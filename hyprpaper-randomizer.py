#!/usr/bin/env python3
"""
hyprpaper-randomizer.py  (v2)

Multi-cache wallpaper selector for hyprpaper.

Cache management:
  --cache-list
  --cache-init NAME --wallpaper-dir PATH [--wallpaper-dir PATH2 ...] --max-depth INT [--no-populate]
  --cache-update NAME
  --cache-switch NAME
  --cache-delete NAME|all

Normal usage (requires an active cache):
  (no args)   — pick and apply next wallpaper
  --back      — rewind to previous wallpaper using global history

Storage layout (~/.cache/hyprpaper-randomizer/):
  active-cache        — text file with the active cache name
  history             — single global history file
  caches/<name>.json  — cache metadata (sources, max_depth, created_at)
  db/<name>.sqlite    — SQLite DB for that cache
"""

from pathlib import Path
import sqlite3
import json
import os
import sys
import time
import random
import subprocess
import argparse

try:
    from PIL import Image
except Exception:
    Image = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
APPDIR = Path.home() / ".cache" / "hyprpaper-randomizer"
ACTIVE_FILE = APPDIR / "active-cache"
HISTFILE = APPDIR / "history"
CACHEDIR = APPDIR / "caches"
DBDIR = APPDIR / "db"

MAXHIST = 50
THROTTLE = Path("/tmp/hyprpaper-randomizer-throttle")
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


# ---------------------------------------------------------------------------
# App directory bootstrap
# ---------------------------------------------------------------------------

def ensure_dirs():
    for d in (APPDIR, CACHEDIR, DBDIR):
        d.mkdir(parents=True, exist_ok=True)
    HISTFILE.touch(exist_ok=True)


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------

def throttle():
    N = int(time.time())
    if THROTTLE.exists():
        try:
            prev = int(THROTTLE.read_text().strip() or "0")
        except Exception:
            prev = 0
        if (N - prev) < 1:
            sys.exit(0)
    THROTTLE.write_text(str(N))


# ---------------------------------------------------------------------------
# Active-cache helpers
# ---------------------------------------------------------------------------

def get_active_cache_name():
    if not ACTIVE_FILE.exists():
        return None
    name = ACTIVE_FILE.read_text().strip()
    return name if name else None


def set_active_cache_name(name):
    ACTIVE_FILE.write_text(name + "\n")


def clear_active_cache():
    if ACTIVE_FILE.exists():
        ACTIVE_FILE.unlink()


# ---------------------------------------------------------------------------
# Cache metadata helpers
# ---------------------------------------------------------------------------

def cache_meta_path(name):
    return CACHEDIR / f"{name}.json"


def cache_db_path(name):
    return DBDIR / f"{name}.sqlite"


def list_cache_names():
    return sorted(p.stem for p in CACHEDIR.glob("*.json"))


def load_cache_meta(name):
    p = cache_meta_path(name)
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


def save_cache_meta(meta):
    p = cache_meta_path(meta["name"])
    with open(p, "w") as f:
        json.dump(meta, f, indent=2)


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def load_history():
    if not HISTFILE.exists():
        return []
    return [ln for ln in HISTFILE.read_text().splitlines() if ln.strip()]


def write_history(lines):
    HISTFILE.write_text("\n".join(lines) + ("\n" if lines else ""))


def clear_history():
    HISTFILE.write_text("")


def append_history(path: Path):
    history = load_history()
    history.append(str(path))
    history = history[-MAXHIST:]
    write_history(history)


# ---------------------------------------------------------------------------
# SQLite DB layer (v2 schema)
# ---------------------------------------------------------------------------

_V2_CREATE = """
CREATE TABLE IF NOT EXISTS images (
    path      TEXT PRIMARY KEY,
    match     INTEGER,
    width     INTEGER,
    height    INTEGER,
    mtime     INTEGER,
    size      INTEGER,
    last_seen INTEGER
)
"""
_V2_IDX_MATCH = "CREATE INDEX IF NOT EXISTS idx_match ON images(match)"
_V2_IDX_LAST  = "CREATE INDEX IF NOT EXISTS idx_last_seen ON images(last_seen)"


def _is_legacy_db(conn):
    """Return True if this DB uses the old 'cache' table schema."""
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cache'")
    return cur.fetchone() is not None


def open_db(db_path: Path):
    """Open (or create) a v2 cache DB at db_path.  Rebuilds legacy DBs."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    if _is_legacy_db(conn):
        # Legacy schema detected — drop and recreate.
        conn.execute("DROP TABLE IF EXISTS cache")
        conn.execute("DROP TABLE IF EXISTS images")
        conn.commit()
    conn.execute(_V2_CREATE)
    conn.execute(_V2_IDX_MATCH)
    conn.execute(_V2_IDX_LAST)
    conn.commit()
    return conn


def db_get_by_path(conn, path: str):
    cur = conn.execute("SELECT * FROM images WHERE path = ?", (path,))
    return cur.fetchone()


def db_upsert(conn, path: str, match: int, width: int, height: int,
              mtime: int, size: int, last_seen: int):
    conn.execute(
        """INSERT INTO images(path, match, width, height, mtime, size, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(path) DO UPDATE SET
               match=excluded.match,
               width=excluded.width,
               height=excluded.height,
               mtime=excluded.mtime,
               size=excluded.size,
               last_seen=excluded.last_seen""",
        (path, match, width, height, mtime, size, last_seen),
    )


def db_touch_last_seen(conn, path: str, ts: int):
    conn.execute("UPDATE images SET last_seen=? WHERE path=?", (ts, path))


def db_prune(conn, scan_started_at: int):
    cur = conn.execute("DELETE FROM images WHERE last_seen < ?", (scan_started_at,))
    return cur.rowcount


def db_count_rows(conn):
    return conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]


def db_count_matched(conn):
    return conn.execute("SELECT COUNT(*) FROM images WHERE match=1").fetchone()[0]


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def file_stat(path: Path):
    try:
        st = path.stat()
        return int(st.st_mtime), int(st.st_size)
    except Exception:
        return 0, 0


def get_image_dimensions(path: Path):
    if Image is not None:
        try:
            with Image.open(path) as im:
                return im.width, im.height
        except Exception:
            pass
    try:
        out = subprocess.check_output(
            ["identify", "-ping", "-format", "%w %h", str(path)],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        parts = out.decode("utf-8", "ignore").strip().split()
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None


def is_acceptable(w, h):
    """Return True if the image is landscape (width strictly greater than height).

    Square images (w == h) are intentionally excluded.
    """
    if not w or not h:
        return False
    return int(w) > int(h)


# ---------------------------------------------------------------------------
# Multi-directory scanning
# ---------------------------------------------------------------------------

def iter_images(sources, maxdepth: int, followlinks: bool = True):
    """Yield image paths from all source directories up to maxdepth."""
    for base in sources:
        base = Path(base)
        if not base.exists():
            continue
        for root, dirs, files in os.walk(str(base), followlinks=followlinks):
            try:
                rel = Path(root).relative_to(base)
                # rel.parts is empty when root == base (depth 0).
                depth = len(rel.parts) if rel.parts else 0
            except Exception:
                depth = maxdepth
            if depth >= maxdepth:
                dirs[:] = []
            for f in files:
                p = Path(root) / f
                if p.suffix.lower() in EXTS:
                    yield p


# ---------------------------------------------------------------------------
# Cache update (with prune)
# ---------------------------------------------------------------------------

def run_cache_update(name: str):
    meta = load_cache_meta(name)
    if meta is None:
        print(f"Error: cache '{name}' not found.")
        sys.exit(1)

    sources = [Path(s) for s in meta["sources"]]
    max_depth = meta.get("max_depth", 2)
    db_path = cache_db_path(name)
    conn = open_db(db_path)

    scan_started_at = int(time.time())
    scanned = updated = unchanged = pruned = matched = nonmatch = 0

    for p in iter_images(sources, max_depth):
        sp = str(p)
        scanned += 1
        mtime, size = file_stat(p)
        row = db_get_by_path(conn, sp)

        if row is None or row["mtime"] != mtime or row["size"] != size:
            dims = get_image_dimensions(p)
            w, h = (dims if dims else (0, 0))
            m = 1 if is_acceptable(w, h) else 0
            db_upsert(conn, sp, m, w, h, mtime, size, scan_started_at)
            updated += 1
            if m:
                matched += 1
            else:
                nonmatch += 1
        else:
            db_touch_last_seen(conn, sp, scan_started_at)
            unchanged += 1
            if row["match"]:
                matched += 1
            else:
                nonmatch += 1

    pruned = db_prune(conn, scan_started_at)
    conn.commit()
    conn.close()

    print(f"Cache '{name}' update complete:")
    print(f"  scanned:   {scanned}")
    print(f"  updated:   {updated}")
    print(f"  unchanged: {unchanged}")
    print(f"  pruned:    {pruned}")
    print(f"  matched:   {matched}")
    print(f"  nonmatch:  {nonmatch}")


# ---------------------------------------------------------------------------
# Choose next wallpaper from a named cache
# ---------------------------------------------------------------------------

def choose_wallpaper(name: str):
    db_path = cache_db_path(name)
    conn = open_db(db_path)
    history_set = set(load_history())

    # Prefer match=1 candidates not in history.
    cur = conn.execute("SELECT path FROM images WHERE match=1")
    candidates = [row[0] for row in cur.fetchall() if row[0] not in history_set]

    if not candidates:
        # Fallback: any match=1 candidate (ignore history).
        cur = conn.execute("SELECT path FROM images WHERE match=1")
        candidates = [row[0] for row in cur.fetchall()]

    conn.close()

    if not candidates:
        return None
    return Path(random.choice(candidates))


# ---------------------------------------------------------------------------
# Apply wallpaper
# ---------------------------------------------------------------------------

def notify(summary: str, body: str = ""):
    """Fire a desktop notification, ignoring errors (e.g. no display / no notify-send)."""
    try:
        cmd = ["notify-send", "hyprpaper-randomizer", summary]
        if body:
            cmd.append(body)
        subprocess.run(cmd, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def apply_wallpaper(p: Path):
    subprocess.run(["hyprctl", "hyprpaper", "wallpaper", f",{str(p)},contain"])


# ---------------------------------------------------------------------------
# --cache-list
# ---------------------------------------------------------------------------

def cmd_cache_list():
    names = list_cache_names()
    active = get_active_cache_name()
    if not names:
        print("No caches found. Use --cache-init to create one.")
        return
    for name in names:
        marker = "*" if name == active else " "
        meta = load_cache_meta(name)
        sources = meta.get("sources", []) if meta else []
        max_depth = meta.get("max_depth", "?") if meta else "?"
        db_path = cache_db_path(name)
        if db_path.exists():
            try:
                conn = open_db(db_path)
                total = db_count_rows(conn)
                matched = db_count_matched(conn)
                conn.close()
                db_info = f"  db: {matched}/{total} matched"
            except Exception:
                db_info = "  db: (error)"
        else:
            db_info = "  db: (empty)"
        print(f"[{marker}] {name}  (max_depth={max_depth}){db_info}")
        for s in sources:
            print(f"      source: {s}")


# ---------------------------------------------------------------------------
# --cache-init
# ---------------------------------------------------------------------------

def cmd_cache_init(name: str, sources: list, max_depth: int, populate: bool):
    meta = {
        "name": name,
        "sources": [str(Path(s).expanduser()) for s in sources],
        "max_depth": max_depth,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_cache_meta(meta)
    set_active_cache_name(name)
    print(f"Cache '{name}' initialized.")
    print(f"  sources:   {meta['sources']}")
    print(f"  max_depth: {max_depth}")
    print(f"  active:    yes")

    if populate:
        run_cache_update(name)
        notify(f"Cache '{name}' initialized and populated.")
    else:
        notify(f"Cache '{name}' initialized (no populate).")


# ---------------------------------------------------------------------------
# --cache-update
# ---------------------------------------------------------------------------

def cmd_cache_update(name: str):
    if load_cache_meta(name) is None:
        print(f"Error: cache '{name}' not found.")
        names = list_cache_names()
        if names:
            print("Available caches:", ", ".join(names))
        sys.exit(1)
    run_cache_update(name)


# ---------------------------------------------------------------------------
# --cache-switch
# ---------------------------------------------------------------------------

def cmd_cache_switch(name: str):
    if load_cache_meta(name) is None:
        print(f"Error: cache '{name}' does not exist.")
        print()
        cmd_cache_list()
        print()
        print(f"To create it:  hyprpaper-randomizer --cache-init {name} --wallpaper-dir PATH --max-depth 2")
        notify(f"Cache '{name}' not found. Use --cache-init.")
        sys.exit(1)

    set_active_cache_name(name)
    # Clear global history on cache switch so the new cache starts fresh.
    clear_history()

    # Ensure DB is populated.
    db_path = cache_db_path(name)
    need_update = True
    if db_path.exists():
        try:
            conn = open_db(db_path)
            if db_count_matched(conn) > 0:
                need_update = False
            conn.close()
        except Exception:
            pass

    if need_update:
        print(f"Cache '{name}' is empty — running update...")
        run_cache_update(name)

    choice = choose_wallpaper(name)
    if choice is None:
        msg = f"Cache '{name}' has no acceptable wallpapers."
        print(msg)
        notify(msg)
        sys.exit(1)

    apply_wallpaper(choice)
    append_history(choice)
    print(f"Switched to cache '{name}'. Applied: {choice}")
    notify(f"Switched to cache '{name}'.")


# ---------------------------------------------------------------------------
# --cache-delete
# ---------------------------------------------------------------------------

def cmd_cache_delete(target: str):
    active = get_active_cache_name()

    if target == "all":
        names = list_cache_names()
        for name in names:
            _delete_one_cache(name)
        clear_history()
        clear_active_cache()
        print("Deleted all caches, history, and active-cache.")
        notify("All caches deleted.")
        return

    _delete_one_cache(target)
    if active == target:
        clear_active_cache()
        print(f"Active cache '{target}' deleted; active-cache cleared.")
    else:
        print(f"Cache '{target}' deleted.")
    notify(f"Cache '{target}' deleted.")


def _delete_one_cache(name: str):
    meta_p = cache_meta_path(name)
    db_p = cache_db_path(name)
    if meta_p.exists():
        meta_p.unlink()
    if db_p.exists():
        db_p.unlink()


# ---------------------------------------------------------------------------
# Normal run
# ---------------------------------------------------------------------------

def cmd_run():
    name = get_active_cache_name()
    if name is None:
        msg = "No active cache. Use --cache-init NAME --wallpaper-dir PATH --max-depth INT"
        print(msg)
        notify(msg)
        sys.exit(1)

    if load_cache_meta(name) is None:
        msg = f"Active cache '{name}' metadata missing. Re-initialize with --cache-init."
        print(msg)
        notify(msg)
        sys.exit(1)

    choice = choose_wallpaper(name)
    if choice is None:
        msg = f"No acceptable wallpapers in cache '{name}'. Try --cache-update {name}."
        print(msg)
        notify(msg)
        sys.exit(1)

    apply_wallpaper(choice)
    append_history(choice)
    print(f"Applied wallpaper: {choice}")


# ---------------------------------------------------------------------------
# --back
# ---------------------------------------------------------------------------

def cmd_back():
    history = load_history()
    if len(history) < 2:
        print("No previous wallpaper in history.")
        notify("No previous wallpaper in history.")
        sys.exit(1)
    prev = history[-2]
    write_history(history[:-1])
    apply_wallpaper(Path(prev))
    print(f"Reverted to previous wallpaper: {prev}")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="hyprpaper-randomizer v2 — multi-cache wallpaper selector",
    )

    # Cache management
    parser.add_argument("--cache-list", action="store_true",
                        help="list all caches")
    parser.add_argument("--cache-init", metavar="NAME",
                        help="initialize a new cache (sets it as active)")
    parser.add_argument("--wallpaper-dir", metavar="PATH", action="append", dest="wallpaper_dirs",
                        help="wallpaper source directory (repeatable, used with --cache-init)")
    parser.add_argument("--max-depth", type=int, default=2,
                        help="maximum directory depth to scan (used with --cache-init, default: 2)")
    parser.add_argument("--no-populate", action="store_true",
                        help="skip initial population when using --cache-init")
    parser.add_argument("--cache-update", metavar="NAME",
                        help="update and prune a cache DB")
    parser.add_argument("--cache-switch", metavar="NAME",
                        help="switch to a cache, clear history, and apply a wallpaper immediately")
    parser.add_argument("--cache-delete", metavar="NAME",
                        help="delete a cache (or 'all')")

    # Normal usage
    parser.add_argument("--back", action="store_true",
                        help="rewind to previous wallpaper using global history")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    throttle()
    ensure_dirs()

    args = parse_args()

    if args.cache_list:
        cmd_cache_list()
        return

    if args.cache_init:
        if not args.wallpaper_dirs:
            print("Error: --cache-init requires at least one --wallpaper-dir PATH")
            sys.exit(2)
        cmd_cache_init(
            name=args.cache_init,
            sources=args.wallpaper_dirs,
            max_depth=args.max_depth,
            populate=not args.no_populate,
        )
        return

    if args.cache_update:
        cmd_cache_update(args.cache_update)
        return

    if args.cache_switch:
        cmd_cache_switch(args.cache_switch)
        return

    if args.cache_delete:
        cmd_cache_delete(args.cache_delete)
        return

    if args.back:
        cmd_back()
        return

    cmd_run()


if __name__ == "__main__":
    main()

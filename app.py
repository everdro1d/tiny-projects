#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from typing import Any
from mutagen import File as MutagenFile
import threading

# === DEFAULT CONFIGURATION (may be overridden at runtime) ===
PROJECT_ROOT = os.path.abspath("ipod-music-downloader")
MUSIC_ROOT = os.path.join(PROJECT_ROOT, "music")
INPUT_DIR = os.path.join(MUSIC_ROOT, "Music")
SHA1_DIR = os.path.join(MUSIC_ROOT, "sha1sum")
OUT_DIR = os.path.join(MUSIC_ROOT, "out")
UNKNOWN_ARTIST_LOG = os.path.join(MUSIC_ROOT, "UNKNOWN-ARTIST.txt")
MISSING_TITLE_LOG = os.path.join(MUSIC_ROOT, "MISSING-TITLE.txt")
FAILED_SHA1_LOG = os.path.join(MUSIC_ROOT, "FAILED-SHA1SUM.txt")

# Module-level flags (set in main)
DRY_RUN = False

# Safety parameters
MAX_COMPONENT_LENGTH = 200  # conservative per-path-component max
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Locks for thread-safety around filesystem mutations and log writes
# Use an RLock so the same thread can re-acquire the lock safely (prevents self-deadlock).
LOG_LOCK = threading.RLock()


def sha1sum(file_path: str, block_size: int = 65536) -> str:
    """Return SHA1 checksum for a file."""
    sha1 = hashlib.sha1()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(block_size), b""):
            sha1.update(chunk)
    return sha1.hexdigest()


def safe_text(value: Any, fallback: str) -> str:
    """Return value if non-empty, otherwise fallback."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def sanitize_component(name: str, max_length: int = MAX_COMPONENT_LENGTH) -> str:
    """
    Produce a filesystem-safe single path component from name.
    - Normalize unicode
    - Replace path separators and control chars with underscore
    - Keep a conservative set of characters (letters, numbers, space, ., -, _, (), [])
    - Trim length, remove trailing dots/spaces
    - Avoid Windows reserved names by appending underscore if needed
    """
    if not name:
        return ""

    # Normalize
    name = unicodedata.normalize("NFKC", name)

    # Remove control characters
    name = "".join(ch for ch in name if ord(ch) >= 0x20)

    # Replace path separators with underscore
    name = name.replace(os.path.sep, "_")
    if os.path.altsep:
        name = name.replace(os.path.altsep, "_")

    # Allow a limited safe charset; replace others with underscore
    name = re.sub(r'[^\w\s.\-\_\(\)\[\],]', "_", name, flags=re.UNICODE)

    # Collapse runs of underscores/spaces
    name = re.sub(r"[ \t]+", " ", name)
    name = re.sub(r"_+", "_", name)

    # Trim and remove trailing dots/spaces (problematic on Windows)
    name = name.strip(" .")

    # Trim to max length
    if len(name) > max_length:
        name = name[: max_length].rstrip(" .")

    # Avoid reserved Windows names (case-insensitive)
    base_upper = name.split(".")[0].upper()
    if base_upper in WINDOWS_RESERVED_NAMES:
        name = name + "_"

    # If result empty, return a single underscore
    if not name:
        return "_"

    return name


def safe_filename(artist: str, title: str, ext: str) -> str:
    """Return a sanitized filename constructed from artist and title and optional extension."""
    artist_s = sanitize_component(artist)
    title_s = sanitize_component(title)
    base = f"{artist_s} - {title_s}".strip()
    # Ensure base isn't too long so extension can fit
    max_base = MAX_COMPONENT_LENGTH - (len(ext) + 1 if ext else 0)
    if len(base) > max_base:
        base = base[:max_base].rstrip(" ._")
    if ext:
        return f"{base}.{sanitize_component(ext, max_length=50)}"
    return base


def append_to_log(filepath: str, entry: str) -> None:
    """Append an entry (one line) to a text log file. Respects DRY_RUN and is thread-safe."""
    if DRY_RUN:
        logging.info("Dry-run: would append to log %s: %s", filepath, entry)
        return
    # Protect log writes with a lock to avoid interleaved writes
    with LOG_LOCK:
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as f:
            _ = f.write(entry + "\n")


def ensure_within_out(dest_path: str) -> bool:
    """
    Ensure dest_path is inside OUT_DIR. Returns True if safe.
    This prevents directory traversal or accidental writes outside the intended output directory.
    Uses realpath for safety against symlink escapes.
    """
    out_real = os.path.realpath(OUT_DIR)
    dest_real = os.path.realpath(dest_path)
    try:
        common = os.path.commonpath([out_real, dest_real])
    except ValueError:
        # On different drives on Windows, abort
        logging.error("Destination %s is on a different drive than OUT_DIR %s", dest_real, out_real)
        return False
    if common != out_real and not dest_real.startswith(out_real + os.sep):
        logging.error("Refusing to write outside OUT_DIR: %s", dest_real)
        return False
    return True


def unique_path(dest_path: str) -> str:
    """
    If dest_path exists, generate a unique path by appending ' (n)' before the extension.
    """
    if not os.path.exists(dest_path):
        return dest_path

    base, ext = os.path.splitext(dest_path)
    counter = 1
    while True:
        candidate = f"{base} ({counter}){ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def write_sha1_log_atomic(sha1_dir: str, original_sha1: str, content: str) -> None:
    """Write sha1 log atomically (thread-safe)."""
    if DRY_RUN:
        logging.info("Dry-run: would write sha1 log for %s: %s", original_sha1, content)
        return
    os.makedirs(sha1_dir, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=f".{original_sha1}.", dir=sha1_dir)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        final_path = os.path.join(sha1_dir, f"{original_sha1}.txt")
        # Use a lock to avoid races replacing same file
        with LOG_LOCK:
            os.replace(tmp_path, final_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def process_file(file_path: str) -> None:
    logging.info("Processing file: %s", file_path)
    if not os.path.isfile(file_path):
        logging.debug("Skipping, not a file: %s", file_path)
        return

    # Compute original sha1 and extract metadata before touching shared filesystem state
    try:
        original_sha1 = sha1sum(file_path)
    except Exception as e:
        logging.error("Failed to compute SHA1 for %s: %s", file_path, e)
        return

    filename = os.path.basename(file_path)
    ext = os.path.splitext(filename)[1].lstrip(".")
    ext = ext[:50]  # avoid overly long extensions

    # Extract metadata
    audio = None
    try:
        audio = MutagenFile(file_path, easy=True)
    except Exception as e:
        logging.warning("Mutagen failed to read %s: %s", file_path, e)
        audio = None

    if audio is None:
        artist = "UNKNOWN ARTIST"
        title = "MISSING TITLE"
        genre = "MISC GENRE"
        logging.debug("No metadata found for %s", file_path)
    else:
        artist = safe_text(audio.get("artist", [None])[0] if "artist" in audio else None, "UNKNOWN ARTIST")
        title = safe_text(audio.get("title", [None])[0] if "title" in audio else None, "MISSING TITLE")
        genre = safe_text(audio.get("genre", [None])[0] if "genre" in audio else None, "MISC GENRE")
        logging.debug("Extracted metadata for %s - artist: %s, title: %s, genre: %s", file_path, artist, title, genre)

    # Prepare destination names (sanitized)
    genre_folder_name = sanitize_component(genre)
    genre_folder = os.path.join(OUT_DIR, genre_folder_name)
    dest_filename = safe_filename(artist, title, ext)
    dest_path = os.path.join(genre_folder, dest_filename)

    # Ensure dest_path is within OUT_DIR using realpath check (defends against symlink escapes)
    if not ensure_within_out(dest_path):
        append_to_log(FAILED_SHA1_LOG, f"unsafe-dest: {dest_path}")
        return

    logging.info("Will copy to: %s", dest_path)

    if DRY_RUN:
        logging.info("Dry-run: would ensure folder exists: %s", genre_folder)
        logging.info("Dry-run: would copy file: %s -> %s", file_path, dest_path)
        logging.info("Dry-run: would verify SHA1 after copy and retry on mismatch")
        logging.info("Dry-run: would write sha1 log to: %s", os.path.join(SHA1_DIR, f"{original_sha1}.txt"))
        if "UNKNOWN ARTIST" in artist:
            logging.info("Dry-run: would append to UNKNOWN_ARTIST_LOG: %s", dest_path)
        if "MISSING TITLE" in title:
            logging.info("Dry-run: would append to MISSING_TITLE_LOG: %s", dest_path)
        return

    # Ensure directories exist (best-effort)
    os.makedirs(genre_folder, exist_ok=True)
    os.makedirs(SHA1_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    # Copy to a temporary file inside the target genre folder (so rename is atomic and stays on same FS)
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=genre_folder)
        os.close(tmp_fd)
    except Exception as e:
        logging.error("Failed to create temporary file in %s: %s", genre_folder, e)
        append_to_log(FAILED_SHA1_LOG, f"tmp-create-fail: {genre_folder} for {file_path}")
        return

    try:
        try:
            shutil.copy2(file_path, tmp_path)
            logging.debug("Copied to temp file %s", tmp_path)
        except Exception as e:
            logging.error("Failed to copy to temp file %s: %s", tmp_path, e)
            append_to_log(FAILED_SHA1_LOG, tmp_path)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return

        try:
            copied_sha1_tmp = sha1sum(tmp_path)
        except Exception as e:
            logging.error("Failed to compute SHA1 for temp file %s: %s", tmp_path, e)
            append_to_log(FAILED_SHA1_LOG, tmp_path)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return

        if copied_sha1_tmp != original_sha1:
            logging.error(
                "SHA1 mismatch after temp copy for %s (original=%s copied=%s). Aborting.",
                file_path,
                original_sha1,
                copied_sha1_tmp,
            )
            append_to_log(FAILED_SHA1_LOG, tmp_path)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return

        # Minimal critical section: decide final destination and atomically move temp into place
        with LOG_LOCK:
            final_dest = dest_path
            if os.path.exists(final_dest):
                try:
                    existing_sha1 = sha1sum(final_dest)
                except Exception:
                    existing_sha1 = None
                if existing_sha1 == original_sha1:
                    logging.info("Destination already exists with identical content, skipping copy: %s", final_dest)
                    # nothing to do, remove temp and return
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                    # still write sha1 log (optional) — mimic previous behaviour: write sha1 log linking source to existing dest
                    sha1_content = f"{file_path}\n{original_sha1}\n{final_dest}\n{existing_sha1 or ''}\n"
                    write_sha1_log_atomic(SHA1_DIR, original_sha1, sha1_content)
                    # Log incomplete metadata
                    if "UNKNOWN ARTIST" in artist:
                        append_to_log(UNKNOWN_ARTIST_LOG, final_dest)
                    if "MISSING TITLE" in title:
                        append_to_log(MISSING_TITLE_LOG, final_dest)
                    return
                else:
                    # pick a unique path
                    new_dest = unique_path(final_dest)
                    logging.warning("Destination exists with different content. Using unique path: %s", new_dest)
                    final_dest = new_dest

            # final safety check
            if not ensure_within_out(final_dest):
                append_to_log(FAILED_SHA1_LOG, f"unsafe-dest-after-unique: {final_dest}")
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                return

            # Attempt atomic move
            try:
                os.replace(tmp_path, final_dest)
                logging.info("Atomically moved temp to final dest: %s", final_dest)
            except Exception as e:
                logging.error("Failed to move temp file to final destination %s: %s", final_dest, e)
                append_to_log(FAILED_SHA1_LOG, final_dest)
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                return

            # Write sha1 log atomically
            sha1_content = f"{file_path}\n{original_sha1}\n{final_dest}\n{copied_sha1_tmp}\n"
            write_sha1_log_atomic(SHA1_DIR, original_sha1, sha1_content)

            # Log incomplete metadata
            if "UNKNOWN ARTIST" in artist:
                append_to_log(UNKNOWN_ARTIST_LOG, final_dest)
            if "MISSING TITLE" in title:
                append_to_log(MISSING_TITLE_LOG, final_dest)

    finally:
        # Ensure tmp file doesn't linger if it wasn't moved
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    global DRY_RUN, OUT_DIR, MUSIC_ROOT, INPUT_DIR, SHA1_DIR, UNKNOWN_ARTIST_LOG, MISSING_TITLE_LOG, FAILED_SHA1_LOG

    parser = argparse.ArgumentParser(description="Process music files into organized folders and record SHA1 checksums.")
    parser.add_argument("--dry-run", action="store_true", help="Perform a trial run with no filesystem changes; logs actions to the console.")
    parser.add_argument("--input-dir", "-i", required=True, help="Directory to scan for music files. (required)")
    parser.add_argument("--output-dir", "-o", required=True, help="Directory under which to place organized output (required).")
    parser.add_argument("--verbose", "-v", action="store_true", default=False, help="Enable debug logging. Disabled by default.")
    args = parser.parse_args(argv)

    DRY_RUN = args.dry_run

    # Resolve logical and real paths for the input directory.
    # We keep both:
    # - INPUT_ABS (logical abspath) is used to derive MUSIC_ROOT for logs (so a symlinked Music/ dir keeps its project-local parent).
    # - INPUT_REAL (realpath) is used to detect the real source device/mount and defend against writing back to the iPod.
    INPUT_ABS = os.path.abspath(args.input_dir)
    INPUT_REAL = os.path.realpath(INPUT_ABS)

    # Derive music root as the parent directory of the logical input path (so logs stay under your project music/ folder when Music is a symlink)
    MUSIC_ROOT = os.path.abspath(os.path.join(INPUT_ABS, os.pardir))

    # Put sha1 and logs under MUSIC_ROOT
    SHA1_DIR = os.path.join(MUSIC_ROOT, "sha1sum")
    UNKNOWN_ARTIST_LOG = os.path.join(MUSIC_ROOT, "UNKNOWN-ARTIST.txt")
    MISSING_TITLE_LOG = os.path.join(MUSIC_ROOT, "MISSING-TITLE.txt")
    FAILED_SHA1_LOG = os.path.join(MUSIC_ROOT, "FAILED-SHA1SUM.txt")

    # Resolve output dir both logically and by realpath for safety checks
    OUT_DIR = os.path.abspath(args.output_dir)
    OUT_DIR_REAL = os.path.realpath(OUT_DIR)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(stream=sys.stdout, level=log_level, format="%(levelname)s: %(message)s")

    logging.info(
        "Starting music file processing. dry-run=%s input_abs=%s input_real=%s music_root=%s output_abs=%s output_real=%s",
        DRY_RUN,
        INPUT_ABS,
        INPUT_REAL,
        MUSIC_ROOT,
        OUT_DIR,
        OUT_DIR_REAL,
    )

    # Safety checks to prevent accidental writes inside the input tree.
    # If the resolved output path is on the same device as the resolved input path, refuse to proceed (unless dry-run).
    try:
        input_dev = os.stat(INPUT_REAL).st_dev
    except Exception:
        input_dev = None

    try:
        output_dev = os.stat(OUT_DIR_REAL).st_dev
    except Exception:
        output_dev = None

    # Refuse if OUT_DIR is (logically) inside the input directory OR (realpath) inside the input realpath.
    if OUT_DIR.startswith(INPUT_ABS + os.sep) or OUT_DIR_REAL.startswith(INPUT_REAL + os.sep):
        logging.error("Refusing to run: output directory is inside the input directory. This could write to the source device.")
        logging.error("INPUT_ABS=%s INPUT_REAL=%s OUT_DIR=%s OUT_DIR_REAL=%s", INPUT_ABS, INPUT_REAL, OUT_DIR, OUT_DIR_REAL)
        return 2

    # If real devices are known and identical, refuse to write (prevents writing to the iPod)
    if (input_dev is not None) and (output_dev is not None) and (input_dev == output_dev):
        logging.error("Refusing to run: output directory appears to be on the same device as the input (likely the iPod).")
        logging.error("INPUT_REAL=%s (dev=%s) OUT_DIR_REAL=%s (dev=%s)", INPUT_REAL, input_dev, OUT_DIR_REAL, output_dev)
        logging.error("Choose an output directory on your local filesystem (not on the iPod) or run with --dry-run to inspect actions.")
        return 2

    # Only create top-level directories if not in dry-run mode
    if not DRY_RUN:
        os.makedirs(SHA1_DIR, exist_ok=True)
        os.makedirs(OUT_DIR, exist_ok=True)

    # Collect all files first
    file_paths: list[str] = []
    for root, _, files in os.walk(INPUT_ABS):
        for filename in files:
            file_paths.append(os.path.join(root, filename))

    for file_path in file_paths:
        process_file(file_path)

    logging.info("Processing complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

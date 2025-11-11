#!/usr/bin/env python3
"""
Create Spotify playlists from a local music folder structure and add tracks by searching Spotify.

Behavior:
- Load SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET from .env (uses python-dotenv)
- OAuth the user with redirect URI http://127.0.0.1:8080/callback
- Walk the input directory (--input / -i), skipping folders listed in --exclude / -e
- Parent folders become playlists (basename of each folder containing files)
- Filenames must be in the format: "%artist% - %track name%.%ext%"
- Search Spotify for "artist:%artist% track:%track name%" and use the first match's uri
- Create playlists for the authenticated user and add found tracks (100 URIs per request max)
- Handle 429 Rate limits by reading Retry-After and retrying after (x + 1) seconds

Added later:
1. Cache successful URIs (JSON file) and prefer cached URIs over sending a network request.
2. Added --force-search flag to override cache preference and always query Spotify.
3. If a track is not found, attempt a cleaned retry by removing underscores, any "Part n", and any bracketed sections (with their contents) from file names and try again.
   Example: "guy1 - The first n_ top Part 1 (beans)" -> cleaned to "guy1 - The first n top"
4. If the artist contains "UNKNOWN ARTIST" and the track does not contain "Titel" then try searching using only the title.
5. Added --not-found-log to record playlist and artist - track for tracks that remain unfound after all attempts.

Usage:
    python app.py -i /path/to/music -e "Podcasts" -e "Audiobooks"

Options added:
    --cache-file     Path to cache file (default: .spotify_uri_cache.json)
    --force-search   Do not prefer cache; query Spotify every time
    --not-found-log  Path to append log file for tracks not found after all search attempts (default: .not_found_tracks.log)
"""
import os
import sys
import argparse
import time
import logging
import json
import re
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("spotify-folder-playlist")

# Allowed audio extensions (common)
AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aac", ".wma"}


def chunkify(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def api_call(func, *args, **kwargs):
    """
    Wrapper to call Spotipy functions and handle 429 responses.

    If a SpotifyException with http_status == 429 is raised, read Retry-After header,
    sleep for int(retry_after) + 1 seconds, and retry. Retries until success.
    Other exceptions are raised.
    """
    while True:
        try:
            return func(*args, **kwargs)
        except SpotifyException as e:
            status = getattr(e, "http_status", None)
            headers = getattr(e, "headers", {}) or {}
            if status == 429:
                retry_after = headers.get("Retry-After", headers.get("retry-after"))
                try:
                    x = int(retry_after)
                except Exception:
                    x = 1
                wait = x + 1
                logger.warning("Rate limited by Spotify (429). Retry-After=%s. Waiting %s seconds.", retry_after, wait)
                time.sleep(wait)
                continue
            else:
                # re-raise other spotify exceptions
                raise


def parse_args():
    p = argparse.ArgumentParser(description="Create Spotify playlists from local music folders.")
    p.add_argument("-i", "--input", required=True, help="Path to root music folder.")
    p.add_argument(
        "-e",
        "--exclude",
        action="append",
        default=[],
        help="Folder name to exclude (can be specified multiple times). Matches any path component. Example: -e Podcasts -e _archived",
    )
    p.add_argument(
        "--public",
        action="store_true",
        help="Create playlists as public instead of private (default is private).",
    )
    p.add_argument("--dry-run", action="store_true", help="Do everything except create playlists or add tracks.")
    p.add_argument(
        "--cache-file",
        default=".spotify_uri_cache.json",
        help="Path to JSON cache file for storing successful artist/track -> uri mappings. Default: .spotify_uri_cache.json",
    )
    p.add_argument(
        "--force-search",
        action="store_true",
        help="Override cache preference and always query Spotify (do not use cached URIs).",
    )
    p.add_argument(
        "--not-found-log",
        default=".not_found_tracks.log",
        help="Path to append log file for tracks not found after all search attempts. Default: .not_found_tracks.log",
    )
    return p.parse_args()


def load_secrets():
    """
    Load secrets from .env in current directory (or existing environment).
    Expected keys:
      - SPOTIPY_CLIENT_ID
      - SPOTIPY_CLIENT_SECRET
    """
    load_dotenv(dotenv_path="./.env")
    client_id = os.getenv("SPOTIPY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.error("SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET must be set in .env or environment.")
        sys.exit(2)
    return client_id, client_secret


def should_exclude_path(path, input_root, excludes):
    """
    Return True if any path component (relative to input_root) is in excludes.
    """
    rel = os.path.relpath(path, input_root)
    if rel == ".":
        components = []
    else:
        components = rel.split(os.sep)
    for comp in components:
        if comp in excludes:
            return True
    return False


def walk_music_folder(input_root, excludes):
    """
    Walk input_root and return mapping: playlist_name -> list of (artist, track, filepath)
    Playlist name will be the basename of each directory that contains files.
    Files not matching the expected filename pattern are skipped with a warning.
    """
    playlists = defaultdict(list)
    input_root = os.path.abspath(input_root)

    if not os.path.isdir(input_root):
        logger.error("Input path is not a directory: %s", input_root)
        sys.exit(2)

    for dirpath, dirnames, filenames in os.walk(input_root):
        # Skip directories that match excludes
        if should_exclude_path(dirpath, input_root, excludes):
            logger.debug("Skipping excluded folder: %s", dirpath)
            continue

        # Filter filenames to audio extensions
        audio_files = [f for f in filenames if os.path.splitext(f)[1].lower() in AUDIO_EXTS]
        if not audio_files:
            continue

        playlist_name = os.path.basename(dirpath) or os.path.basename(input_root)
        for fname in audio_files:
            name_no_ext = os.path.splitext(fname)[0]
            # Expect "%artist% - %track name%"
            if " - " not in name_no_ext:
                logger.warning("Skipping file with unexpected name (no ' - '): %s", os.path.join(dirpath, fname))
                continue
            artist, track = name_no_ext.split(" - ", 1)
            artist = artist.strip()
            track = track.strip()
            if not artist or not track:
                logger.warning("Skipping file with empty artist or track: %s", os.path.join(dirpath, fname))
                continue
            filepath = os.path.join(dirpath, fname)
            playlists[playlist_name].append({"artist": artist, "track": track, "path": filepath})
    return playlists


def _make_cache_key(artist, track):
    """
    Make a normalized cache key for artist/track pair.
    Lowercase and collapse whitespace so lookups are consistent.
    """
    norm = f"{artist or ''}\x1f{track or ''}".lower()
    # collapse whitespace
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def load_cache(path):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            logger.debug("Loaded cache with %d entries from %s", len(data), path)
            return data
    except Exception as e:
        logger.warning("Failed to load cache %s: %s", path, e)
    return {}


def save_cache(path, data):
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        logger.debug("Saved cache with %d entries to %s", len(data), path)
    except Exception as e:
        logger.warning("Failed to save cache %s: %s", path, e)


def find_track_uri(sp, query):
    """
    Low level search helper: search Spotify using an explicit query string (q)
    and return the first track uri or None.
    """
    logger.debug("Searching Spotify q=%s", query)
    res = api_call(sp.search, q=query, type="track", limit=1)
    tracks = res.get("tracks", {}).get("items", [])
    if not tracks:
        return None
    uri = tracks[0].get("uri")
    return uri


def clean_name(s):
    """
    Clean the file-name-derived string:
      - remove underscores (replace with space)
      - remove bracketed contents ((), [], {})
      - remove "Part <n>" occurrences
      - collapse whitespace and trim
    """
    if not s:
        return s
    # replace underscores with spaces
    out = s.replace("_", " ")
    # remove bracketed content
    out = re.sub(r"[\(\[\{].*?[\)\]\}]", "", out)
    # remove "Part N" (case-insensitive)
    out = re.sub(r"\bPart\s*\d+\b", "", out, flags=re.IGNORECASE)
    # collapse multiple spaces and trim
    out = re.sub(r"\s+", " ", out).strip()
    return out


def get_track_uri_with_cache(sp, artist, track, cache, force_search=False):
    """
    Try to get a track URI:
      - Prefer cache unless force_search is True.
      - Special case: if artist contains "UNKNOWN ARTIST" and track does not contain "Titel",
        attempt searching with only the title.
      - If initial attempts fail, try again with cleaned artist/track (remove underscores,
        "Part n", and bracketed contents) and try to use cache or search.
      - If a URI is found, cache it (under normalized keys).
    Returns (uri, used_cache_bool)
    """
    # normalize inputs for decisions
    artist_str = artist or ""
    track_str = track or ""

    # helpers
    def cache_get(a, t):
        return cache.get(_make_cache_key(a, t))

    def cache_set(a, t, uri):
        cache[_make_cache_key(a, t)] = uri

    # 1) Check cache first unless force_search
    key_uri = None
    if not force_search:
        key_uri = cache_get(artist_str, track_str)
        if key_uri:
            logger.debug("Cache hit for '%s - %s'", artist_str, track_str)
            return key_uri, True

    # 2) Special case: UNKNOWN ARTIST -> search by title only (unless title contains 'Titel')
    if "UNKNOWN ARTIST" in artist_str.upper() and "titel" not in track_str.lower():
        q = f'track:{track_str}'
        uri = find_track_uri(sp, q)
        if uri:
            logger.info("Found (by title only) for %s - %s", artist_str, track_str)
            cache_set(artist_str, track_str, uri)
            return uri, False

    # 3) Standard search with both artist and track
    q = f'artist:{artist_str} track:{track_str}'
    uri = find_track_uri(sp, q)
    if uri:
        logger.debug("Found on Spotify for '%s - %s'", artist_str, track_str)
        cache_set(artist_str, track_str, uri)
        return uri, False

    # 4) Not found: try cleaned names
    cleaned_artist = clean_name(artist_str)
    cleaned_track = clean_name(track_str)

    # if cleaning changed, check cache for cleaned combination (unless force_search)
    if (cleaned_artist, cleaned_track) != (artist_str, track_str):
        if not force_search:
            key_uri = cache_get(cleaned_artist, cleaned_track)
            if key_uri:
                logger.debug("Cache hit for cleaned '%s - %s' (original '%s - %s')", cleaned_artist, cleaned_track, artist_str, track_str)
                # store under original key too for faster future lookups
                cache_set(artist_str, track_str, key_uri)
                return key_uri, True

        # Special-case unknown artist after cleaning
        if "UNKNOWN ARTIST" in cleaned_artist.upper() and "titel" not in cleaned_track.lower():
            q = f'track:{cleaned_track}'
            uri = find_track_uri(sp, q)
            if uri:
                logger.info("Found (by title only, after cleaning) for %s - %s", cleaned_artist, cleaned_track)
                cache_set(artist_str, track_str, uri)
                cache_set(cleaned_artist, cleaned_track, uri)
                return uri, False

        # Try artist+track with cleaned strings
        q = f'artist:{cleaned_artist} track:{cleaned_track}'
        uri = find_track_uri(sp, q)
        if uri:
            logger.info("Found on Spotify after cleaning for '%s - %s' (orig '%s - %s')", cleaned_artist, cleaned_track, artist_str, track_str)
            cache_set(artist_str, track_str, uri)
            cache_set(cleaned_artist, cleaned_track, uri)
            return uri, False

    # 5) No result
    return None, False


def create_playlist(sp, user_id, name, public=False, dry_run=False):
    """
    Create a playlist and return its id. If dry_run is True, we just return a placeholder ID.
    """
    if dry_run:
        logger.info("[dry-run] Would create playlist: %s", name)
        return f"dryrun-{name}"
    payload = api_call(sp.user_playlist_create, user=user_id, name=name, public=public, description="Created by spotify-folder-playlist")
    playlist_id = payload.get("id")
    logger.info("Created playlist '%s' (id=%s)", name, playlist_id)
    return playlist_id


def add_tracks_to_playlist(sp, playlist_id, uris, dry_run=False):
    """
    Add a list of URIs to playlist_id, chunking at 100 per request.
    """
    if not uris:
        return
    for chunk in chunkify(uris, 100):
        if dry_run:
            logger.info("[dry-run] Would add %d tracks to playlist %s", len(chunk), playlist_id)
            continue
        api_call(sp.playlist_add_items, playlist_id, chunk)
        logger.info("Added %d tracks to playlist %s", len(chunk), playlist_id)


def log_not_found(log_path, playlist_name, artist, track, filepath=None):
    """
    Append an entry to the not-found log file with timestamp, playlist, artist - track, and optional path.
    """
    try:
        ts = datetime.utcnow().isoformat() + "Z"
        entry = f"{ts} | {playlist_name} | {artist} - {track}"
        if filepath:
            entry += f" | {filepath}"
        entry += "\n"
        # Ensure directory exists
        log_dir = os.path.dirname(os.path.abspath(log_path)) or "."
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except Exception:
                pass
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(entry)
        logger.debug("Appended not-found entry to %s: %s - %s", log_path, artist, track)
    except Exception as e:
        logger.warning("Failed to write not-found log to %s: %s", log_path, e)


def main():
    args = parse_args()
    client_id, client_secret = load_secrets()

    redirect_uri = "http://127.0.0.1:8080/callback"
    scope = "playlist-modify-private playlist-modify-public"

    logger.info("Starting Spotify folder -> playlists tool")

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=scope,
        open_browser=True,
    )

    sp = spotipy.Spotify(auth_manager=auth_manager)

    # Get authenticated user
    user = api_call(sp.current_user)
    user_id = user.get("id")
    logger.info("Authenticated as user: %s", user_id)

    # Walk folder and build playlist mapping
    playlists = walk_music_folder(args.input, args.exclude)
    if not playlists:
        logger.info("No playlists found in the given input directory.")
        return

    logger.info("Found %d playlists to process.", len(playlists))

    # Load cache
    cache = load_cache(args.cache_file)

    # Create playlists
    playlist_id_map = {}
    for pl_name in playlists:
        pl_id = create_playlist(sp, user_id, pl_name, public=args.public, dry_run=args.dry_run)
        playlist_id_map[pl_name] = pl_id

    # For each playlist, search spotify for each track and collect URIs
    for pl_name, tracks in playlists.items():
        logger.info("Processing playlist '%s' with %d tracks", pl_name, len(tracks))
        uris = []
        for entry in tracks:
            artist = entry["artist"]
            track = entry["track"]
            try:
                uri, used_cache = get_track_uri_with_cache(sp, artist, track, cache, force_search=args.force_search)
            except SpotifyException as e:
                # If we get rate limited or similar, api_call will have handled 429, otherwise re-raise
                logger.exception("Spotify error searching for %s - %s: %s", artist, track, e)
                uri = None
                used_cache = False
            if uri:
                if used_cache:
                    logger.debug("Using cached uri for %s - %s", artist, track)
                else:
                    logger.debug("Found uri for %s - %s", artist, track)
                uris.append(uri)
            else:
                logger.warning("Track not found on Spotify: %s - %s (file: %s)", artist, track, entry["path"])
                # Log to the not-found file as requested
                if args.not_found_log:
                    log_not_found(args.not_found_log, pl_name, artist, track, entry.get("path"))

        logger.info("Found %d/%d tracks on Spotify for playlist '%s'", len(uris), len(tracks), pl_name)
        # Add URIs to playlist in chunks
        add_tracks_to_playlist(sp, playlist_id_map[pl_name], uris, dry_run=args.dry_run)

    # Save cache
    save_cache(args.cache_file, cache)

    logger.info("All done.")


if __name__ == "__main__":
    main()

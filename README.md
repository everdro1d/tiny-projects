# Spotify Folder Playlist Creator

This Python app walks a local music folder and creates Spotify playlists from parent folders, adding tracks by searching Spotify.

## Features
- Load Spotify client ID/secret from `./.env`
- OAuth user using redirect URI `http://localhost:8080/callback`
- Treat parent folders as playlists; filenames must be in the format: `%artist% - %track name%.%ext%`
- Search Spotify using `artist:%artist% track:%track name%`
- Create playlists for the authenticated user and add found tracks (100 URIs per request max)
- Handles 429 rate limits by honoring `Retry-After` and retrying after `x + 1` seconds

## Requirements
- spotipy
- python-dotenv

## Installation
1. Create a virtual environment and install requirements:
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
   OR
   Use the nix flake to run nix develop

2. Create a `.env` file in the project root with your Spotify app credentials:
   - SPOTIPY_CLIENT_ID
   - SPOTIPY_CLIENT_SECRET

## Usage
```bash
python app.py -i /path/to/music -e "Podcasts" -e "Audiobooks"
```

## Options
- -i / --input: Path to root music folder (required)
- -e / --exclude: Folder name to exclude. Can be specified multiple times.
- --public: Create playlists as public (default is private)
- --dry-run: Do everything except create playlists or add tracks (useful for testing)

## Notes:
- Filenames must be in the format: `Artist - TrackName.ext`. Files not matching this pattern are skipped.
- Playlist name is the basename of each folder containing audio files.
- If a track can't be found on Spotify, it is skipped with a warning.
- The app honors Spotify rate limits (429) by reading `Retry-After` header and waiting `x + 1` seconds.

## Example `.env`
```
SPOTIPY_CLIENT_ID=your_client_id_here
SPOTIPY_CLIENT_SECRET=your_client_secret_here
```

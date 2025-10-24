#!/usr/bin/env python3

import os
import random
import traceback
import datetime
from plexapi.server import PlexServer
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

PLEX_URL = os.getenv('PLEX_URL')
PLEX_TOKEN = os.getenv('PLEX_TOKEN')
PLAYLIST_NAMES = ['Newton']  # Replace with your playlists

def shuffle_playlist(plex, playlist_name):
    print(f'\n🔄 Attempting to shuffle: "{playlist_name}"')

    # Safer playlist lookup
    playlist = next((p for p in plex.playlists() if p.title.strip().lower() == playlist_name.strip().lower()), None)
    if not playlist:
        print(f'⚠️ Playlist not found: "{playlist_name}" — skipping.')
        return

    if playlist.smart:
        print(f'⚠️ Skipping smart playlist: "{playlist.title}" (cannot be modified)')
        return

    try:
        raw_items = playlist.items()
        # Filter: valid, music-type items with a ratingKey
        items = [item for item in raw_items if item is not None and hasattr(item, 'ratingKey') and item.TYPE == 'track']

        print(f'ℹ️ "{playlist.title}" contains {len(items)} valid music tracks.')

        if not items:
            print(f'⚠️ Playlist "{playlist.title}" has no valid tracks to shuffle. Skipping.')
            return

        random.shuffle(items)
        shuffled_name = f"{playlist.title} (Shuffled)"

        # Remove old shuffled version if it exists
        existing = next((p for p in plex.playlists() if p.title == shuffled_name), None)
        if existing:
            print(f'🗑 Removing old playlist: "{shuffled_name}"')
            existing.delete()

        # Create shuffled playlist
        new_playlist = plex.createPlaylist(shuffled_name, items)
        print(f'✅ Created shuffled playlist: "{shuffled_name}" with {len(items)} tracks.')

        # Add current date to description
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        new_playlist.edit(description=f"Shuffled on {current_date}")
        print(f'✅ Added description to playlist: "{shuffled_name}" - "Shuffled on {current_date}"')

    except Exception as e:
        print(f'❌ Unexpected error while processing "{playlist_name}": {e}')
        traceback.print_exc()

def list_playlists(plex):
    print("\n📜 Available playlists on server:")
    for p in plex.playlists():
        print(f' - "{p.title}" (Type: {p.playlistType}, Smart: {p.smart})')

def main():
    if not PLEX_URL or not PLEX_TOKEN:
        print("❌ Missing PLEX_URL or PLEX_TOKEN in .env file.")
        return

    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    except Exception as e:
        print(f'❌ Could not connect to Plex server: {e}')
        traceback.print_exc()
        return

    # Optional: print available playlists
    # list_playlists(plex)

    for name in PLAYLIST_NAMES:
        shuffle_playlist(plex, name)

if __name__ == '__main__':
    main()

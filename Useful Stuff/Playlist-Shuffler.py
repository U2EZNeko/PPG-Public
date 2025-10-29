#!/usr/bin/env python3

import os
import random
import traceback
import datetime
import re
from plexapi.server import PlexServer
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

PLEX_URL = os.getenv('PLEX_URL')
PLEX_TOKEN = os.getenv('PLEX_TOKEN')
PLAYLIST_NAMES = ['Newton']  # Replace with your playlists

def shuffle_playlist(plex, playlist_name):
    print(f'\n🔄 Attempting to shuffle: "{playlist_name}"')

    # Find the playlist
    playlist = next((p for p in plex.playlists() if p.title.strip().lower() == playlist_name.strip().lower()), None)
    if not playlist:
        print(f'⚠️ Playlist not found: "{playlist_name}" — skipping.')
        return

    if playlist.smart:
        print(f'⚠️ Skipping smart playlist: "{playlist.title}" (cannot be modified)')
        return

    try:
        # Get all items from the playlist
        items = playlist.items()
        print(f'ℹ️ "{playlist.title}" contains {len(items)} tracks.')

        if not items:
            print(f'⚠️ Playlist "{playlist.title}" has no tracks to shuffle. Skipping.')
            return

        # Shuffle the items
        random.shuffle(items)
        print(f'🔀 Shuffled {len(items)} tracks.')

        # Clear the existing playlist and add shuffled items
        print(f'🔄 Replacing playlist contents...')
        playlist.removeItems(items)  # Remove all items
        playlist.addItems(items)      # Add them back in shuffled order
        
        print(f'✅ Successfully shuffled playlist: "{playlist.title}"')

        # Update description with shuffle timestamp
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        current_description = playlist.summary or ""
        
        # Look for existing shuffle timestamp pattern
        shuffle_pattern = r'Shuffled on \d{4}-\d{2}-\d{2}'
        
        if re.search(shuffle_pattern, current_description):
            # Replace existing shuffle timestamp
            new_description = re.sub(shuffle_pattern, f"Shuffled on {current_date}", current_description)
            playlist.editSummary(new_description)
            print(f'✅ Updated shuffle timestamp: "Shuffled on {current_date}"')
        else:
            # Add new shuffle timestamp to existing description
            if current_description.strip():
                new_description = f"{current_description}\n\nShuffled on {current_date}"
            else:
                new_description = f"Shuffled on {current_date}"
            playlist.editSummary(new_description)
            print(f'✅ Added shuffle timestamp: "Shuffled on {current_date}"')

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

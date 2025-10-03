from plexapi.server import PlexServer
from plexapi.playlist import Playlist
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

PLEX_URL = os.getenv('PLEX_URL')  # Plex server URL from .env
PLEX_TOKEN = os.getenv('PLEX_TOKEN')  # Admin Plex token from .env
SUB_USER_TOKENS = os.getenv('SUB_USER_TOKENS').split(',')  # Sub-user tokens from .env, comma-separated

# Define the playlists to copy
PLAYLISTS_TO_COPY = [
    "Rock Ballads",
    "Rock Ballads 2",
    "Rock Classics",
    "Rock Balladen 80-90",
    "All Out 50s",
    "All Out 60s",
    "All Out 70s",
    "All Out 80s",
    "All Out 90s",
    "All Out 2000s",
    "Classic Voices in Jazz",
    "Oldies Mix",
    "Greatest Rock Ballads",
    "Zurück in die 00er",
    "Zurück in die 10er",
    "Zurück in die 60er",
    "Zurück in die 70er",
    "Zurück in die 80er",
    "Zurück in die 90er",
    "Polka Mix",
    "Chill Mix",
    "Best of Rock Balladen",
    "Rock Balladen Mix",
    "Rock Ballads 80s-90s"
]

# Connect to Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

# Fetch and output all playlists on the admin account
admin_playlists = {playlist.title: playlist for playlist in plex.playlists()}
print("Available playlists on admin account:")
for playlist_title in admin_playlists.keys():
    print(f"- {playlist_title}")

def copy_playlists_to_users(admin_plex, sub_tokens, playlists_to_copy):
    """Copy selected playlists from admin user to multiple sub-users."""
    for sub_token in sub_tokens:
        sub_plex = PlexServer(PLEX_URL, sub_token.strip())  # Connect as sub-user

        for playlist_title in playlists_to_copy:
            if playlist_title not in admin_playlists:
                print(f"Playlist '{playlist_title}' not found in admin account. Skipping.")
                continue

            playlist = admin_playlists[playlist_title]

            # Get media items and description from the admin playlist
            items = playlist.items()
            description = playlist.summary

            # Check if playlist already exists in sub-user's account
            existing_playlists = {pl.title: pl for pl in sub_plex.playlists()}
            if playlist.title in existing_playlists:
                print(f"Playlist '{playlist.title}' already exists for sub-user. Clearing and updating.")
                existing_playlist = existing_playlists[playlist.title]
                try:
                    existing_playlist.delete()
                    print(f"Cleared existing playlist '{playlist.title}'.")
                except Exception as e:
                    print(f"Failed to clear existing playlist '{playlist.title}': {e}")

            # Create a new playlist for the sub-user
            try:
                new_playlist = Playlist.create(
                    server=sub_plex,
                    title=playlist.title,
                    items=items,
                )
                # Update the description
                if description:
                    new_playlist.edit(summary=description)

                print(f"Successfully copied playlist '{playlist.title}' to sub-user.")
            except Exception as e:
                print(f"Failed to copy playlist '{playlist.title}' to sub-user: {e}")

# Execute the copying function
copy_playlists_to_users(plex, SUB_USER_TOKENS, PLAYLISTS_TO_COPY)

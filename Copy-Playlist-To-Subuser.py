from plexapi.server import PlexServer
from plexapi.playlist import Playlist
from dotenv import load_dotenv
import os
import requests
from io import BytesIO

# Load environment variables
load_dotenv()

PLEX_URL = os.getenv('PLEX_URL')  # Plex server URL from .env
PLEX_TOKEN = os.getenv('PLEX_TOKEN')  # Admin Plex token from .env
SUB_USER_TOKENS = os.getenv('SUB_USER_TOKENS').split(',')  # Sub-user tokens from .env, comma-separated

# Define the playlists to copy
PLAYLISTS_TO_COPY = [
    "Rock Ballads",
    "Rock Classics",
    "Rock Balladen 80-90",
    "All Out 50s",
    "All Out 60s",
    "All Out 70s",
    "All Out 80s",
    "All Out 90s",
    "All Out 2000s",
    "Classic Voices in Jazz",
    "Oldies Mix"
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

            # Get media items, description, and poster from the admin playlist
            items = playlist.items()
            description = playlist.summary
            poster = playlist.thumb

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

                # Handle poster upload with additional checks
                if poster:
                    try:
                        # Download poster image
                        response = requests.get(poster)
                        if response.status_code == 200:
                            # Upload the poster as an image file
                            poster_image = BytesIO(response.content)
                            new_playlist.uploadPoster(poster_image)
                            print(f"Successfully updated poster for '{playlist.title}'.")
                        else:
                            print(f"Failed to fetch poster for '{playlist.title}', status code: {response.status_code}.")
                    except Exception as e:
                        print(f"Error downloading/uploading poster for '{playlist.title}': {e}")
                else:
                    print(f"No poster found for playlist '{playlist.title}'.")

                print(f"Successfully copied playlist '{playlist.title}' to sub-user.")
            except Exception as e:
                print(f"Failed to copy playlist '{playlist.title}' to sub-user: {e}")

# Execute the copying function
copy_playlists_to_users(plex, SUB_USER_TOKENS, PLAYLISTS_TO_COPY)

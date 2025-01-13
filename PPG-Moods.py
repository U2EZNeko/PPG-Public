import os
import random
import json
from plexapi.server import PlexServer
from dotenv import load_dotenv

# Static configuration
PLAYLIST_SIZE = 50  # Number of tracks in each playlist
MIN_TRACK_PERCENT = 0.8  # Minimum percentage of tracks required to create a playlist (80%)
MOOD_GROUPS_FILE = "mood_groups.json"  # Path to the JSON file containing mood groups


# Load environment variables from .env file
load_dotenv()

# Fetch sensitive data from environment variables
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")

# Connect to the Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

# Load mood groups from JSON file
def load_mood_groups():
    """Load mood groups from a JSON file."""
    print("Loading mood groups from file...")
    if not os.path.exists(MOOD_GROUPS_FILE):
        print(f"Error: {MOOD_GROUPS_FILE} not found.")
        return {}
    try:
        with open(MOOD_GROUPS_FILE, "r") as file:
            mood_groups = json.load(file)
            print(f"Loaded mood groups: {mood_groups}")
            return mood_groups
    except Exception as e:
        print(f"Error loading mood groups: {e}")
        return {}


# Generate playlists based on mood groups
def generate_mood_playlists():
    """Generate playlists based on mood groups."""
    print("Connecting to Plex server...")
    try:
        music_library = plex.library.section("Music")  # Adjust if your music library name differs
        print("Successfully connected to Plex server and accessed 'Music' library.")
    except Exception as e:
        print(f"Error connecting to Plex server or accessing library: {e}")
        return

    # Load mood groups
    mood_groups = load_mood_groups()
    if not mood_groups:
        print("No mood groups available. Exiting.")
        return

    for group_name, moods in mood_groups.items():
        # Create playlist name in the format "<Mood Group> Mix"
        playlist_name = f"{group_name} Mix"
        print(f"\nStarting generation for Playlist '{playlist_name}'...")

        try:
            # Retry logic if not enough songs are found
            songs = []

            # Collect all tracks for the selected moods
            for mood in moods:
                print(f"Fetching tracks for mood: {mood}")
                tracks = music_library.search(libtype="track", mood=mood, limit=None)
                print(f"Found {len(tracks)} tracks for mood: {mood}")
                songs.extend(tracks)

            total_songs = len(songs)
            print(f"Total songs found for playlist '{playlist_name}': {total_songs}")

            # Check if the number of songs is >= 50% of PLAYLIST_SIZE
            if total_songs >= (MIN_TRACK_PERCENT * PLAYLIST_SIZE):
                print(f"Found sufficient songs ({total_songs}) for Playlist '{playlist_name}'. Creating playlist.")
            else:
                print(f"Not enough songs for Playlist '{playlist_name}', skipping.")
                continue  # Skip this playlist if we couldn't find enough songs

            # Select the required number of songs (up to PLAYLIST_SIZE)
            playlist_songs = random.sample(songs, min(len(songs), PLAYLIST_SIZE))
            print(f"Selected {len(playlist_songs)} random songs for Playlist '{playlist_name}'.")

            # Create or update the playlist
            existing_playlist = plex.playlist(playlist_name) if playlist_name in [pl.title for pl in plex.playlists()] else None

            if existing_playlist:
                print(f"Updating existing playlist: {playlist_name}")

                # Remove all items from the existing playlist before adding new ones
                existing_playlist.removeItems(existing_playlist.items())  # This empties the current playlist

                # Add the new songs
                existing_playlist.addItems(playlist_songs)

                # Update the description with the selected moods
                mood_description = ", ".join(moods)
                existing_playlist.editSummary(f"Moods used: {mood_description}")
            else:
                print(f"Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)

                # Set the description with the selected moods
                mood_description = ", ".join(moods)
                playlist.editSummary(f"Moods used: {mood_description}")

            print(f"Playlist '{playlist_name}' successfully created/updated with {len(playlist_songs)} songs.")

        except Exception as e:
            print(f"Error during playlist generation for Playlist '{playlist_name}': {e}")

# Run the script
if __name__ == "__main__":
    print("Starting the mood playlist generation process...")
    generate_mood_playlists()
    print("\nMood playlists updated successfully.")

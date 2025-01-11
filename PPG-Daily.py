from plexapi.server import PlexServer
import random
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fetch sensitive data from environment variables
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
PLAYLIST_COUNT = 7
SONGS_PER_PLAYLIST = 50
MOOD_GROUPS_FILE = "mood_groups.json"  # Path to the mood groups file
MIN_SONGS_REQUIRED = 0.8 * SONGS_PER_PLAYLIST  # 80% of the required songs

# Connect to the Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)


# Load mood groups from JSON file
def load_mood_groups():
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


# Generate playlists
def generate_daily_playlists():
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

    for i in range(PLAYLIST_COUNT):
        print(f"\nStarting generation for Playlist {i + 1}...")
        try:
            # Retry logic if not enough songs are found
            songs = []
            selected_group = None
            selected_moods = None

            # Keep retrying until we find a genre group with enough songs
            for attempt in range(10):  # Retry up to 10 times for each playlist
                selected_group = random.choice(list(mood_groups.keys()))
                selected_moods = mood_groups[selected_group]
                print(f"Attempt {attempt + 1}: Selected mood group: {selected_group}")
                print(f"Moods in group: {selected_moods}")

                # Collect all tracks for the selected moods
                songs = []
                for mood in selected_moods:
                    print(f"Fetching tracks for mood: {mood}")
                    tracks = music_library.search(mood=mood, libtype="track", limit=None)
                    print(f"Found {len(tracks)} tracks for mood: {mood}")
                    songs.extend(tracks)

                total_songs = len(songs)
                print(f"Total songs found for group '{selected_group}': {total_songs}")

                # Check if the number of songs is >= 80% of SONGS_PER_PLAYLIST
                if total_songs >= MIN_SONGS_REQUIRED:
                    print(f"Found sufficient songs ({total_songs}) for Playlist {i + 1}. Creating playlist.")
                    break  # We found enough songs, break out of the retry loop
                else:
                    print(f"Not enough songs for Playlist {i + 1}. Retrying with a different mood group...")

            if total_songs < MIN_SONGS_REQUIRED:
                print(f"Error: Could not find enough songs after 10 attempts. Skipping playlist {i + 1}.")
                continue  # Skip this playlist if we couldn't find enough songs

            # Select the required number of songs (up to SONGS_PER_PLAYLIST)
            playlist_songs = random.sample(songs, min(len(songs), SONGS_PER_PLAYLIST))
            print(f"Selected {len(playlist_songs)} random songs for Playlist {i + 1}.")

            # Create or update the playlist
            playlist_name = f"{selected_group} Mix"
            existing_playlist = plex.playlist(playlist_name) if playlist_name in [pl.title for pl in plex.playlists()] else None

            if existing_playlist:
                print(f"Updating existing playlist: {playlist_name}")

                # Remove all items from the existing playlist before adding new ones
                existing_playlist.removeItems(existing_playlist.items())  # This empties the current playlist

                # Add the new songs
                existing_playlist.addItems(playlist_songs)

                # Update the description with the selected genres
                mood_description = ", ".join(selected_moods)
                existing_playlist.editSummary(f"Moods used: {mood_description}")  # Using editSummary instead of edit
            else:
                print(f"Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)

                # Set the description with the selected genres
                mood_description = ", ".join(selected_moods)
                playlist.editSummary(f"Moods used: {mood_description}")  # Using editSummary instead of edit

            print(f"Playlist '{playlist_name}' successfully created/updated with {len(playlist_songs)} songs.")

        except Exception as e:
            print(f"Error during playlist generation for Playlist {i + 1}: {e}")


# Run the script
if __name__ == "__main__":
    print("Starting the Daily playlist generation process...")
    generate_daily_playlists()
    print("\nDaily playlists updated successfully.")


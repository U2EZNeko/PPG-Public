from plexapi.server import PlexServer
import random
import json
import os
from dotenv import load_dotenv
from datetime import date

# Load environment variables from .env file
load_dotenv()

# Fetch sensitive data from environment variables
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
SHOW_UPDATED = os.getenv("SHOW_LAST_UPDATED")

PLAYLIST_COUNT = 7
SONGS_PER_PLAYLIST = 50
GENRE_GROUPS_FILE = "genre_groups.json"  # Path to the genre groups file
DAILY_LOG_FILE = "dailylog.txt"  # File to store used genre groups
MAX_LOG_ENTRIES = 50  # Maximum number of entries in the log
MIN_SONGS_REQUIRED = 0.8 * SONGS_PER_PLAYLIST  # 80% of the required songs

# Get the current date
today = date.today()
curr_date = today.strftime('%a %d %b %Y')

# Connect to the Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)


# Load genre groups from JSON file
def load_genre_groups():
    print("Loading genre groups from file...")
    if not os.path.exists(GENRE_GROUPS_FILE):
        print(f"Error: {GENRE_GROUPS_FILE} not found.")
        return {}
    try:
        with open(GENRE_GROUPS_FILE, "r") as file:
            genre_groups = json.load(file)
            print(f"Loaded genre groups: {genre_groups}")
            return genre_groups
    except Exception as e:
        print(f"Error loading genre groups: {e}")
        return {}


# Read the daily log file
def read_daily_log():
    print("Reading daily log...")
    if not os.path.exists(DAILY_LOG_FILE):
        print(f"{DAILY_LOG_FILE} does not exist. Starting with an empty log.")
        return []
    try:
        with open(DAILY_LOG_FILE, "r") as file:
            log = [line.strip() for line in file.readlines()]
            print(f"Daily log loaded: {log}")
            return log
    except Exception as e:
        print(f"Error reading daily log: {e}")
        return []


# Write to the daily log file
def write_daily_log(log):
    print("Writing to daily log...")
    try:
        with open(DAILY_LOG_FILE, "w") as file:
            file.writelines(f"{entry}\n" for entry in log)
        print("Daily log updated successfully.")
    except Exception as e:
        print(f"Error writing to daily log: {e}")


# Generate daily playlists
def generate_daily_playlists():
    print("Connecting to Plex server...")
    try:
        music_library = plex.library.section("Music")  # Adjust if your music library name differs
        print("Successfully connected to Plex server and accessed 'Music' library.")
    except Exception as e:
        print(f"Error connecting to Plex server or accessing library: {e}")
        return

    # Load genre groups
    genre_groups = load_genre_groups()
    if not genre_groups:
        print("No genre groups available. Exiting.")
        return

    # Read the daily log to avoid previously used genre groups
    daily_log = read_daily_log()

    # Filter out previously used genre groups
    available_genre_groups = {
        group: genres
        for group, genres in genre_groups.items()
        if group not in daily_log
    }

    if not available_genre_groups:
        print("All genre groups have been used recently. Resetting the log.")
        daily_log = []
        available_genre_groups = genre_groups.copy()

    for i in range(PLAYLIST_COUNT):
        print(f"\nStarting generation for Playlist {i + 1}...")
        try:
            # Retry logic if not enough songs are found
            songs = []
            selected_group = None
            selected_genres = None

            # Keep retrying until we find a genre group with enough songs
            for attempt in range(10):  # Retry up to 10 times for each playlist
                selected_group = random.choice(list(available_genre_groups.keys()))
                selected_genres = available_genre_groups[selected_group]
                print(f"Attempt {attempt + 1}: Selected genre group: {selected_group}")
                print(f"Genres in group: {selected_genres}")

                # Collect all tracks for the selected genres
                songs = []
                for genre in selected_genres:
                    print(f"Fetching tracks for genre: {genre}")
                    tracks = music_library.search(genre=genre, libtype="track", limit=None)
                    print(f"Found {len(tracks)} tracks for genre: {genre}")
                    songs.extend(tracks)

                total_songs = len(songs)
                print(f"Total songs found for group '{selected_group}': {total_songs}")

                # Check if the number of songs is >= 80% of SONGS_PER_PLAYLIST
                if total_songs >= MIN_SONGS_REQUIRED:
                    print(f"Found sufficient songs ({total_songs}) for Playlist {i + 1}. Creating playlist.")
                    break  # We found enough songs, break out of the retry loop
                else:
                    print(f"Not enough songs for Playlist {i + 1}. Retrying with a different genre group...")

            if total_songs < MIN_SONGS_REQUIRED:
                print(f"Error: Could not find enough songs after 10 attempts. Skipping playlist {i + 1}.")
                continue  # Skip this playlist if we couldn't find enough songs

            # Select the required number of songs (up to SONGS_PER_PLAYLIST)
            playlist_songs = random.sample(songs, min(len(songs), SONGS_PER_PLAYLIST))
            print(f"Selected {len(playlist_songs)} random songs for Playlist {i + 1}.")

            # Create or update the playlist
            playlist_name = f"Daily Playlist {i + 1}"
            existing_playlist = plex.playlist(playlist_name) if playlist_name in [pl.title for pl in
                                                                                  plex.playlists()] else None

            if existing_playlist:
                print(f"Updating existing playlist: {playlist_name}")

                # Remove all items from the existing playlist before adding new ones
                existing_playlist.removeItems(existing_playlist.items())  # This empties the current playlist

                # Add the new songs
                existing_playlist.addItems(playlist_songs)

                # Update the description with the selected genres
                genre_description = ", ".join(selected_genres)

                if (SHOW_UPDATED):
                    genre_description += "\nLast updated: " + curr_date

                existing_playlist.editSummary(f"Genres used: {genre_description}")  # Using editSummary instead of edit
            else:
                print(f"Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)

                # Set the description with the selected genres
                genre_description = ", ".join(selected_genres)

                if (SHOW_UPDATED):
                    genre_description += "\nLast updated: " + curr_date

                playlist.editSummary(f"Genres used: {genre_description}")  # Using editSummary instead of edit

            print(f"Playlist '{playlist_name}' successfully created/updated with {len(playlist_songs)} songs.")

            # Add the selected genre group to the log
            daily_log.append(selected_group)

            # Keep the log size to a maximum of MAX_LOG_ENTRIES
            if len(daily_log) > MAX_LOG_ENTRIES:
                daily_log = daily_log[-MAX_LOG_ENTRIES:]

        except Exception as e:
            print(f"Error during playlist generation for Playlist {i + 1}: {e}")

    # Write the updated log back to the file
    write_daily_log(daily_log)


# Run the script
if __name__ == "__main__":
    print("Starting the Daily playlist generation process...")
    generate_daily_playlists()
    print("\nDaily playlists updated successfully.")

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
SHOW_UPDATED = os.getenv("SHOW_LAST_UPDATED")

SONGS_PER_PLAYLIST = 50
GENRE_MIXES_FILE = "genre_mixes.json"  # Path to the genre mixes file
MIN_SONGS_REQUIRED = 0.5 * SONGS_PER_PLAYLIST  # 50% of the required songs

# Get the current date
from datetime import date
today = date.today()
curr_date = today

# Connect to the Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

# Load genre mixes from JSON file (updated to handle new structure)
def load_genre_mixes():
    print("Loading genre mixes from file...")
    if not os.path.exists(GENRE_MIXES_FILE):
        print(f"Error: {GENRE_MIXES_FILE} not found.")
        return {}
    try:
        with open(GENRE_MIXES_FILE, "r") as file:
            genre_mixes = json.load(file)
            print(f"Loaded genre mixes: {genre_mixes}")
            return genre_mixes
    except Exception as e:
        print(f"Error loading genre mixes: {e}")
        return {}

# Get the release year, with fallback to parent album
def get_release_year(track):
    # Check if the track itself has a year
    if track.year:
        return track.year
    # Fallback to the parent album's year
    if hasattr(track, "parentRatingKey"):
        album = plex.fetchItem(track.parentRatingKey)
        if album and album.year:
            return album.year
    return None  # No year available

# Generate playlists based on genre mixes
def generate_genre_playlists():
    print("Connecting to Plex server...")
    try:
        music_library = plex.library.section("Music")  # Adjust if your music library name differs
        print("Successfully connected to Plex server and accessed 'Music' library.")
    except Exception as e:
        print(f"Error connecting to Plex server or accessing library: {e}")
        return

    # Load genre mixes
    genre_mixes = load_genre_mixes()
    if not genre_mixes:
        print("No genre mixes available. Exiting.")
        return

    for i, (genre_group, group_data) in enumerate(genre_mixes.items()):
        genres = group_data["genres"]
        release_date_filter = group_data.get("release_date_filter")
        playlist_name = f"{genre_group} Mix"
        print(f"\nStarting generation for Playlist '{playlist_name}'...")

        try:
            # Collect all tracks for the selected genres
            songs = []
            for genre in genres:
                print(f"Fetching tracks for genre: {genre}")
                tracks = music_library.search(genre=genre, libtype="track", limit=None)
                print(f"Found {len(tracks)} tracks for genre: {genre}")
                songs.extend(tracks)

            # Apply release date filter if specified
            if release_date_filter:
                condition = release_date_filter.get("condition")
                print(f"Applying release date filter with condition: {condition}")

                if condition == "after":
                    threshold_year = int(release_date_filter["date"])
                    print(f"Filtering songs released after {threshold_year}")
                    songs = [
                        track for track in songs
                        if (year := get_release_year(track)) and year >= threshold_year
                    ]

                elif condition == "before":
                    threshold_year = int(release_date_filter["date"])
                    print(f"Filtering songs released before {threshold_year}")
                    songs = [
                        track for track in songs
                        if (year := get_release_year(track)) and year < threshold_year
                    ]

                elif condition == "between":
                    start_year = int(release_date_filter["start_date"])
                    end_year = int(release_date_filter["end_date"])
                    print(f"Filtering songs released between {start_year} and {end_year}")
                    songs = [
                        track for track in songs
                        if (year := get_release_year(track)) and start_year <= year <= end_year
                    ]

            total_songs = len(songs)
            print(f"Total songs after filtering: {total_songs}")

            # Check if the number of songs is >= MIN_SONGS_REQUIRED
            if total_songs >= MIN_SONGS_REQUIRED:
                print(f"Found sufficient songs ({total_songs}) for Playlist '{playlist_name}'. Creating playlist.")
            else:
                print(f"Not enough songs for Playlist '{playlist_name}', skipping.")
                continue

            # Select the required number of songs (up to SONGS_PER_PLAYLIST)
            playlist_songs = random.sample(songs, min(len(songs), SONGS_PER_PLAYLIST))
            print(f"Selected {len(playlist_songs)} random songs for Playlist '{playlist_name}'.")

            # Create or update the playlist
            existing_playlist = plex.playlist(playlist_name) if playlist_name in [pl.title for pl in plex.playlists()] else None

            if existing_playlist:
                print(f"Updating existing playlist: {playlist_name}")
                existing_playlist.removeItems(existing_playlist.items())
                existing_playlist.addItems(playlist_songs)
                genre_description = ", ".join(genres)

                if (SHOW_UPDATED):
                    genre_description += "\nLast updated: ".curr_date

                existing_playlist.editSummary(f"Genres used: {genre_description}")
            else:
                print(f"Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)
                genre_description = ", ".join(genres)

                if (SHOW_UPDATED):
                    genre_description += "\nLast updated: ".curr_date

                playlist.editSummary(f"Genres used: {genre_description}")

            print(f"Playlist '{playlist_name}' successfully created/updated with {len(playlist_songs)} songs.")

        except Exception as e:
            print(f"Error during playlist generation for Playlist '{playlist_name}': {e}")

# Run the script
if __name__ == "__main__":
    print("Starting the Daily playlist generation process...")
    generate_genre_playlists()
    print("\nDaily playlists updated successfully.")

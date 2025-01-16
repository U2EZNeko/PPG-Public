from plexapi.server import PlexServer
import random
import json
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fetch sensitive data from environment variables
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
SONGS_PER_PLAYLIST = 50
GENRE_MIXES_FILE = "genre_mixes.json"  # Path to the genre mixes file
MIN_SONGS_REQUIRED = 0.5 * SONGS_PER_PLAYLIST  # 50% of the required songs

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
                if condition == "after":
                    threshold_date = datetime.strptime(release_date_filter["date"], "%Y-%m-%d")
                    print(f"Filtering songs released after {threshold_date}")
                    songs = [
                        track for track in songs
                        if track.originallyAvailableAt and track.originallyAvailableAt >= threshold_date
                    ]
                elif condition == "before":
                    threshold_date = datetime.strptime(release_date_filter["date"], "%Y-%m-%d")
                    print(f"Filtering songs released before {threshold_date}")
                    songs = [
                        track for track in songs
                        if track.originallyAvailableAt and track.originallyAvailableAt < threshold_date
                    ]
                elif condition == "between":
                    start_date = datetime.strptime(release_date_filter["start_date"], "%Y-%m-%d")
                    end_date = datetime.strptime(release_date_filter["end_date"], "%Y-%m-%d")
                    print(f"Filtering songs released between {start_date} and {end_date}")
                    songs = [
                        track for track in songs
                        if track.originallyAvailableAt and start_date <= track.originallyAvailableAt <= end_date
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
                existing_playlist.editSummary(f"Genres used: {genre_description}")
            else:
                print(f"Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)
                genre_description = ", ".join(genres)
                playlist.editSummary(f"Genres used: {genre_description}")

            print(f"Playlist '{playlist_name}' successfully created/updated with {len(playlist_songs)} songs.")

        except Exception as e:
            print(f"Error during playlist generation for Playlist '{playlist_name}': {e}")

# Run the script
if __name__ == "__main__":
    print("Starting the Daily playlist generation process...")
    generate_genre_playlists()
    print("\nDaily playlists updated successfully.")

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
PLAYLIST_COUNT = 5
SONGS_PER_PLAYLIST = 200
GENRE_GROUPS_FILE = "genre_groups.json"  # Path to the genre groups file
MIN_SONGS_REQUIRED = 0.8 * SONGS_PER_PLAYLIST  # 80% of the required songs

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


# Generate playlists
def generate_weekly_playlists():
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

    # Fetch all genres from the server
    print("Fetching genres from the music library...")
    try:
        genres = music_library.search(libtype="artist", limit=None)
        # Extract genre names as strings
        existing_genres = set(
            genre.tag for artist in genres for genre in (artist.genres or [])
        )
        print(f"Found {len(existing_genres)} unique genres on the server: {existing_genres}")
    except Exception as e:
        print(f"Error fetching genres: {e}")
        return

    # Filter genre groups to only include genres available on the server
    print("Filtering genre groups to match available genres on the server...")
    filtered_genre_groups = {
        group: [genre for genre in genres if genre in existing_genres]
        for group, genres in genre_groups.items()
    }
    # Remove empty groups
    filtered_genre_groups = {group: genres for group, genres in filtered_genre_groups.items() if genres}
    print(f"Filtered genre groups: {filtered_genre_groups}")

    for i in range(PLAYLIST_COUNT):
        print(f"\nStarting generation for Playlist {i + 1}...")
        try:
            # Retry logic if not enough songs are found
            songs = []
            selected_group = None
            selected_genres = None

            # Keep retrying until we find a genre group with enough songs
            for attempt in range(10):  # Retry up to 10 times for each playlist
                selected_group = random.choice(list(filtered_genre_groups.keys()))
                selected_genres = filtered_genre_groups[selected_group]
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
            playlist_name = f"Weekly Playlist {i + 1}"
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
                existing_playlist.editSummary(f"Genres used: {genre_description}")  # Using editSummary instead of edit
            else:
                print(f"Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)

                # Set the description with the selected genres
                genre_description = ", ".join(selected_genres)
                playlist.editSummary(f"Genres used: {genre_description}")  # Using editSummary instead of edit

            print(f"Playlist '{playlist_name}' successfully created/updated with {len(playlist_songs)} songs.")

        except Exception as e:
            print(f"Error during playlist generation for Playlist {i + 1}: {e}")


# Run the script
if __name__ == "__main__":
    print("Starting the Weekly playlist generation process...")
    generate_weekly_playlists()
    print("\nWeekly playlists updated successfully.")
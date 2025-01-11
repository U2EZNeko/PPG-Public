import os
import random
import json
from plexapi.server import PlexServer
from dotenv import load_dotenv

# Static configuration
PLAYLIST_SIZE = 50  # Number of tracks in each playlist
MIN_TRACK_PERCENT = 0.8  # Minimum percentage of tracks required to create a playlist
MOOD_GROUPS_FILE = "mood_groups.json"  # Path to the JSON file containing mood groups


def load_env():
    """Load environment variables from .env file."""
    print("Loading environment variables from .env file...")
    load_dotenv()
    return {
        "PLEX_URL": os.getenv("PLEX_URL"),
        "PLEX_TOKEN": os.getenv("PLEX_TOKEN")
    }


def load_mood_groups():
    """Load mood groups from a JSON file."""
    print("Loading mood groups from JSON file...")
    try:
        with open(MOOD_GROUPS_FILE, 'r') as f:
            mood_groups = json.load(f)
        print(f"Loaded mood groups: {mood_groups}")
        return mood_groups
    except Exception as e:
        print(f"Error loading mood groups: {e}")
        return {}


def get_tracks_by_moods(plex, moods):
    """Fetch tracks from Plex with any of the specified moods."""
    print(f"Fetching tracks for moods: {', '.join(moods)}")
    try:
        tracks = set()  # Using set to avoid duplicates
        for mood in moods:
            mood_tracks = plex.library.search(libtype="track", mood=mood)
            tracks.update(mood_tracks)
        print(f"Found {len(tracks)} tracks for moods '{', '.join(moods)}'.")
        return list(tracks)
    except Exception as e:
        print(f"Error fetching tracks for moods {moods}: {e}")
        return []


def create_or_update_playlist(plex, group_name, tracks):
    """Create or update a Plex playlist for the given group."""
    print(f"Checking for existing playlist: {group_name}")

    try:
        # Check if the playlist exists
        existing_playlist = next((p for p in plex.playlists() if p.title == group_name), None)

        if existing_playlist:
            print(f"Playlist '{group_name}' exists. Updating it.")
            # Clear the existing playlist and add the new tracks
            existing_playlist.removeItems(existing_playlist.items())
            existing_playlist.addItems(tracks)
            print(f"Playlist '{group_name}' updated with {len(tracks)} tracks.")
        else:
            # Create a new playlist if it doesn't exist and add tracks
            print(f"Creating new playlist '{group_name}' with {len(tracks)} tracks.")
            # Ensure we're passing valid track objects to createPlaylist
            track_objects = [track for track in tracks]  # Ensure these are valid Track objects
            new_playlist = plex.createPlaylist(group_name, track_objects)
            print(f"Playlist '{group_name}' created successfully with {len(tracks)} tracks.")

    except Exception as e:
        print(f"Error creating or updating playlist '{group_name}': {e}")


def generate_playlist(plex, mood_groups, playlist_size, min_track_percent):
    """Generate playlists for each mood group."""
    print(f"Starting playlist generation for mood groups: {', '.join(mood_groups.keys())}")

    for group_name, moods in mood_groups.items():
        print(f"Processing mood group: {group_name}")
        tracks = get_tracks_by_moods(plex, moods)

        if not tracks:
            print(f"No tracks found for mood group '{group_name}'. Skipping.")
            continue

        # Shuffle tracks randomly
        print(f"Shuffling tracks for mood group '{group_name}'.")
        random.shuffle(tracks)

        # Select the top 'playlist_size' number of tracks (e.g., 50)
        selected_tracks = tracks[:playlist_size]
        print(f"Selected {len(selected_tracks)} tracks for playlist '{group_name}'.")

        create_or_update_playlist(plex, group_name, selected_tracks)


def main():
    print("Starting Plex Mood Playlist Generator...")

    # Load environment variables
    config = load_env()
    PLEX_URL = config["PLEX_URL"]
    PLEX_TOKEN = config["PLEX_TOKEN"]

    if not PLEX_URL or not PLEX_TOKEN:
        print("Error: PLEX_URL and PLEX_TOKEN must be set in the .env file.")
        return

    print("Connecting to Plex server...")
    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        print("Connected to Plex server successfully.")
    except Exception as e:
        print(f"Error connecting to Plex server: {e}")
        return

    # Load mood groups from the JSON file
    mood_groups = load_mood_groups()

    if not mood_groups:
        print("Error: No mood groups found. Exiting.")
        return

    # Generate playlists for each mood group
    print(f"Generating playlists for mood groups: {', '.join(mood_groups.keys())}")
    generate_playlist(plex, mood_groups, PLAYLIST_SIZE, MIN_TRACK_PERCENT)
    print("Playlist generation complete.")


if __name__ == "__main__":
    main()

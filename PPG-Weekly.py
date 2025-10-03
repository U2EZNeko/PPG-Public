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
WEEKLY_LOG_FILE = "weeklylog.txt"  # File to store used genre groups
MAX_LOG_ENTRIES = 50  # Maximum number of entries in the log
MIN_SONGS_REQUIRED = 0.8 * SONGS_PER_PLAYLIST  # 80% of the required songs
MAX_ARTIST_PERCENTAGE = 0.3  # Maximum percentage of songs per artist (30%)

# Liked artists and variety configuration
MAX_LIKED_ARTISTS_PERCENTAGE = 0.9  # Maximum percentage of songs from liked artists (90%)
MIN_VARIETY_PERCENTAGE = 0.1  # Minimum percentage of songs from other artists for variety (10%)

# Connect to the Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

# Get artist name from a track
def get_artist_name(track):
    """Get the artist name from a track, handling different Plex track structures."""
    if hasattr(track, 'artist') and track.artist:
        return track.artist().title if callable(track.artist) else track.artist
    elif hasattr(track, 'grandparentTitle') and track.grandparentTitle:
        return track.grandparentTitle
    return None

# Get liked artists from Plex
def get_liked_artists():
    """Get a set of artist names that have been liked in Plex."""
    try:
        print("Fetching liked artists from Plex...")
        liked_artists = set()
        
        # Get all music items that have been liked
        music_library = plex.library.section("Music")
        liked_items = music_library.search(filters={'userRating': 5}, libtype="track", limit=None)
        
        for track in liked_items:
            artist_name = get_artist_name(track)
            if artist_name:
                liked_artists.add(artist_name)
        
        print(f"Found {len(liked_artists)} liked artists")
        return liked_artists
        
    except Exception as e:
        print(f"Error fetching liked artists: {e}")
        return set()

# Analyze artist distribution in a playlist
def analyze_artist_distribution(playlist_songs):
    """Analyze the distribution of artists in the playlist and return artist counts."""
    artist_counts = {}
    for track in playlist_songs:
        artist_name = get_artist_name(track)
        if artist_name:
            artist_counts[artist_name] = artist_counts.get(artist_name, 0) + 1
    
    return artist_counts

# Balance artist representation in playlist to max percentage per artist
def balance_artist_representation(playlist_songs, all_available_songs, max_percentage=0.3):
    """Ensure no single artist represents more than max_percentage of the playlist."""
    total_songs = len(playlist_songs)
    max_songs_per_artist = int(total_songs * max_percentage)
    
    print(f"Balancing artist representation (max {max_percentage*100:.0f}% per artist = {max_songs_per_artist} songs)")
    
    # Analyze current distribution
    artist_counts = analyze_artist_distribution(playlist_songs)
    print(f"Current artist distribution: {artist_counts}")
    
    # Find artists that exceed the limit
    artists_to_reduce = {}
    for artist, count in artist_counts.items():
        if count > max_songs_per_artist:
            excess = count - max_songs_per_artist
            artists_to_reduce[artist] = excess
            print(f"Artist '{artist}' has {count} songs, needs to reduce by {excess}")
    
    if not artists_to_reduce:
        print(f"No artists exceed the {max_percentage*100:.0f}% limit. Playlist is balanced.")
        return playlist_songs
    
    # Create a copy of the playlist to modify
    balanced_playlist = playlist_songs.copy()
    
    # For each artist that exceeds the limit, keep only max_songs_per_artist random songs
    for artist, excess_count in artists_to_reduce.items():
        # Find all songs by this artist
        artist_songs = [song for song in balanced_playlist if get_artist_name(song) == artist]
        
        # Keep only max_songs_per_artist random songs from this artist
        songs_to_keep = random.sample(artist_songs, max_songs_per_artist)
        songs_to_remove = [song for song in artist_songs if song not in songs_to_keep]
        
        # Remove excess songs from the playlist
        for song in songs_to_remove:
            balanced_playlist.remove(song)
        
        print(f"Kept {len(songs_to_keep)} songs from '{artist}', removed {len(songs_to_remove)}")
    
    # Fill the playlist back up to the target size with songs from other artists
    songs_needed = total_songs - len(balanced_playlist)
    if songs_needed > 0:
        print(f"Need to add {songs_needed} more songs to reach target size")
        
        # Get songs from artists that are not over-represented
        excluded_artists = set(artists_to_reduce.keys())
        available_songs = [song for song in all_available_songs if song not in balanced_playlist]
        
        # Filter out songs from over-represented artists
        filtered_available = []
        for song in available_songs:
            artist_name = get_artist_name(song)
            if artist_name not in excluded_artists:
                filtered_available.append(song)
        
        if len(filtered_available) >= songs_needed:
            additional_songs = random.sample(filtered_available, songs_needed)
            balanced_playlist.extend(additional_songs)
            print(f"Added {len(additional_songs)} additional songs from other artists")
        else:
            print(f"Warning: Only {len(filtered_available)} songs available from other artists, added all of them")
            balanced_playlist.extend(filtered_available)
    
    # Final verification
    final_artist_counts = analyze_artist_distribution(balanced_playlist)
    print(f"Final artist distribution: {final_artist_counts}")
    
    return balanced_playlist

# Prefer songs from liked artists with guaranteed variety
def prefer_liked_artists(songs, liked_artists, target_count, max_liked_percentage=0.9, min_variety_percentage=0.1):
    """Select songs with preference for liked artists, but ensure minimum variety from other artists."""
    if not liked_artists:
        print("No liked artists found, selecting randomly.")
        return random.sample(songs, min(len(songs), target_count))
    
    # Calculate target counts based on percentages
    max_liked_count = int(target_count * max_liked_percentage)
    min_variety_count = int(target_count * min_variety_percentage)
    
    print(f"Target distribution: max {max_liked_percentage*100:.0f}% liked artists ({max_liked_count}), min {min_variety_percentage*100:.0f}% variety ({min_variety_count})")
    
    # Separate songs into liked and non-liked artists
    liked_songs = []
    other_songs = []
    
    for song in songs:
        artist_name = get_artist_name(song)
        if artist_name and artist_name in liked_artists:
            liked_songs.append(song)
        else:
            other_songs.append(song)
    
    print(f"Found {len(liked_songs)} songs from liked artists, {len(other_songs)} from other artists")
    
    selected_songs = []
    
    # Ensure minimum variety first
    if other_songs and min_variety_count > 0:
        variety_count = min(len(other_songs), min_variety_count)
        selected_songs.extend(random.sample(other_songs, variety_count))
        print(f"Selected {variety_count} songs from other artists for guaranteed variety")
    
    # Fill remaining slots with liked artists (up to max percentage)
    remaining_slots = target_count - len(selected_songs)
    if liked_songs and remaining_slots > 0:
        liked_count = min(len(liked_songs), remaining_slots, max_liked_count)
        selected_songs.extend(random.sample(liked_songs, liked_count))
        print(f"Selected {liked_count} songs from liked artists")
    
    # Fill any remaining slots with more other songs if needed
    remaining_slots = target_count - len(selected_songs)
    if other_songs and remaining_slots > 0:
        other_count = min(len(other_songs), remaining_slots)
        # Remove already selected songs from available pool
        available_other_songs = [song for song in other_songs if song not in selected_songs]
        if available_other_songs:
            other_count = min(len(available_other_songs), other_count)
            selected_songs.extend(random.sample(available_other_songs, other_count))
            print(f"Selected {other_count} additional songs from other artists to fill playlist")
    
    # Show final distribution
    final_liked_count = sum(1 for song in selected_songs if get_artist_name(song) in liked_artists)
    final_other_count = len(selected_songs) - final_liked_count
    final_liked_percentage = (final_liked_count / len(selected_songs)) * 100 if selected_songs else 0
    final_other_percentage = (final_other_count / len(selected_songs)) * 100 if selected_songs else 0
    
    print(f"Final selection: {final_liked_count} from liked artists ({final_liked_percentage:.1f}%), {final_other_count} from other artists ({final_other_percentage:.1f}%)")
    
    return selected_songs

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


# Read the weekly log file
def read_weekly_log():
    print("Reading weekly log...")
    if not os.path.exists(WEEKLY_LOG_FILE):
        print(f"{WEEKLY_LOG_FILE} does not exist. Starting with an empty log.")
        return []
    try:
        with open(WEEKLY_LOG_FILE, "r") as file:
            log = [line.strip() for line in file.readlines()]
            print(f"Weekly log loaded: {log}")
            return log
    except Exception as e:
        print(f"Error reading weekly log: {e}")
        return []


# Write to the weekly log file
def write_weekly_log(log):
    print("Writing to weekly log...")
    try:
        with open(WEEKLY_LOG_FILE, "w") as file:
            file.writelines(f"{entry}\n" for entry in log)
        print("Weekly log updated successfully.")
    except Exception as e:
        print(f"Error writing to weekly log: {e}")


# Generate weekly playlists
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

    # Get liked artists once at the beginning
    liked_artists = get_liked_artists()

    # Read the weekly log to avoid previously used genre groups
    weekly_log = read_weekly_log()

    # Filter out previously used genre groups
    available_genre_groups = {
        group: genres
        for group, genres in genre_groups.items()
        if group not in weekly_log
    }

    if not available_genre_groups:
        print("All genre groups have been used recently. Resetting the log.")
        weekly_log = []
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
            if liked_artists:
                playlist_songs = prefer_liked_artists(songs, liked_artists, min(len(songs), SONGS_PER_PLAYLIST), 
                                                    MAX_LIKED_ARTISTS_PERCENTAGE, MIN_VARIETY_PERCENTAGE)
                print(f"Selected {len(playlist_songs)} songs (preferring liked artists) for Playlist {i + 1}.")
            else:
                playlist_songs = random.sample(songs, min(len(songs), SONGS_PER_PLAYLIST))
                print(f"Selected {len(playlist_songs)} random songs for Playlist {i + 1}.")

            # Balance artist representation to ensure no single artist exceeds the configured limit
            print(f"Checking artist distribution for Playlist {i + 1}...")
            playlist_songs = balance_artist_representation(playlist_songs, songs, MAX_ARTIST_PERCENTAGE)

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

            # Add the selected genre group to the log
            weekly_log.append(selected_group)

            # Keep the log size to a maximum of MAX_LOG_ENTRIES
            if len(weekly_log) > MAX_LOG_ENTRIES:
                weekly_log = weekly_log[-MAX_LOG_ENTRIES:]

        except Exception as e:
            print(f"Error during playlist generation for Playlist {i + 1}: {e}")

    # Write the updated log back to the file
    write_weekly_log(weekly_log)


# Run the script
if __name__ == "__main__":
    print("Starting the Weekly playlist generation process...")
    generate_weekly_playlists()
    print("\nWeekly playlists updated successfully.")

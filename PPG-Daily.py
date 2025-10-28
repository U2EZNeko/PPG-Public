
from plexapi.server import PlexServer
import random
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fetch all configuration from environment variables
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")

# Paths for playlist posters
PLAYLIST_POSTERS_DIR = os.path.join("playlist_posters", "Daily")
SUPPORTED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')

# Shared configuration
SONGS_PER_PLAYLIST = int(os.getenv("SONGS_PER_PLAYLIST", "50"))
MAX_ARTIST_PERCENTAGE = float(os.getenv("MAX_ARTIST_PERCENTAGE", "0.3"))
MAX_LIKED_ARTISTS_PERCENTAGE = float(os.getenv("MAX_LIKED_ARTISTS_PERCENTAGE", "0.8"))
MIN_VARIETY_PERCENTAGE = float(os.getenv("MIN_VARIETY_PERCENTAGE", "0.1"))
LIKED_ARTISTS_CACHE_FILE = os.getenv("LIKED_ARTISTS_CACHE_FILE", "liked_artists_cache.json")
UPDATE_POSTERS = os.getenv("UPDATE_POSTERS", "true").lower() == "true"

# Daily-specific configuration
PLAYLIST_COUNT = int(os.getenv("DAILY_PLAYLIST_COUNT", "14"))
GENRE_GROUPS_FILE = os.getenv("DAILY_GENRE_GROUPS_FILE", "genre_groups.json")
DAILY_LOG_FILE = os.getenv("DAILY_LOG_FILE", "dailylog.txt")
MAX_LOG_ENTRIES = int(os.getenv("DAILY_MAX_LOG_ENTRIES", "50"))
MIN_SONGS_REQUIRED = float(os.getenv("DAILY_MIN_SONGS_REQUIRED", "0.8")) * SONGS_PER_PLAYLIST

# Connect to the Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

# Get available images from a directory
def get_available_images(directory):
    """Get a list of all available image files in the specified directory."""
    if not os.path.exists(directory):
        print(f"⚠️  Directory '{directory}' does not exist. No posters will be used.")
        return []
    
    try:
        all_files = os.listdir(directory)
        image_files = [f for f in all_files if f.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS)]
        return image_files
    except Exception as e:
        print(f"⚠️  Error reading directory '{directory}': {e}")
        return []

# Get a random unused image from the available pool
def get_random_unused_image(available_images, used_images):
    """Select a random image that hasn't been used yet in this run."""
    unused_images = [img for img in available_images if img not in used_images]
    
    if not unused_images:
        print(f"⚠️  No unused images available. Reusing images from the pool.")
        unused_images = available_images
    
    if not unused_images:
        print(f"❌ No images available in the poster directory.")
        return None
    
    selected = random.choice(unused_images)
    return selected

# Upload poster to a playlist
def upload_playlist_poster(playlist, image_path):
    """Upload a poster image to a Plex playlist."""
    try:
        if image_path and os.path.exists(image_path):
            playlist.uploadPoster(filepath=image_path)
            print(f"✅ Uploaded poster: {os.path.basename(image_path)}")
        else:
            print(f"⚠️  Poster file not found: {image_path}")
    except Exception as e:
        print(f"⚠️  Could not upload poster: {e}")

# Get artist name from a track
def get_artist_name(track):
    """Get the artist name from a track, handling different Plex track structures."""
    if hasattr(track, 'artist') and track.artist:
        return track.artist().title if callable(track.artist) else track.artist
    elif hasattr(track, 'grandparentTitle') and track.grandparentTitle:
        return track.grandparentTitle
    return None

# Count liked tracks only (for cache validation)
def count_liked_tracks():
    """Count liked tracks without extracting artists (for cache validation)."""
    try:
        print("⚡ Quickly counting liked tracks to check cache validity...")
        
        # Get music library
        music_library = plex.library.section("Music")
        
        # Try different approaches to count liked tracks
        liked_count = 0
        
        # Method 1: Try searchTracks with userRating__gte
        try:
            liked_items = music_library.searchTracks(userRating__gte=1)
            liked_count = len(liked_items)
            print(f"✅ Method 1 (searchTracks): Found {liked_count:,} liked tracks")
        except Exception as e1:
            print(f"❌ Method 1 failed: {e1}")
            liked_count = 0
        
        # Method 2: Try search with different filter syntax
        if liked_count == 0:
            try:
                liked_items = music_library.search(libtype="track", filters={'userRating>=': 1}, limit=None)
                liked_count = len(liked_items)
                print(f"✅ Method 2 (search with userRating>=): Found {liked_count:,} liked tracks")
            except Exception as e2:
                print(f"❌ Method 2 failed: {e2}")
                liked_count = 0
        
        # Method 3: Try search with userRating__gte in filters
        if liked_count == 0:
            try:
                liked_items = music_library.search(libtype="track", filters={'userRating__gte': 1}, limit=None)
                liked_count = len(liked_items)
                print(f"✅ Method 3 (search with userRating__gte): Found {liked_count:,} liked tracks")
            except Exception as e3:
                print(f"❌ Method 3 failed: {e3}")
                liked_count = 0
        
        return liked_count
        
    except Exception as e:
        print(f"❌ Error counting liked tracks: {e}")
        return 0


# Get liked artists from Plex by fetching liked tracks directly (1+ stars)
def get_liked_artists():
    """Get a set of artist names from all liked tracks (1+ stars) in Plex."""
    try:
        print("🎵 Fetching liked artists from Plex by querying liked tracks directly...")
        liked_artists = set()
        
        # Get music library
        music_library = plex.library.section("Music")
        
        # Try different approaches to find liked tracks
        print("🔍 Attempting to query Plex for tracks with 1+ star rating...")
        
        # Method 1: Try searchTracks with userRating__gte
        try:
            liked_items = music_library.searchTracks(userRating__gte=1)
            print(f"✅ Method 1 (searchTracks): Found {len(liked_items):,} liked tracks")
        except Exception as e1:
            print(f"❌ Method 1 failed: {e1}")
            liked_items = []
        
        # Method 2: Try search with different filter syntax
        if not liked_items:
            try:
                liked_items = music_library.search(libtype="track", filters={'userRating>=': 1}, limit=None)
                print(f"✅ Method 2 (search with userRating>=): Found {len(liked_items):,} liked tracks")
            except Exception as e2:
                print(f"❌ Method 2 failed: {e2}")
                liked_items = []
        
        # Method 3: Try search with userRating__gte in filters
        if not liked_items:
            try:
                liked_items = music_library.search(libtype="track", filters={'userRating__gte': 1}, limit=None)
                print(f"✅ Method 3 (search with userRating__gte): Found {len(liked_items):,} liked tracks")
            except Exception as e3:
                print(f"❌ Method 3 failed: {e3}")
                liked_items = []
        
        # Method 4: Fallback - get all tracks and filter manually (for debugging)
        if not liked_items:
            print("⚠️ All direct filtering methods failed. Falling back to manual filtering for debugging...")
            print("🐌 This will be slower but will help us debug the issue.")
            all_tracks = music_library.search(libtype="track", limit=None)
            print(f"📊 Loaded {len(all_tracks):,} total tracks for manual filtering...")
            
            # Debug: Check a few tracks for their userRating
            print("🔍 Checking first 10 tracks for userRating values:")
            for i, track in enumerate(all_tracks[:10]):
                rating = getattr(track, 'userRating', 'No userRating attribute')
                print(f"  Track {i+1}: {track.title} - userRating: {rating}")
            
            # Filter manually
            liked_items = []
            for i, track in enumerate(all_tracks):
                if hasattr(track, 'userRating') and track.userRating and track.userRating >= 1:
                    liked_items.append(track)
                
                # Show progress every 5000 tracks
                if i % 5000 == 0 and i > 0:
                    print(f"Manual filtering progress: {i:,}/{len(all_tracks):,} tracks - Found {len(liked_items):,} liked tracks so far", end='\r')
            
            print(f"\n✅ Manual filtering complete: Found {len(liked_items):,} liked tracks")
        
        if not liked_items:
            print("❌ No liked tracks found with any method. Please check:")
            print("1. Do you have tracks rated 1+ stars in Plex?")
            print("2. Are you logged in as the correct user?")
            print("3. Is your Plex server up to date?")
            return set(), 0
        
        print(f"🎯 Found {len(liked_items):,} liked tracks, extracting artists...")
        
        # Extract artists with progress display
        for i, track in enumerate(liked_items, 1):
            artist_name = get_artist_name(track)
            if artist_name:
                liked_artists.add(artist_name)
            
            # Show progress every 100 tracks or at the end
            if i % 100 == 0 or i == len(liked_items):
                progress_percent = (i / len(liked_items)) * 100
                print(f"Artist extraction: {i:,}/{len(liked_items):,} tracks ({progress_percent:.1f}%) - Found {len(liked_artists):,} unique artists so far", end='\r')
        
        print(f"\n🎉 Found {len(liked_artists):,} unique liked artists from {len(liked_items):,} liked tracks")
        return liked_artists, len(liked_items)
        
    except Exception as e:
        print(f"❌ Error fetching liked artists: {e}")
        return set(), 0

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
            print(f"Loaded genre groups successfully!")
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


# Load liked artists from cache file
def load_liked_artists_cache():
    """Load liked artists and track count from cache file."""
    print("🔍 Checking liked artists cache...")
    if not os.path.exists(LIKED_ARTISTS_CACHE_FILE):
        print("❌ No liked artists cache found.")
        return None, 0, None
    
    try:
        with open(LIKED_ARTISTS_CACHE_FILE, "r") as file:
            cache_data = json.load(file)
            liked_artists = set(cache_data.get("liked_artists", []))
            cached_track_count = cache_data.get("liked_track_count", 0)
            cache_timestamp = cache_data.get("cache_timestamp", None)
            
            if cache_timestamp:
                from datetime import datetime, timedelta
                cache_date = datetime.fromisoformat(cache_timestamp)
                days_old = (datetime.now() - cache_date).days
                print(f"✅ Loaded {len(liked_artists):,} liked artists from cache (from {cached_track_count:,} tracks)")
                print(f"📅 Cache is {days_old} days old")
                return liked_artists, cached_track_count, cache_timestamp
            else:
                print(f"✅ Loaded {len(liked_artists):,} liked artists from cache (from {cached_track_count:,} tracks)")
                print("⚠️ Cache has no timestamp - will refresh to add timestamp")
                return liked_artists, cached_track_count, None
    except Exception as e:
        print(f"❌ Error loading liked artists cache: {e}")
        return None, 0, None


# Save liked artists to cache file
def save_liked_artists_cache(liked_artists, track_count):
    """Save liked artists and track count to cache file."""
    print("💾 Saving liked artists to cache...")
    try:
        from datetime import datetime
        cache_data = {
            "liked_artists": list(liked_artists),
            "liked_track_count": track_count,
            "cache_timestamp": datetime.now().isoformat()
        }
        with open(LIKED_ARTISTS_CACHE_FILE, "w") as file:
            json.dump(cache_data, file, indent=2)
        print(f"✅ Saved {len(liked_artists):,} liked artists to cache (from {track_count:,} tracks)")
        print(f"📅 Cache timestamp: {cache_data['cache_timestamp']}")
    except Exception as e:
        print(f"❌ Error saving liked artists cache: {e}")


# Check if cache is older than configured days
def is_cache_old(cache_timestamp):
    """Check if cache is older than configured days."""
    if not cache_timestamp:
        return True
    
    try:
        from datetime import datetime, timedelta
        cache_date = datetime.fromisoformat(cache_timestamp)
        days_old = (datetime.now() - cache_date).days
        cache_days = int(os.getenv("CACHE_DAYS", "7"))
        return days_old >= cache_days
    except Exception as e:
        print(f"Error checking cache age: {e}")
        return True


# Generate daily playlists
def generate_daily_playlists():
    print("🔌 Connecting to Plex server...")
    try:
        music_library = plex.library.section("Music")  # Adjust if your music library name differs
        print("✅ Successfully connected to Plex server and accessed 'Music' library.")
    except Exception as e:
        print(f"❌ Error connecting to Plex server or accessing library: {e}")
        return

    # Load genre groups
    genre_groups = load_genre_groups()
    if not genre_groups:
        print("❌ No genre groups available. Exiting.")
        return

    # Get available poster images
    used_images = set()
    
    if UPDATE_POSTERS:
        print("🖼️  Loading poster images...")
        available_images = get_available_images(PLAYLIST_POSTERS_DIR)
        
        if available_images:
            print(f"✅ Found {len(available_images)} poster images in '{PLAYLIST_POSTERS_DIR}'")
        else:
            print(f"⚠️  No poster images found in '{PLAYLIST_POSTERS_DIR}'. Playlists will be created without posters.")
    else:
        print("ℹ️  Poster updates are disabled. Skipping poster loading.")
        available_images = []

    # Get liked artists with weekly caching logic
    print("🎵 Loading liked artists...")
    cached_artists, cached_track_count, cache_timestamp = load_liked_artists_cache()
    
    if cached_artists is not None and not is_cache_old(cache_timestamp):
        # We have fresh cached data (less than configured days old)
        cache_days = int(os.getenv("CACHE_DAYS", "7"))
        print(f"✅ Using cached liked artists (cache is fresh, less than {cache_days} days old)")
        liked_artists = cached_artists
    else:
        # Cache is old or doesn't exist, refresh it
        cache_days = int(os.getenv("CACHE_DAYS", "7"))
        if cached_artists is not None:
            print(f"🔄 Cache is older than {cache_days} days. Refreshing liked artists data...")
        else:
            print("🆕 No cache available. Fetching fresh liked artists data...")
        
        print("🔄 Fetching liked artists with progress display...")
        liked_artists, track_count = get_liked_artists()
        save_liked_artists_cache(liked_artists, track_count)

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

            # Get a random unused poster image (only if poster updates are enabled)
            poster_image = None
            if UPDATE_POSTERS and available_images:
                selected_image_name = get_random_unused_image(available_images, used_images)
                if selected_image_name:
                    poster_image = os.path.join(PLAYLIST_POSTERS_DIR, selected_image_name)
                    used_images.add(selected_image_name)
                    print(f"📸 Selected poster: {selected_image_name}")

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

                # Update the description with the selected genres and timestamp
                genre_description = ", ".join(selected_genres)
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                existing_playlist.editSummary(f"{selected_group}\nUpdated on: {timestamp}\nGenres used: {genre_description}")
                
                # Upload poster if available
                if poster_image:
                    upload_playlist_poster(existing_playlist, poster_image)
                playlist = existing_playlist
            else:
                print(f"Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)

                # Set the description with the selected genres and timestamp
                genre_description = ", ".join(selected_genres)
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                playlist.editSummary(f"{selected_group}\nUpdated on: {timestamp}\nGenres used: {genre_description}")
                
                # Upload poster if available
                if poster_image:
                    upload_playlist_poster(playlist, poster_image)

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

from plexapi.server import PlexServer
import random
import json
import os
import time
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from urllib.parse import quote
import urllib.request
import tempfile

# Load environment variables from .env file
load_dotenv()

# Validation function to check required environment variables
def validate_env_vars(required_vars, script_name):
    """Validate that all required environment variables are set."""
    missing_vars = []
    for var in required_vars:
        value = os.getenv(var)
        if value is None or value.strip() == "":
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ ERROR: Missing required environment variables for {script_name}:")
        for var in missing_vars:
            print(f"   - {var}")
        print(f"\nPlease ensure all required variables are set in your .env file.")
        print(f"Refer to example.env for the complete list of required variables.")
        exit(1)

# Define required environment variables for PPG-LikedArtists.py
REQUIRED_ENV_VARS = [
    # Plex Server
    "PLEX_URL",
    "PLEX_TOKEN",
    # Shared configuration
    "SONGS_PER_PLAYLIST",
    "MAX_ARTIST_PERCENTAGE",
    "MAX_LIKED_ARTISTS_PERCENTAGE",
    "MIN_VARIETY_PERCENTAGE",
    "LIKED_ARTISTS_CACHE_FILE",
    # Quality & Variety
    "MIN_SONG_DURATION_SECONDS",
    "MAX_SONGS_PER_ALBUM",
    "PREVENT_CONSECUTIVE_ARTISTS",
    "MOOD_GROUPING_ENABLED",
    # Logging
    "LOG_LEVEL",
    # Liked Artists-specific
    "LIKED_ARTISTS_PLAYLIST_COUNT",
    "LIKED_ARTISTS_MIN_SONGS_REQUIRED",
    "LIKED_ARTISTS_SIMILARITY_METHOD",
    "LIKED_ARTISTS_LOG_FILE",
    "LIKED_ARTISTS_MAX_LOG_ENTRIES"
]

# Validate environment variables before proceeding
validate_env_vars(REQUIRED_ENV_VARS, "PPG-LikedArtists.py")

# Fetch all configuration from environment variables (no defaults)
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")

# Paths for playlist posters
PLAYLIST_POSTERS_DIR = os.path.join("playlist_posters", "LikedArtists")
SUPPORTED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')

# Shared configuration
SONGS_PER_PLAYLIST = int(os.getenv("SONGS_PER_PLAYLIST"))
MAX_ARTIST_PERCENTAGE = float(os.getenv("MAX_ARTIST_PERCENTAGE"))
MAX_LIKED_ARTISTS_PERCENTAGE = float(os.getenv("MAX_LIKED_ARTISTS_PERCENTAGE"))
MIN_VARIETY_PERCENTAGE = float(os.getenv("MIN_VARIETY_PERCENTAGE"))
LIKED_ARTISTS_CACHE_FILE = os.getenv("LIKED_ARTISTS_CACHE_FILE")

# Quality & Variety configuration
MIN_SONG_DURATION_SECONDS = int(os.getenv("MIN_SONG_DURATION_SECONDS"))
MAX_SONGS_PER_ALBUM = int(os.getenv("MAX_SONGS_PER_ALBUM"))
PREVENT_CONSECUTIVE_ARTISTS = os.getenv("PREVENT_CONSECUTIVE_ARTISTS").lower() == "true"
MOOD_GROUPING_ENABLED = os.getenv("MOOD_GROUPING_ENABLED").lower() == "true"

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL").upper()

# Log level hierarchy (lower number = lower priority)
LOG_LEVELS = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3
}

def log(level, message, end="\n"):
    """Log a message if the log level is appropriate."""
    current_level = LOG_LEVELS.get(LOG_LEVEL, 1)
    message_level = LOG_LEVELS.get(level, 1)
    
    if message_level >= current_level:
        print(message, end=end)

# Convenience functions for common log levels
def log_debug(message, end="\n"):
    """Log a DEBUG message."""
    log("DEBUG", message, end=end)

def log_info(message, end="\n"):
    """Log an INFO message."""
    log("INFO", message, end=end)

def log_warning(message, end="\n"):
    """Log a WARNING message."""
    log("WARNING", message, end=end)

def log_error(message, end="\n"):
    """Log an ERROR message."""
    log("ERROR", message, end=end)

# Format time duration in a readable way
def format_duration(seconds):
    """Format a duration in seconds to a human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} {secs} second{'s' if secs != 1 else ''}"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''} {secs} second{'s' if secs != 1 else ''}"

# Liked Artists-specific configuration
PLAYLIST_COUNT = int(os.getenv("LIKED_ARTISTS_PLAYLIST_COUNT"))
MIN_SONGS_REQUIRED = float(os.getenv("LIKED_ARTISTS_MIN_SONGS_REQUIRED")) * SONGS_PER_PLAYLIST
# Similarity method configuration
SIMILARITY_METHOD_CONFIG = os.getenv("LIKED_ARTISTS_SIMILARITY_METHOD").lower()
# Available similarity methods (used when method is "random")
# "similar_artists" = playlist based on artist, uses similar artists
# "similar_tracks" = playlist based on a single liked song, uses similar tracks for that song
AVAILABLE_SIMILARITY_METHODS = ["similar_artists", "similar_tracks"]
LOG_FILE = os.getenv("LIKED_ARTISTS_LOG_FILE")
MAX_LOG_ENTRIES = int(os.getenv("LIKED_ARTISTS_MAX_LOG_ENTRIES"))

# Connect to the Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

# Get available images from a directory
def get_available_images(directory):
    """Get a list of all available image files in the specified directory."""
    if not os.path.exists(directory):
        log_warning(f"⚠️  Directory '{directory}' does not exist. No posters will be used.")
        return []
    
    try:
        all_files = os.listdir(directory)
        image_files = [f for f in all_files if f.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS)]
        return image_files
    except Exception as e:
        log_warning(f"⚠️  Error reading directory '{directory}': {e}")
        return []

# Get a random unused image from the available pool
def get_random_unused_image(available_images, used_images):
    """Select a random image that hasn't been used yet in this run."""
    unused_images = [img for img in available_images if img not in used_images]
    
    if not unused_images:
        log_warning(f"⚠️  No unused images available. Reusing images from the pool.")
        unused_images = available_images
    
    if not unused_images:
        log_error(f"❌ No images available in the poster directory.")
        return None
    
    selected = random.choice(unused_images)
    return selected

# Download poster from Spotify API
def download_spotify_poster(artist_name):
    """Download a poster image from Spotify's seed mix API."""
    try:
        # URL encode the artist name
        url_encoded_name = quote(artist_name, safe='')
        url = f"https://seed-mix-image.spotifycdn.com/v6/img/desc/{url_encoded_name}/en/default"
        
        log_debug(f"📥 Downloading poster from Spotify for '{artist_name}'...")
        
        # Create a temporary file to store the image
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
        temp_path = temp_file.name
        temp_file.close()
        
        # Download the image
        urllib.request.urlretrieve(url, temp_path)
        
        # Check if file was downloaded successfully (not empty)
        if os.path.getsize(temp_path) > 0:
            log_info(f"✅ Downloaded Spotify poster for '{artist_name}'")
            return temp_path
        else:
            log_warning(f"⚠️  Downloaded file is empty for '{artist_name}'")
            os.remove(temp_path)
            return None
    except Exception as e:
        log_warning(f"⚠️  Could not download Spotify poster for '{artist_name}': {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        return None

# Upload poster to a playlist
def upload_playlist_poster(playlist, image_path):
    """Upload a poster image to a Plex playlist."""
    try:
        if image_path and os.path.exists(image_path):
            playlist.uploadPoster(filepath=image_path)
            log_info(f"✅ Uploaded poster: {os.path.basename(image_path)}")
            
            # If it's a temporary file, clean it up after uploading
            if image_path.startswith(tempfile.gettempdir()):
                try:
                    os.remove(image_path)
                    log_debug(f"🧹 Cleaned up temporary poster file")
                except:
                    pass
        else:
            log_warning(f"⚠️  Poster file not found: {image_path}")
    except Exception as e:
        log_warning(f"⚠️  Could not upload poster: {e}")
        # Clean up temp file even if upload failed
        if image_path and image_path.startswith(tempfile.gettempdir()) and os.path.exists(image_path):
            try:
                os.remove(image_path)
            except:
                pass

# Normalize artist name for consistent comparison
def normalize_artist_name(artist_name):
    """Normalize artist name for consistent comparison.
    Handles Unicode (German ÄÖÜ, Cyrillic), whitespace around slashes, 
    multiple spaces, and strips leading/trailing whitespace."""
    if not artist_name:
        return None
    
    import unicodedata
    # Normalize Unicode characters (NFC form - preserves German ÄÖÜ and Cyrillic properly)
    normalized = unicodedata.normalize('NFC', artist_name)
    
    # Strip leading/trailing whitespace
    normalized = normalized.strip()
    
    # Normalize whitespace around slashes
    normalized = normalized.replace(' / ', '/').replace('/ ', '/').replace(' /', '/')
    
    # Normalize multiple spaces to single space
    normalized = ' '.join(normalized.split())
    
    return normalized

# Get artist name from a track
def get_artist_name(track):
    """Get the artist name from a track, handling different Plex track structures."""
    if hasattr(track, 'artist') and track.artist:
        artist_name = track.artist().title if callable(track.artist) else track.artist
    elif hasattr(track, 'grandparentTitle') and track.grandparentTitle:
        artist_name = track.grandparentTitle
    else:
        return None
    
    # Normalize the artist name for consistent comparison
    return normalize_artist_name(artist_name)

# Get original artist name (non-normalized, for display)
def get_artist_name_original(track):
    """Get the original artist name from a track, preserving casing."""
    if hasattr(track, 'artist') and track.artist:
        artist_name = track.artist().title if callable(track.artist) else track.artist
    elif hasattr(track, 'grandparentTitle') and track.grandparentTitle:
        artist_name = track.grandparentTitle
    else:
        return None
    
    if artist_name:
        artist_name = artist_name.strip()
        artist_name = artist_name.replace(' / ', '/').replace('/ ', '/').replace(' /', '/')
        artist_name = ' '.join(artist_name.split())
    
    return artist_name

# Get album name from a track
def get_album_name(track):
    """Get the album name from a track."""
    try:
        if hasattr(track, 'parentTitle') and track.parentTitle:
            return track.parentTitle
        elif hasattr(track, 'album') and track.album:
            album = track.album() if callable(track.album) else track.album
            if album and hasattr(album, 'title'):
                return album.title
        return None
    except Exception as e:
        log_debug(f"⚠️  Error getting album name for track '{track.title}': {e}")
        return None

# Get track duration in seconds
def get_track_duration_seconds(track):
    """Get the track duration in seconds."""
    try:
        if hasattr(track, 'duration'):
            duration_ms = track.duration
            if duration_ms:
                return duration_ms / 1000.0
        return None
    except Exception as e:
        log_debug(f"⚠️  Error getting duration for track '{track.title}': {e}")
        return None

# Get track genres
def get_track_genres(track):
    """Get genres from a track."""
    try:
        genres = []
        if hasattr(track, 'genres') and track.genres:
            if isinstance(track.genres, list):
                genres = [g.tag for g in track.genres if hasattr(g, 'tag')]
            else:
                genres = [track.genres]
        elif hasattr(track, 'genre') and track.genre:
            if isinstance(track.genre, list):
                genres = [g.tag for g in track.genre if hasattr(g, 'tag')]
            else:
                genres = [track.genre]
        return genres
    except Exception as e:
        log_debug(f"Error getting genres for track '{track.title}': {e}")
        return []

# Get track mood
def get_track_mood(track):
    """Get the mood from a track."""
    try:
        if hasattr(track, 'mood') and track.mood:
            # Mood can be a list or a single value
            if isinstance(track.mood, list):
                return track.mood[0] if track.mood else None
            return track.mood
        elif hasattr(track, 'moods') and track.moods:
            # Some tracks have 'moods' (plural)
            if isinstance(track.moods, list):
                return track.moods[0] if track.moods else None
            return track.moods
        return None
    except Exception as e:
        log_debug(f"Error getting mood for track '{track.title}': {e}")
        return None

# Get track style
def get_track_style(track):
    """Get style from a track."""
    try:
        styles = []
        if hasattr(track, 'styles') and track.styles:
            if isinstance(track.styles, list):
                styles = [s.tag for s in track.styles if hasattr(s, 'tag')]
            else:
                styles = [track.styles]
        elif hasattr(track, 'style') and track.style:
            if isinstance(track.style, list):
                styles = [s.tag for s in track.style if hasattr(s, 'tag')]
            else:
                styles = [track.style]
        return styles
    except Exception as e:
        log_debug(f"Error getting style for track '{track.title}': {e}")
        return []

# Filter tracks by minimum duration
def filter_by_minimum_duration(tracks, min_duration_seconds=90):
    """Filter out tracks shorter than the minimum duration."""
    if min_duration_seconds <= 0:
        return tracks
    
    filtered = []
    removed = 0
    for track in tqdm(tracks, desc="Filtering by duration", unit="track", disable=(LOG_LEVEL in ["WARNING", "ERROR"])):
        duration = get_track_duration_seconds(track)
        if duration is None or duration >= min_duration_seconds:
            filtered.append(track)
        else:
            removed += 1
    
    if removed > 0:
        log_info(f"⏱️  Removed {removed} tracks shorter than {min_duration_seconds} seconds")
    
    return filtered

# Limit songs per album
def limit_songs_per_album(playlist_songs, all_available_songs, max_per_album=1):
    """Ensure no more than max_per_album songs from the same album."""
    if max_per_album <= 0:
        return playlist_songs
    
    album_counts = {}
    album_tracks = {}
    
    log_info(f"🔄 Analyzing {len(playlist_songs)} tracks for album grouping...")
    for track in tqdm(playlist_songs, desc="Grouping by album", unit="track", disable=(LOG_LEVEL in ["WARNING", "ERROR"])):
        album_name = get_album_name(track)
        if album_name:
            if album_name not in album_tracks:
                album_tracks[album_name] = []
            album_tracks[album_name].append(track)
            album_counts[album_name] = album_counts.get(album_name, 0) + 1
    
    albums_to_reduce = {
        album: count - max_per_album 
        for album, count in album_counts.items() 
        if count > max_per_album
    }
    
    if not albums_to_reduce:
        log_info(f"✅ No albums exceed the limit ({max_per_album} songs per album)")
        return playlist_songs
    
    log_info(f"💿 Limiting songs per album (max {max_per_album} per album)")
    
    filtered_playlist = []
    for album_name, tracks in album_tracks.items():
        if album_name in albums_to_reduce:
            tracks_to_keep = random.sample(tracks, max_per_album)
            filtered_playlist.extend(tracks_to_keep)
        else:
            filtered_playlist.extend(tracks)
    
    songs_needed = len(playlist_songs) - len(filtered_playlist)
    if songs_needed > 0:
        excluded_albums = set(albums_to_reduce.keys())
        available_songs = [
            song for song in all_available_songs 
            if song not in filtered_playlist 
            and (get_album_name(song) not in excluded_albums or get_album_name(song) is None)
        ]
        
        if len(available_songs) >= songs_needed:
            additional = random.sample(available_songs, songs_needed)
            filtered_playlist.extend(additional)
            log_info(f"✅ Added {len(additional)} additional songs to maintain playlist size")
        else:
            available_any = [s for s in all_available_songs if s not in filtered_playlist]
            if available_any:
                additional = random.sample(available_any, min(songs_needed, len(available_any)))
                filtered_playlist.extend(additional)
                log_info(f"✅ Added {len(additional)} additional songs")
    
    return filtered_playlist

# Prevent consecutive same artist
def prevent_consecutive_artists(playlist_songs):
    """Reorder playlist to prevent same artist appearing consecutively."""
    if len(playlist_songs) < 2:
        return playlist_songs
    
    log_info(f"🔄 Grouping {len(playlist_songs)} tracks by artist for reordering...")
    artist_tracks = {}
    for track in tqdm(playlist_songs, desc="Grouping by artist", unit="track", disable=(LOG_LEVEL in ["WARNING", "ERROR"])):
        artist = get_artist_name(track)
        if artist:
            if artist not in artist_tracks:
                artist_tracks[artist] = []
            artist_tracks[artist].append(track)
        else:
            if 'Unknown' not in artist_tracks:
                artist_tracks['Unknown'] = []
            artist_tracks['Unknown'].append(track)
    
    if len(artist_tracks) <= 1:
        return playlist_songs
    
    for artist in artist_tracks:
        random.shuffle(artist_tracks[artist])
    
    reordered = []
    artist_queue = list(artist_tracks.keys())
    random.shuffle(artist_queue)
    
    while len(reordered) < len(playlist_songs):
        next_artist = None
        attempts = 0
        max_attempts = len(artist_queue) * 2
        
        while attempts < max_attempts:
            candidate = random.choice(artist_queue)
            if artist_tracks[candidate] and (
                not reordered or 
                get_artist_name(reordered[-1]) != candidate
            ):
                next_artist = candidate
                break
            attempts += 1
        
        if not next_artist:
            available = [a for a in artist_queue if artist_tracks[a]]
            if available:
                next_artist = random.choice(available)
        
        if next_artist and artist_tracks[next_artist]:
            reordered.append(artist_tracks[next_artist].pop())
        else:
            break
    
    for tracks in artist_tracks.values():
        reordered.extend(tracks)
    
    log_debug(f"🔄 Reordered playlist to minimize consecutive artist repeats")
    return reordered[:len(playlist_songs)]

# Group and sort by mood
def group_by_mood(playlist_songs):
    """Group and sort tracks by mood for better flow. Picks a random mood from existing tracks and groups by it."""
    log_debug(f"🎵 Starting mood grouping for {len(playlist_songs)} tracks")
    
    # Extract all moods from tracks
    tracks_with_mood = []
    tracks_without_mood = []
    mood_counts = {}  # Count occurrences of each mood
    
    for track in playlist_songs:
        mood = get_track_mood(track)
        if mood:
            tracks_with_mood.append((track, mood))
            mood_counts[mood] = mood_counts.get(mood, 0) + 1
        else:
            tracks_without_mood.append(track)
    
    log_debug(f"  📊 Mood data found: {len(tracks_with_mood)} tracks have mood, {len(tracks_without_mood)} tracks missing mood")
    
    if not tracks_with_mood:
        # No mood data available, just shuffle
        log_debug(f"  ⚠️  No mood data available for any tracks. Shuffling playlist randomly.")
        random.shuffle(playlist_songs)
        return playlist_songs
    
    # Show available moods
    log_debug(f"  🎭 Found {len(mood_counts)} unique moods:")
    for mood, count in sorted(mood_counts.items(), key=lambda x: x[1], reverse=True):
        log_debug(f"    - {mood}: {count} tracks")
    
    # Pick a random mood from the available moods
    if mood_counts:
        selected_mood = random.choice(list(mood_counts.keys()))
        log_info(f"  🎯 Selected mood for grouping: '{selected_mood}' ({mood_counts[selected_mood]} tracks)")
        
        # Group tracks by selected mood
        tracks_matching_mood = [track for track, mood in tracks_with_mood if mood == selected_mood]
        tracks_other_moods = [track for track, mood in tracks_with_mood if mood != selected_mood]
        
        # Start with tracks matching the selected mood
        grouped = tracks_matching_mood.copy()
        random.shuffle(grouped)
        
        # Add tracks with other moods
        random.shuffle(tracks_other_moods)
        grouped.extend(tracks_other_moods)
        
        # Interleave tracks without mood data randomly
        if tracks_without_mood:
            log_debug(f"  🔀 Interleaving {len(tracks_without_mood)} tracks without mood data randomly")
            random.shuffle(tracks_without_mood)
            for track in tracks_without_mood:
                # Insert at random position (avoiding the beginning where mood-matched tracks are)
                if len(grouped) > len(tracks_matching_mood):
                    pos = random.randint(len(tracks_matching_mood), len(grouped))
                    grouped.insert(pos, track)
                else:
                    grouped.append(track)
        
        log_info(f"✅ Mood grouping complete: {len(tracks_matching_mood)} tracks with selected mood '{selected_mood}' grouped first, {len(tracks_other_moods)} other mood tracks, {len(tracks_without_mood)} tracks without mood interleaved")
        return grouped
    else:
        # Fallback: just shuffle
        log_debug(f"  ⚠️  No valid moods found. Shuffling playlist randomly.")
        random.shuffle(playlist_songs)
        return playlist_songs

# Apply all quality filters to a playlist
def apply_quality_filters(playlist_songs, all_available_songs, min_duration_seconds=90, 
                          max_songs_per_album=1, prevent_consecutive=True, 
                          mood_grouping=False):
    """Apply all quality and variety filters to a playlist."""
    original_count = len(playlist_songs)
    
    if min_duration_seconds > 0:
        log_info(f"🔄 Filtering by minimum duration ({min_duration_seconds}s)...")
        playlist_songs = filter_by_minimum_duration(playlist_songs, min_duration_seconds)
        log_info(f"✅ Duration filter: {original_count} tracks -> {len(playlist_songs)} tracks")
    
    if max_songs_per_album > 0 and len(playlist_songs) > max_songs_per_album:
        log_info(f"🔄 Limiting songs per album (max {max_songs_per_album})...")
        before_album = len(playlist_songs)
        playlist_songs = limit_songs_per_album(playlist_songs, all_available_songs, max_songs_per_album)
        log_info(f"✅ Album limit filter: {before_album} tracks -> {len(playlist_songs)} tracks")
    
    if prevent_consecutive and len(playlist_songs) > 1:
        log_info(f"🔄 Reordering to prevent consecutive artists...")
        playlist_songs = prevent_consecutive_artists(playlist_songs)
        log_info(f"✅ Reordered playlist to minimize consecutive artist repeats")
    
    # Group by mood if enabled (after other filters, before finalizing)
    if mood_grouping and len(playlist_songs) > 1:
        log_info(f"🔄 Grouping songs by mood...")
        playlist_songs = group_by_mood(playlist_songs)
        # group_by_mood already logs completion
    
    log_info(f"✅ Quality filters complete: {original_count} tracks -> {len(playlist_songs)} tracks")
    return playlist_songs

# Analyze artist distribution in a playlist
def analyze_artist_distribution(playlist_songs):
    """Analyze the distribution of artists in the playlist and return artist counts."""
    artist_counts = {}
    tracks_iter = tqdm(playlist_songs, desc="Analyzing artists", unit="track", disable=(len(playlist_songs) < 100 or LOG_LEVEL in ["WARNING", "ERROR"]))
    for track in tracks_iter:
        artist_name = get_artist_name(track)
        if artist_name:
            artist_counts[artist_name] = artist_counts.get(artist_name, 0) + 1
    
    return artist_counts

# Helper function to categorize a batch of songs
def categorize_song_batch(song_batch, liked_artists):
    """Categorize a batch of songs into liked and other artists. Used for parallel processing."""
    liked_batch = []
    other_batch = []
    for song in song_batch:
        artist_name = get_artist_name(song)
        if artist_name and artist_name in liked_artists:
            liked_batch.append(song)
        else:
            other_batch.append(song)
    return (liked_batch, other_batch)

# Prefer songs from liked artists with guaranteed variety
def prefer_liked_artists(songs, liked_artists, target_count, max_liked_percentage=0.9, min_variety_percentage=0.1):
    """Select songs with preference for liked artists, but ensure minimum variety from other artists."""
    if not liked_artists:
        log_debug("No liked artists found, selecting randomly.")
        return random.sample(songs, min(len(songs), target_count))
    
    # Calculate target counts based on percentages
    max_liked_count = int(target_count * max_liked_percentage)
    min_variety_count = int(target_count * min_variety_percentage)
    
    log_debug(f"Target distribution: max {max_liked_percentage*100:.0f}% liked artists ({max_liked_count}), min {min_variety_percentage*100:.0f}% variety ({min_variety_count})")
    
    # Separate songs into liked and non-liked artists using multi-threading
    log_info(f"🔄 Categorizing {len(songs)} songs by liked artists (multi-threaded)...")
    liked_songs = []
    other_songs = []
    
    # Determine optimal batch size and number of workers
    # Use smaller batches for better load distribution, but not too small to avoid overhead
    batch_size = max(50, len(songs) // 20)  # Aim for ~20 batches, minimum 50 songs per batch
    num_workers = min(10, max(4, len(songs) // batch_size))  # 4-10 workers depending on song count
    
    # Split songs into batches
    song_batches = [songs[i:i + batch_size] for i in range(0, len(songs), batch_size)]
    
    # Process batches in parallel
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit all batches
        future_to_batch = {executor.submit(categorize_song_batch, batch, liked_artists): batch for batch in song_batches}
        
        # Collect results with progress bar
        with tqdm(total=len(song_batches), desc="Categorizing songs", unit="batch", disable=(LOG_LEVEL in ["WARNING", "ERROR"])) as pbar:
            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                try:
                    liked_batch, other_batch = future.result()
                    liked_songs.extend(liked_batch)
                    other_songs.extend(other_batch)
                    pbar.update(1)
                    pbar.set_postfix({"liked": len(liked_songs), "other": len(other_songs)})
                except Exception as e:
                    log_error(f"Error processing batch: {e}")
                    pbar.update(1)
    
    log_info(f"✅ Found {len(liked_songs)} songs from liked artists, {len(other_songs)} from other artists")
    
    selected_songs = []
    
    # Ensure minimum variety first
    if other_songs and min_variety_count > 0:
        variety_count = min(len(other_songs), min_variety_count)
        selected_songs.extend(random.sample(other_songs, variety_count))
        log_debug(f"Selected {variety_count} songs from other artists for guaranteed variety")
    
    # Fill remaining slots with liked artists (up to max percentage)
    remaining_slots = target_count - len(selected_songs)
    if liked_songs and remaining_slots > 0:
        liked_count = min(len(liked_songs), remaining_slots, max_liked_count)
        selected_songs.extend(random.sample(liked_songs, liked_count))
        log_debug(f"Selected {liked_count} songs from liked artists")
    
    # Fill any remaining slots with more other songs if needed
    remaining_slots = target_count - len(selected_songs)
    if other_songs and remaining_slots > 0:
        other_count = min(len(other_songs), remaining_slots)
        # Remove already selected songs from available pool
        available_other_songs = [song for song in other_songs if song not in selected_songs]
        if available_other_songs:
            other_count = min(len(available_other_songs), other_count)
            selected_songs.extend(random.sample(available_other_songs, other_count))
            log_debug(f"Selected {other_count} additional songs from other artists to fill playlist")
    
    # Show final distribution
    final_liked_count = sum(1 for song in selected_songs if get_artist_name(song) in liked_artists)
    final_other_count = len(selected_songs) - final_liked_count
    final_liked_percentage = (final_liked_count / len(selected_songs)) * 100 if selected_songs else 0
    final_other_percentage = (final_other_count / len(selected_songs)) * 100 if selected_songs else 0
    
    log_info(f"📊 Final selection: {final_liked_count} from liked artists ({final_liked_percentage:.1f}%), {final_other_count} from other artists ({final_other_percentage:.1f}%)")
    
    return selected_songs

# Balance artist representation in playlist to max percentage per artist
def balance_artist_representation(playlist_songs, all_available_songs, max_percentage=0.3, target_size=None):
    """Ensure no single artist represents more than max_percentage of the playlist."""
    # Use target size if provided, otherwise use current playlist size
    if target_size is None:
        target_size = len(playlist_songs)
    max_songs_per_artist = int(target_size * max_percentage)
    
    log_info(f"🔄 Balancing artist representation (max {max_percentage*100:.0f}% per artist = {max_songs_per_artist} songs)")
    
    artist_counts = analyze_artist_distribution(playlist_songs)
    log_info(f"📊 Analyzed {len(artist_counts)} unique artists in playlist")
    
    artists_to_reduce = {}
    for artist, count in artist_counts.items():
        if count > max_songs_per_artist:
            excess = count - max_songs_per_artist
            artists_to_reduce[artist] = excess
            log_debug(f"Artist '{artist}' has {count} songs, needs to reduce by {excess}")
    
    if not artists_to_reduce:
        log_info(f"✅ No artists exceed the {max_percentage*100:.0f}% limit. Playlist is balanced.")
        return playlist_songs
    
    log_info(f"📊 Found {len(artists_to_reduce)} artist(s) that exceed the limit, reducing them...")
    
    balanced_playlist = playlist_songs.copy()
    
    for artist, excess_count in artists_to_reduce.items():
        artist_songs = [song for song in balanced_playlist if get_artist_name(song) == artist]
        songs_to_keep = random.sample(artist_songs, max_songs_per_artist)
        songs_to_remove = [song for song in artist_songs if song not in songs_to_keep]
        
        for song in songs_to_remove:
            balanced_playlist.remove(song)
        
        log_debug(f"Kept {len(songs_to_keep)} songs from '{artist}', removed {len(songs_to_remove)}")
    
    songs_needed = target_size - len(balanced_playlist)
    if songs_needed > 0:
        log_debug(f"Need to add {songs_needed} more songs to reach target size")
        
        excluded_artists = set(artists_to_reduce.keys())
        available_songs = [song for song in all_available_songs if song not in balanced_playlist]
        
        filtered_available = []
        for song in available_songs:
            artist_name = get_artist_name(song)
            if artist_name not in excluded_artists:
                filtered_available.append(song)
        
        if len(filtered_available) >= songs_needed:
            additional_songs = random.sample(filtered_available, songs_needed)
            balanced_playlist.extend(additional_songs)
            log_info(f"✅ Added {len(additional_songs)} additional songs from other artists")
        else:
            log_warning(f"⚠️ Warning: Only {len(filtered_available)} songs available from other artists, added all of them")
            balanced_playlist.extend(filtered_available)
    
    return balanced_playlist

# Load liked artists from cache file
def load_liked_artists_cache():
    """Load liked artists, track count, and liked track keys from cache file.
    Supports both old format (list of strings) and new format (list of dicts with 'id' and 'name').
    Returns (liked_artists_set, track_count, cache_timestamp, artist_name_map, liked_track_keys_list, artist_id_map)
    artist_id_map maps normalized artist name -> artist ID (ratingKey)"""
    log_debug("🔍 Checking liked artists cache...")
    if not os.path.exists(LIKED_ARTISTS_CACHE_FILE):
        log_debug("❌ No liked artists cache found.")
        return None, 0, None, {}, [], {}
    
    try:
        with open(LIKED_ARTISTS_CACHE_FILE, "r", encoding='utf-8') as file:
            cache_data = json.load(file)
            
            # Try new format first (detailed with IDs)
            detailed_artists = cache_data.get("liked_artists_detailed", [])
            # Fallback to old format
            raw_artists = cache_data.get("liked_artists", [])
            
            liked_artists = set()
            artist_name_map = {}  # normalized -> original name
            artist_id_map = {}  # normalized -> artist ID (ratingKey)
            
            # Process detailed format (new format with IDs)
            if detailed_artists and isinstance(detailed_artists[0], dict):
                log_debug("📊 Loading artists from detailed format (with IDs)...")
                for artist_info in detailed_artists:
                    artist_name = artist_info.get('name', '')
                    artist_id = artist_info.get('id', None)
                    if artist_name:
                        normalized = normalize_artist_name(artist_name)
                        if normalized:
                            liked_artists.add(normalized)
                            artist_name_map[normalized] = artist_name
                            if artist_id:
                                artist_id_map[normalized] = artist_id
            # Fallback to old format (just names)
            elif raw_artists:
                log_debug("📊 Loading artists from legacy format (names only)...")
                for artist in raw_artists:
                    if isinstance(artist, str):
                        normalized = normalize_artist_name(artist)
                        if normalized:
                            liked_artists.add(normalized)
                            artist_name_map[normalized] = artist
            
            cached_track_count = cache_data.get("liked_track_count", 0)
            liked_track_keys = cache_data.get("liked_track_keys", [])
            cache_timestamp = cache_data.get("cache_timestamp", None)
            
            artists_with_ids = len(artist_id_map)
            if cache_timestamp:
                from datetime import datetime
                cache_date = datetime.fromisoformat(cache_timestamp)
                days_old = (datetime.now() - cache_date).days
                log_info(f"✅ Loaded {len(liked_artists):,} liked artists from cache (from {cached_track_count:,} tracks)")
                if artists_with_ids > 0:
                    log_info(f"✅ Loaded {artists_with_ids:,} artist IDs for accurate matching")
                if liked_track_keys:
                    log_info(f"✅ Loaded {len(liked_track_keys):,} liked track keys from cache")
                log_debug(f"📅 Cache is {days_old} days old")
                return liked_artists, cached_track_count, cache_timestamp, artist_name_map, liked_track_keys, artist_id_map
            else:
                log_info(f"✅ Loaded {len(liked_artists):,} liked artists from cache (from {cached_track_count:,} tracks)")
                if artists_with_ids > 0:
                    log_info(f"✅ Loaded {artists_with_ids:,} artist IDs for accurate matching")
                if liked_track_keys:
                    log_info(f"✅ Loaded {len(liked_track_keys):,} liked track keys from cache")
                log_warning("⚠️ Cache has no timestamp - will refresh to add timestamp")
                return liked_artists, cached_track_count, None, artist_name_map, liked_track_keys, artist_id_map
    except Exception as e:
        log_error(f"❌ Error loading liked artists cache: {e}")
        return None, 0, None, {}, [], {}

# Get artist object by name or ID
def get_artist_object(music_library, artist_name, artist_id=None):
    """Get the artist object from Plex by name or ID.
    If artist_id is provided, uses it for direct lookup (more accurate).
    Otherwise falls back to name-based search."""
    try:
        # If we have an ID, use it for direct lookup (most accurate)
        if artist_id:
            try:
                artist = music_library.fetchItem(artist_id)
                if artist and hasattr(artist, 'type') and artist.type == 'artist':
                    log_debug(f"✅ Found artist by ID: {artist_name} (ID: {artist_id})")
                    return artist
            except Exception as e:
                log_debug(f"Could not fetch artist by ID {artist_id}: {e}, falling back to name search")
        
        # Fallback: Try searching for the artist by name
        artists = music_library.searchArtists(title=artist_name)
        if artists:
            # Find exact match (case-insensitive)
            for artist in artists:
                if normalize_artist_name(artist.title) == normalize_artist_name(artist_name):
                    return artist
            # If no exact match, return first result
            return artists[0]
        
        # Fallback: search all artists
        all_artists = music_library.searchArtists()
        for artist in all_artists:
            if normalize_artist_name(artist.title) == normalize_artist_name(artist_name):
                return artist
        return None
    except Exception as e:
        log_debug(f"Error getting artist object for '{artist_name}': {e}")
        return None

# Get similar artists from Plex API using sonicallySimilar method
def get_similar_artists(music_library, artist_name, artist_id=None):
    """Get similar artists using Plex's sonicallySimilar API method."""
    try:
        artist_obj = get_artist_object(music_library, artist_name, artist_id)
        if not artist_obj:
            log_debug(f"Could not find artist object for '{artist_name}'")
            return []
        
        similar_artists = []
        
        # Method 1: Use sonicallySimilar() method (recommended by PlexAPI)
        try:
            if hasattr(artist_obj, 'sonicallySimilar'):
                log_debug(f"Artist has sonicallySimilar method, attempting to call it...")
                try:
                    # Call sonicallySimilar - don't check hasSonicAnalysis as it may not be reliable
                    similar_items = artist_obj.sonicallySimilar(limit=50, maxDistance=0.25)
                    log_info(f"📊 sonicallySimilar() returned {len(similar_items)} items for '{artist_name}'")
                    
                    # Filter to only get artists (sonicallySimilar can return artists, albums, or tracks)
                    for item in similar_items:
                        item_type = getattr(item, 'type', None)
                        item_title = getattr(item, 'title', 'Unknown')
                        log_debug(f"  Item: {item_title} (type: {item_type})")
                        if item_type == 'artist':
                            similar_artists.append(item)
                        else:
                            log_debug(f"    Skipping non-artist item: {item_title} (type: {item_type})")
                    
                    if similar_artists:
                        log_info(f"✅ Found {len(similar_artists)} similar artists via sonicallySimilar()")
                    elif similar_items:
                        # Show what types we got
                        types_found = {}
                        for item in similar_items:
                            item_type = getattr(item, 'type', 'unknown')
                            types_found[item_type] = types_found.get(item_type, 0) + 1
                        log_warning(f"⚠️  sonicallySimilar() returned {len(similar_items)} items but none were artists. Types found: {types_found}")
                except Exception as e:
                    log_warning(f"⚠️  Error calling sonicallySimilar(): {e}")
                    import traceback
                    log_debug(traceback.format_exc())
            else:
                log_debug(f"Artist object does not have sonicallySimilar method")
        except Exception as e:
            log_warning(f"⚠️  Error accessing sonicallySimilar: {e}")
            import traceback
            log_debug(traceback.format_exc())
        
        # Method 2: Fallback to similar attribute (metadata-based, not sonic)
        if not similar_artists:
            try:
                if hasattr(artist_obj, 'similar'):
                    similar = artist_obj.similar
                    log_debug(f"Found 'similar' attribute, type: {type(similar)}")
                    
                    # Check if it's a callable method or a list/attribute
                    if callable(similar):
                        similar = similar()
                        log_debug(f"Called similar() method, got {len(similar) if isinstance(similar, list) else 'non-list'} items")
                    
                    if similar:
                        # similar can be a list of Similar objects or direct artist objects
                        if isinstance(similar, list):
                            for sim_item in similar:
                                log_debug(f"  Processing similar item: {type(sim_item)}, has 'item': {hasattr(sim_item, 'item')}")
                                # Similar objects have a .item attribute that points to the actual artist
                                if hasattr(sim_item, 'item'):
                                    actual_item = sim_item.item
                                    item_type = getattr(actual_item, 'type', None)
                                    log_debug(f"    Item type: {item_type}, title: {getattr(actual_item, 'title', 'Unknown')}")
                                    if item_type == 'artist':
                                        similar_artists.append(actual_item)
                                elif hasattr(sim_item, 'type'):
                                    item_type = getattr(sim_item, 'type', None)
                                    log_debug(f"    Direct item type: {item_type}, title: {getattr(sim_item, 'title', 'Unknown')}")
                                    if item_type == 'artist':
                                        similar_artists.append(sim_item)
                        else:
                            # Single item
                            if hasattr(similar, 'item'):
                                actual_item = similar.item
                                if getattr(actual_item, 'type', None) == 'artist':
                                    similar_artists.append(actual_item)
                            elif getattr(similar, 'type', None) == 'artist':
                                similar_artists.append(similar)
                        
                        if similar_artists:
                            log_info(f"✅ Found {len(similar_artists)} similar artists via similar attribute (metadata-based)")
                        else:
                            log_debug(f"similar attribute returned items but none were artists")
            except Exception as e:
                log_debug(f"Error accessing similar attribute: {e}")
                import traceback
                log_debug(traceback.format_exc())
        
        # Method 3: Try direct API call to /nearest endpoint (what sonicallySimilar uses internally)
        if not similar_artists:
            try:
                log_debug(f"Trying direct API call to /nearest endpoint...")
                url = f"{artist_obj.key}/nearest?limit=50&maxDistance=0.25"
                similar_items = artist_obj.fetchItems(url, cls=type(artist_obj))
                log_info(f"📊 Direct /nearest API returned {len(similar_items)} items for '{artist_name}'")
                
                for item in similar_items:
                    item_type = getattr(item, 'type', None)
                    if item_type == 'artist':
                        similar_artists.append(item)
                        log_debug(f"  Found artist: {getattr(item, 'title', 'Unknown')}")
                
                if similar_artists:
                    log_info(f"✅ Found {len(similar_artists)} similar artists via direct /nearest API")
            except Exception as e:
                log_debug(f"Error calling direct /nearest API: {e}")
                import traceback
                log_debug(traceback.format_exc())
        
        if not similar_artists:
            log_warning(f"⚠️  No similar artists found for '{artist_name}'. Note: Similar artists require Plex Pass and completed sonic analysis.")
            log_debug(f"Artist ratingKey: {artist_obj.ratingKey}, tried methods: sonicallySimilar(), similar(), direct /nearest API")
        
        # Limit to 15 randomly selected similar artists
        if len(similar_artists) > 15:
            log_info(f"📊 Randomly selecting 15 similar artists from {len(similar_artists)} total")
            similar_artists = random.sample(similar_artists, 15)
        
        return similar_artists
    except Exception as e:
        log_debug(f"Error getting similar artists for '{artist_name}': {e}")
        import traceback
        log_debug(traceback.format_exc())
        return []

# Get a random liked track (using cached track keys only)
def get_random_liked_track(music_library, liked_track_keys=None):
    """Get a random track from liked tracks using cached track keys only.
    Does not query Plex directly - relies on the cache created by fetch-liked-artists.py.
    If liked_track_keys is not provided or empty, returns None."""
    try:
        # Must have cached track keys - we don't query Plex directly
        if not liked_track_keys or len(liked_track_keys) == 0:
            log_warning("⚠️  No cached track keys available. Run fetch-liked-artists.py to create the cache.")
            return None
        
        log_debug(f"🔍 get_random_liked_track: Using cached track keys ({len(liked_track_keys)} tracks)")
        # Pick a random key
        random_key = random.choice(liked_track_keys)
        log_debug(f"🔍 get_random_liked_track: Selected track key: {random_key}")
        
        # Fetch the track by key
        try:
            track = music_library.fetchItem(random_key)
            log_debug(f"🔍 get_random_liked_track: Fetched track: {getattr(track, 'title', 'Unknown')}")
            return track
        except Exception as e:
            log_warning(f"⚠️  Error fetching track with key {random_key}: {e}")
            log_warning("⚠️  Track may have been deleted from Plex. Consider refreshing the cache with fetch-liked-artists.py")
            return None
    except Exception as e:
        log_error(f"❌ Error getting random liked track: {e}")
        import traceback
        log_debug(traceback.format_exc())
        return None

# Get similar tracks from Plex API using sonicallySimilar method
def get_similar_tracks(music_library, track, use_fallbacks=False):
    """Get similar tracks using Plex's sonicallySimilar API method.
    
    Args:
        music_library: Plex music library
        track: Track object to find similar tracks for
        use_fallbacks: If False, only try sonicallySimilar() and return immediately if it fails/hangs
    """
    try:
        similar_tracks = []
        track_title = getattr(track, 'title', 'Unknown')
        
        # Method 1: Use sonicallySimilar() method (recommended by PlexAPI)
        try:
            log_debug(f"🔍 get_similar_tracks: Checking if track has sonicallySimilar method...")
            if hasattr(track, 'sonicallySimilar'):
                log_info(f"📡 Calling sonicallySimilar() for '{track_title}'...")
                log_debug(f"🔍 get_similar_tracks: About to call track.sonicallySimilar(limit=50, maxDistance=0.25)...")
                # Call sonicallySimilar - don't check hasSonicAnalysis as it may not be reliable or may be slow
                try:
                    similar_items = track.sonicallySimilar(limit=50, maxDistance=0.25)
                    log_debug(f"🔍 get_similar_tracks: sonicallySimilar() call completed, returned {len(similar_items)} items")
                    log_info(f"📊 sonicallySimilar() returned {len(similar_items)} items for '{track_title}'")
                    
                    # Filter to only get tracks (sonicallySimilar can return artists, albums, or tracks)
                    for item in similar_items:
                        item_type = getattr(item, 'type', None)
                        if item_type == 'track':
                            similar_tracks.append(item)
                    
                    if similar_tracks:
                        log_info(f"✅ Found {len(similar_tracks)} similar tracks via sonicallySimilar()")
                        return similar_tracks  # Return immediately if we found tracks
                    elif similar_items:
                        # Show what types we got
                        types_found = {}
                        for item in similar_items:
                            item_type = getattr(item, 'type', 'unknown')
                            types_found[item_type] = types_found.get(item_type, 0) + 1
                        log_warning(f"⚠️  sonicallySimilar() returned {len(similar_items)} items but none were tracks. Types found: {types_found}")
                        if not use_fallbacks:
                            return []  # Return empty if not using fallbacks
                except Exception as e:
                    log_warning(f"⚠️  Error calling sonicallySimilar(): {e}")
                    import traceback
                    log_debug(traceback.format_exc())
                    if not use_fallbacks:
                        return []  # Return empty if not using fallbacks
            else:
                log_debug(f"Track object does not have sonicallySimilar method")
                if not use_fallbacks:
                    return []  # Return empty if not using fallbacks
        except Exception as e:
            log_warning(f"⚠️  Error accessing sonicallySimilar: {e}")
            import traceback
            log_debug(traceback.format_exc())
            if not use_fallbacks:
                return []  # Return empty if not using fallbacks
        
        # Only use fallbacks if explicitly requested
        if not use_fallbacks:
            log_warning(f"⚠️  No similar tracks found for '{track_title}' via sonicallySimilar(). Skipping fallbacks.")
            return []
        
        # Method 2: Fallback to similar attribute (metadata-based, not sonic) - SKIPPED for speed
        # Method 3: Try direct API call to /nearest endpoint - SKIPPED for speed
        
        if not similar_tracks:
            log_warning(f"⚠️  No similar tracks found for '{track_title}'. Note: Similar tracks require Plex Pass and completed sonic analysis.")
            log_debug(f"Track ratingKey: {track.ratingKey}, tried method: sonicallySimilar()")
        
        return similar_tracks
    except Exception as e:
        log_debug(f"Error getting similar tracks: {e}")
        import traceback
        log_debug(traceback.format_exc())
        return []

# Get tracks by artist name or ID
def get_tracks_by_artist(music_library, artist_name, artist_id=None):
    """Get all tracks by a specific artist.
    If artist_id is provided, uses it for direct lookup (more accurate)."""
    try:
        # First, try to get the artist object and get tracks from it
        artist_obj = get_artist_object(music_library, artist_name, artist_id)
        if artist_obj:
            try:
                # Get tracks from the artist object
                if hasattr(artist_obj, 'tracks'):
                    tracks = artist_obj.tracks()
                    if tracks:
                        log_debug(f"Found {len(tracks)} tracks from artist object for '{artist_name}'")
                        return tracks
                # Alternative: try albums and get tracks from albums
                if hasattr(artist_obj, 'albums'):
                    albums = artist_obj.albums()
                    tracks = []
                    for album in albums:
                        if hasattr(album, 'tracks'):
                            album_tracks = album.tracks()
                            tracks.extend(album_tracks)
                    if tracks:
                        log_debug(f"Found {len(tracks)} tracks from artist albums for '{artist_name}'")
                        return tracks
            except Exception as e:
                log_debug(f"Error getting tracks from artist object: {e}")
        
        # Fallback: search all tracks and filter by artist name (with limit to avoid hanging)
        log_debug(f"Falling back to searching tracks for '{artist_name}'...")
        try:
            # Try a limited search first to avoid hanging
            all_tracks = music_library.searchTracks(limit=10000)  # Limit to avoid hanging on huge libraries
            matching_tracks = []
            for track in all_tracks:
                track_artist = get_artist_name_original(track)
                if track_artist and normalize_artist_name(track_artist) == normalize_artist_name(artist_name):
                    matching_tracks.append(track)
            
            if matching_tracks:
                log_debug(f"Found {len(matching_tracks)} tracks by searching tracks for '{artist_name}'")
            return matching_tracks
        except Exception as e:
            log_error(f"Error in fallback track search for '{artist_name}': {e}")
            return []
    except Exception as e:
        log_error(f"Error getting tracks for artist '{artist_name}': {e}")
        return []

# Extract similarity attributes from tracks
def extract_similarity_attributes(tracks, method):
    """Extract genres, similar artists, or similar tracks from tracks based on similarity method.
    Returns a tuple of (all_attributes, genre_attrs, similar_artists_list, similar_tracks_list) for combined method,
    or just all_attributes for single method (or special markers for similar_artists/similar_tracks methods)."""
    all_attributes = set()
    genre_attrs = set()
    similar_artists_list = []  # List of artist objects
    similar_tracks_list = []  # List of track objects
    
    for track in tracks:
        if method == "genre" or method == "combined":
            genres = get_track_genres(track)
            all_attributes.update(genres)
            if method == "combined":
                genre_attrs.update(genres)
    
    # For similar_artists method, we'll get similar artists separately (not from tracks)
    if method == "similar_artists":
        # Return a special marker - we'll handle this differently
        return "similar_artists_method"
    
    # For similar_tracks method, we'll get similar tracks separately (not from tracks)
    if method == "similar_tracks":
        # Return a special marker - we'll handle this differently
        return "similar_tracks_method"
    
    if method == "combined":
        return (all_attributes, genre_attrs, similar_artists_list, similar_tracks_list)
    else:
        return all_attributes

# Find similar tracks using similar artists
def find_similar_tracks_via_artists(music_library, artist_name, exclude_artists=None, artist_id=None):
    """Find tracks from similar artists using Plex's similar artists feature.
    If artist_id is provided, uses it for more accurate artist lookup."""
    if exclude_artists is None:
        exclude_artists = set()
    
    similar_tracks = []
    seen_tracks = set()
    
    log_info(f"🔍 Finding similar artists for '{artist_name}'...")
    similar_artists = get_similar_artists(music_library, artist_name, artist_id)
    
    if not similar_artists:
        log_warning(f"⚠️  No similar artists found for '{artist_name}'. Falling back to genre-based search.")
        return []
    
    log_info(f"✅ Found {len(similar_artists)} similar artists")
    
    # Log the similar artist names for debugging
    if LOG_LEVEL == "DEBUG":
        for i, sa in enumerate(similar_artists[:10], 1):  # Show first 10
            sa_name = sa.title if hasattr(sa, 'title') else str(sa)
            log_debug(f"  Similar artist {i}: {sa_name}")
    
    # Get tracks from each similar artist
    for similar_artist in tqdm(similar_artists, desc="Getting tracks from similar artists", unit="artist", disable=(LOG_LEVEL in ["WARNING", "ERROR"])):
        try:
            # Validate this is actually an artist object
            item_type = getattr(similar_artist, 'type', None)
            if item_type != 'artist':
                log_debug(f"Skipping non-artist item (type: {item_type}): {similar_artist}")
                continue
            
            artist_name_similar = similar_artist.title if hasattr(similar_artist, 'title') else str(similar_artist)
            
            # Additional validation: check if this looks like an album name (common patterns)
            # Album names often have patterns like "Album Name: Subtitle" or contain words like "Complete", "Collection", etc.
            if not artist_name_similar:
                log_debug(f"Skipping empty artist name")
                continue
            
            # Check for common album name patterns
            album_indicators = [':', ' - ', 'Complete', 'Collection', 'Greatest Hits', 'Best Of', 'Anthology', 'Deluxe', 'Remastered']
            if any(indicator in artist_name_similar for indicator in album_indicators):
                log_debug(f"Skipping item that looks like an album name: '{artist_name_similar}'")
                continue
            
            if len(artist_name_similar) > 100:
                log_debug(f"Skipping very long name (likely not an artist): {artist_name_similar[:50]}...")
                continue
            
            # Try to get tracks directly from the artist object first (faster)
            try:
                if hasattr(similar_artist, 'tracks'):
                    tracks = similar_artist.tracks()
                    if tracks:
                        log_debug(f"Getting {len(tracks)} tracks directly from artist object '{artist_name_similar}'")
                        added_count = 0
                        excluded_count = 0
                        for track in tracks:
                            track_id = getattr(track, 'ratingKey', None) or id(track)
                            if track_id not in seen_tracks:
                                artist = get_artist_name(track)
                                if artist not in exclude_artists:
                                    similar_tracks.append(track)
                                    seen_tracks.add(track_id)
                                    added_count += 1
                                else:
                                    excluded_count += 1
                                    log_debug(f"Excluded track from '{artist}' (in exclude list)")
                        log_info(f"✅ Added {added_count} tracks from similar artist '{artist_name_similar}' (excluded {excluded_count} from original artist)")
                        continue  # Successfully got tracks, skip the slower method
                    else:
                        log_debug(f"No tracks found in artist object for '{artist_name_similar}'")
            except Exception as e:
                log_debug(f"Error getting tracks directly from artist object '{artist_name_similar}': {e}")
            
            # Fallback: search by artist name (but limit to avoid hanging)
            artist_normalized = normalize_artist_name(artist_name_similar)
            
            if artist_normalized and artist_normalized not in exclude_artists:
                # Get tracks by this similar artist (with timeout protection)
                try:
                    tracks = get_tracks_by_artist(music_library, artist_name_similar)
                    if tracks:
                        # Limit the number of tracks per artist to avoid huge lists
                        max_tracks_per_artist = 50
                        if len(tracks) > max_tracks_per_artist:
                            tracks = random.sample(tracks, max_tracks_per_artist)
                            log_debug(f"Limited tracks from '{artist_name_similar}' to {max_tracks_per_artist}")
                        
                        added_count = 0
                        for track in tracks:
                            track_id = getattr(track, 'ratingKey', None) or id(track)
                            if track_id not in seen_tracks:
                                similar_tracks.append(track)
                                seen_tracks.add(track_id)
                                added_count += 1
                        log_info(f"✅ Added {added_count} tracks from similar artist '{artist_name_similar}' (via search)")
                    else:
                        log_debug(f"No tracks found for similar artist '{artist_name_similar}'")
                except Exception as e:
                    log_warning(f"⚠️  Error getting tracks for '{artist_name_similar}': {e}")
        except Exception as e:
            artist_name = artist_name_similar if 'artist_name_similar' in locals() else 'unknown'
            log_warning(f"⚠️  Error processing similar artist '{artist_name}': {e}")
            import traceback
            log_debug(traceback.format_exc())
    
    log_info(f"✅ Found {len(similar_tracks)} tracks from similar artists")
    return similar_tracks

# Find similar tracks using a liked track
def find_similar_tracks_via_track(music_library, exclude_artists=None, fallback_to_genre=True, liked_track=None):
    """Find tracks similar to a liked track using Plex's similar tracks feature.
    
    Args:
        music_library: Plex music library
        exclude_artists: Set of artist names to exclude
        fallback_to_genre: Whether to fall back to genre search if no similar tracks found
        liked_track: Optional specific track to use. If None, gets a random liked track.
    """
    if exclude_artists is None:
        exclude_artists = set()
    
    similar_tracks = []
    seen_tracks = set()
    
    # Use provided track - if None, this is an error (should always be provided)
    if liked_track is None:
        log_error(f"❌ No track provided to find_similar_tracks_via_track. Cannot proceed.")
        return []
    
    log_debug(f"🔍 find_similar_tracks_via_track: Extracting track info...")
    track_artist = get_artist_name(liked_track)
    track_title = getattr(liked_track, 'title', 'Unknown')
    log_info(f"🎵 Finding sonically similar tracks for: '{track_title}' by {track_artist if track_artist else 'Unknown'}")
    log_debug(f"🔍 find_similar_tracks_via_track: Track info extracted, calling get_similar_tracks...")
    
    # For song-based playlists, only use sonicallySimilar() - skip slow fallbacks
    similar_tracks_list = get_similar_tracks(music_library, liked_track, use_fallbacks=False)
    log_debug(f"🔍 find_similar_tracks_via_track: get_similar_tracks returned, processing results...")
    
    log_info(f"📊 Plex API returned {len(similar_tracks_list)} similar tracks")
    
    # Filter out tracks from excluded artists
    for track in similar_tracks_list:
        track_id = getattr(track, 'ratingKey', None) or id(track)
        if track_id not in seen_tracks:
            artist = get_artist_name(track)
            if artist not in exclude_artists:
                similar_tracks.append(track)
                seen_tracks.add(track_id)
            else:
                log_debug(f"Excluded track from '{artist}' (in exclude list)")
    
    log_info(f"📊 After filtering excluded artists: {len(similar_tracks)} tracks remaining")
    
    if not similar_tracks:
        log_warning(f"⚠️  No similar tracks found for '{track_title}'.")
        if fallback_to_genre:
            log_info(f"🔄 Falling back to genre-based search...")
            # Get genres from the liked track and search by genre (limit to first 5 genres)
            track_genres = get_track_genres(liked_track)
            if track_genres:
                genre_list = list(track_genres)[:5]  # Limit to first 5 genres
                if len(track_genres) > 5:
                    log_info(f"📊 Limiting genre fallback to first 5 genres (out of {len(track_genres)} total)")
                
                target_tracks = SONGS_PER_PLAYLIST * 3  # Stop if we have enough
                for genre in genre_list:
                    # Early stopping if we have enough tracks
                    if len(similar_tracks) >= target_tracks:
                        log_info(f"✅ Found enough tracks ({len(similar_tracks)}), stopping genre fallback early")
                        break
                    
                    try:
                        # Reduce limit for faster searches
                        genre_tracks = music_library.search(genre=genre, libtype="track", limit=2000)
                        log_debug(f"Found {len(genre_tracks)} tracks for genre '{genre}'")
                        
                        for track in genre_tracks:
                            track_id = getattr(track, 'ratingKey', None) or id(track)
                            if track_id not in seen_tracks:
                                artist = get_artist_name(track)
                                if artist not in exclude_artists:
                                    similar_tracks.append(track)
                                    seen_tracks.add(track_id)
                            
                            # Early stopping check
                            if len(similar_tracks) >= target_tracks:
                                break
                    except Exception as e:
                        log_warning(f"⚠️  Error searching genre '{genre}': {e}")
                        # Continue with next genre
                        continue
                log_info(f"✅ Found {len(similar_tracks)} tracks via genre fallback")
        return similar_tracks
    
    log_info(f"✅ Found {len(similar_tracks)} similar tracks (after filtering excluded artists)")
    return similar_tracks

# Find similar tracks based on similarity attributes
def find_similar_tracks(music_library, similarity_data, method, exclude_artists=None, artist_name=None):
    """Find tracks similar to the given attributes.
    similarity_data can be either:
    - A set of attributes (for single method)
    - A tuple of (all_attrs, genre_attrs, similar_artists_list, similar_tracks_list) for combined method)
    - "similar_artists_method" marker for similar_artists method
    - "similar_tracks_method" marker for similar_tracks method
    """
    if exclude_artists is None:
        exclude_artists = set()
    
    similar_tracks = []
    seen_tracks = set()
    
    log_info(f"🔍 Finding similar tracks using {method} method...")
    
    # Handle combined method vs single method
    if method == "combined":
        all_attrs, genre_attrs, similar_artists_list, similar_tracks_list = similarity_data
    else:
        all_attrs = similarity_data
        genre_attrs = all_attrs if method == "genre" else set()
    
    # Search for tracks matching genres (most efficient)
    # Limit to first 3-4 genres to avoid long waits, and stop early if we have enough tracks
    if genre_attrs:
        # Limit to fewer genres for faster execution
        max_genres_to_search = 4
        target_tracks = SONGS_PER_PLAYLIST * 3  # Stop if we have 3x the playlist size
        
        genre_list = list(genre_attrs)[:max_genres_to_search]
        if len(genre_attrs) > max_genres_to_search:
            log_info(f"📊 Limiting genre search to first {max_genres_to_search} genres (out of {len(genre_attrs)} total) for faster execution")
        
        for attr in tqdm(genre_list, desc="Searching genres", unit="genre", disable=(LOG_LEVEL in ["WARNING", "ERROR"])):
            # Early stopping if we already have enough tracks
            if len(similar_tracks) >= target_tracks:
                log_info(f"✅ Found enough tracks ({len(similar_tracks)}), stopping genre search early")
                break
            
            try:
                # Reduce limit further for faster searches
                tracks = music_library.search(genre=attr, libtype="track", limit=2000)  # Reduced from 5000 for speed
                log_debug(f"Found {len(tracks)} tracks for genre '{attr}'")
                
                for track in tracks:
                    track_id = getattr(track, 'ratingKey', None) or id(track)
                    if track_id not in seen_tracks:
                        artist = get_artist_name(track)
                        if artist not in exclude_artists:
                            # For combined method, accept if genre matches OR style matches
                            if method == "combined":
                                track_styles = get_track_style(track)
                                # Accept if genre matches, or if style also matches
                                if True:  # Genre already matches
                                    similar_tracks.append(track)
                                    seen_tracks.add(track_id)
                            else:
                                similar_tracks.append(track)
                                seen_tracks.add(track_id)
                    
                    # Early stopping check inside loop too
                    if len(similar_tracks) >= target_tracks:
                        break
                        
            except Exception as e:
                log_warning(f"⚠️  Error searching for genre '{attr}': {e}")
                # Continue with next genre instead of failing completely
                continue
    
    # For combined method, also try to get similar artists and similar tracks if available
    # But only if we don't already have enough tracks from genres
    target_tracks = SONGS_PER_PLAYLIST * 3
    if method == "combined":
        if len(similar_tracks) < target_tracks and artist_name:
            log_info(f"📊 Also searching for similar artists...")
            similar_artist_tracks = find_similar_tracks_via_artists(music_library, artist_name, exclude_artists)
            for track in similar_artist_tracks:
                track_id = getattr(track, 'ratingKey', None) or id(track)
                if track_id not in seen_tracks:
                    similar_tracks.append(track)
                    seen_tracks.add(track_id)
                    if len(similar_tracks) >= target_tracks:
                        break
        else:
            log_info(f"📊 Skipping similar artists search (already have {len(similar_tracks)} tracks)")
        
        if len(similar_tracks) < target_tracks:
            log_info(f"📊 Also searching for similar tracks from a liked song...")
            similar_track_tracks = find_similar_tracks_via_track(music_library, exclude_artists)
            for track in similar_track_tracks:
                track_id = getattr(track, 'ratingKey', None) or id(track)
                if track_id not in seen_tracks:
                    similar_tracks.append(track)
                    seen_tracks.add(track_id)
                    if len(similar_tracks) >= target_tracks:
                        break
        else:
            log_info(f"📊 Skipping similar tracks search (already have {len(similar_tracks)} tracks)")
    
    log_info(f"✅ Found {len(similar_tracks)} similar tracks")
    return similar_tracks

# Read the log file
def read_log():
    log_debug("Reading log...")
    if not os.path.exists(LOG_FILE):
        log_debug(f"{LOG_FILE} does not exist. Starting with an empty log.")
        return []
    try:
        with open(LOG_FILE, "r") as file:
            log_entries = [line.strip() for line in file.readlines()]
            log_debug(f"Log loaded: {log_entries}")
            return log_entries
    except Exception as e:
        log_error(f"Error reading log: {e}")
        return []

# Write to the log file
def write_log(log_entries):
    log_debug("Writing to log...")
    try:
        with open(LOG_FILE, "w") as file:
            file.writelines(f"{entry}\n" for entry in log_entries)
        log_debug("Log updated successfully.")
    except Exception as e:
        log_error(f"Error writing to log: {e}")

# Generate playlists themed around liked artists
def generate_liked_artists_playlists():
    log_info("🔌 Connecting to Plex server...")
    try:
        music_library = plex.library.section("Music")
        log_info("✅ Successfully connected to Plex server and accessed 'Music' library.")
    except Exception as e:
        log_error(f"❌ Error connecting to Plex server or accessing library: {e}")
        return

    # Load liked artists and track keys from cache
    log_info("🎵 Loading liked artists and tracks from cache...")
    cache_result = load_liked_artists_cache()
    if cache_result[0] is None:
        log_error("❌ No liked artists cache found. Run fetch-liked-artists.py to create the cache.")
        return
    
    liked_artists, cached_track_count, cache_timestamp, artist_name_map, liked_track_keys, artist_id_map = cache_result
    log_info(f"✅ Loaded {len(liked_artists):,} liked artists from cache")
    if artist_id_map:
        log_info(f"✅ Loaded {len(artist_id_map):,} artist IDs for accurate matching")
    if liked_track_keys:
        log_info(f"✅ Loaded {len(liked_track_keys):,} liked track keys from cache (will use for fast track selection)")

    # Note: We use Spotify posters automatically, so no need to check for local images
    available_images = []
    used_images = set()

    # Read the log to avoid previously used artists
    log_entries = read_log()

    # Filter out previously used artists
    available_artists = {
        artist: artist_name_map.get(artist, artist)
        for artist in liked_artists
        if artist not in log_entries
    }

    if not available_artists:
        log_info("All liked artists have been used recently. Resetting the log.")
        log_entries = []
        available_artists = {artist: artist_name_map.get(artist, artist) for artist in liked_artists}

    # Generate playlists - each playlist is either artist-based or song-based
    playlists_created = 0
    
    for i in range(PLAYLIST_COUNT):
        playlist_start_time = time.time()
        playlist_songs = []
        
        # Determine if this playlist should be artist-based or song-based
        if SIMILARITY_METHOD_CONFIG == "random":
            selected_method = random.choice(AVAILABLE_SIMILARITY_METHODS)
            log_info(f"🎲 Randomly selected: {selected_method} method")
        else:
            # Validate the configured method
            if SIMILARITY_METHOD_CONFIG in AVAILABLE_SIMILARITY_METHODS:
                selected_method = SIMILARITY_METHOD_CONFIG
                log_info(f"📌 Using configured method: {selected_method}")
            else:
                log_warning(f"⚠️  Invalid similarity method '{SIMILARITY_METHOD_CONFIG}'. Using random selection.")
                selected_method = random.choice(AVAILABLE_SIMILARITY_METHODS)
                log_info(f"🎲 Randomly selected: {selected_method} method")
        
        try:
            if selected_method == "similar_artists":
                # Artist-based playlist: use similar artists
                if not available_artists:
                    log_warning(f"⚠️  No available artists. Skipping playlist {i + 1}.")
                    continue
                
                # Select a random artist
                artist_normalized, artist_original = random.choice(list(available_artists.items()))
                # Get artist ID if available for more accurate matching
                artist_id = artist_id_map.get(artist_normalized) if artist_id_map else None
                log_info(f"\n🎵 Starting generation for Playlist {i + 1} (Artist: {artist_original})...")
                if artist_id:
                    log_debug(f"🎯 Using artist ID {artist_id} for accurate matching")
                
                # Get tracks by this artist (for the playlist)
                log_info(f"🔍 Fetching tracks by {artist_original}...")
                artist_tracks = get_tracks_by_artist(music_library, artist_original, artist_id)
                
                if not artist_tracks:
                    log_warning(f"⚠️  No tracks found for artist '{artist_original}'. Skipping playlist {i + 1}.")
                    continue
                
                log_info(f"✅ Found {len(artist_tracks)} tracks by {artist_original}")
                
                # Find similar artists and get their tracks
                exclude_artists = {artist_normalized}
                log_info(f"🔍 Finding similar artists for '{artist_original}'...")
                similar_tracks = find_similar_tracks_via_artists(music_library, artist_original, exclude_artists, artist_id)
                
                # Use artist name for poster
                poster_artist_name = artist_original
                
            elif selected_method == "similar_tracks":
                # Song-based playlist: use similar tracks for a single liked song
                log_info(f"\n🎵 Starting generation for Playlist {i + 1} (Song-based)...")
                log_debug(f"🔍 Step 1: Getting a random liked track...")
                
                # Get a random liked track (using cached keys for speed)
                liked_track = get_random_liked_track(music_library, liked_track_keys)
                log_debug(f"🔍 Step 1 complete: get_random_liked_track returned: {liked_track is not None}")
                
                if not liked_track:
                    log_warning(f"⚠️  No liked track found. Skipping playlist {i + 1}.")
                    continue
                
                log_debug(f"🔍 Step 2: Extracting track info...")
                track_artist = get_artist_name_original(liked_track)
                track_title = getattr(liked_track, 'title', 'Unknown')
                log_info(f"🎵 Base song selected: '{track_title}' by {track_artist if track_artist else 'Unknown'}")
                log_debug(f"🔍 Step 2 complete: Track info extracted")
                
                # Find similar tracks for this specific song (don't exclude the artist - we want variety)
                log_info(f"🔍 Finding sonically similar tracks for '{track_title}'...")
                log_debug(f"🔍 Step 3: Calling find_similar_tracks_via_track...")
                similar_tracks = find_similar_tracks_via_track(music_library, exclude_artists=None, fallback_to_genre=False, liked_track=liked_track)
                log_debug(f"🔍 Step 3 complete: find_similar_tracks_via_track returned {len(similar_tracks)} tracks")
                
                # Start with the base song itself, then add similar tracks
                artist_tracks = [liked_track]  # Include the base song
                
                # Use track artist for poster
                poster_artist_name = track_artist if track_artist else "Unknown"
                liked_track_for_poster = liked_track
                
                # If no similar tracks found, log a warning
                if not similar_tracks:
                    log_warning(f"⚠️  No similar tracks found for '{track_title}'. Playlist will only contain the base song.")
            
            # Handle fallback for similar_artists if no similar artists found
            if selected_method == "similar_artists" and not similar_tracks:
                log_warning(f"⚠️  No similar artists found. Using more tracks from '{artist_original}'.")
                similar_tracks = []
            
            # Now combine artist tracks with similar tracks
            # For song-based playlists, use base song + similar tracks
            # For artist-based playlists, use artist tracks + similar tracks
            if selected_method == "similar_tracks":
                # Song-based: combine base song with similar tracks
                all_available_tracks = list(artist_tracks) + similar_tracks
                log_info(f"📊 Available tracks: {len(artist_tracks)} base song(s), {len(similar_tracks)} sonically similar tracks")
                
                # Select tracks: include base song, fill rest with similar tracks
                playlist_songs = list(artist_tracks)  # Start with base song(s)
                remaining_slots = SONGS_PER_PLAYLIST - len(playlist_songs)
                
                if similar_tracks and remaining_slots > 0:
                    # Remove base song from similar tracks if it's in there
                    available_similar = [t for t in similar_tracks if t not in playlist_songs]
                    if available_similar:
                        similar_count = min(remaining_slots, len(available_similar))
                        selected_similar = random.sample(available_similar, similar_count)
                        playlist_songs.extend(selected_similar)
                        log_info(f"✅ Selected {len(selected_similar)} sonically similar tracks")
                    else:
                        log_warning(f"⚠️  No additional similar tracks available (base song may be in similar tracks list)")
                else:
                    log_warning(f"⚠️  Not enough tracks to fill playlist (have {len(playlist_songs)}, need {SONGS_PER_PLAYLIST})")
            else:
                # Artist-based: use existing logic
                all_available_tracks = list(artist_tracks) + similar_tracks
                log_info(f"📊 Available tracks: {len(artist_tracks)} from main artist, {len(similar_tracks)} from similar artists/other sources")
                
                # Select tracks for playlist (prefer artist's tracks but include similar ones)
                if similar_tracks:
                    # Use 30-50% from the artist, rest from similar tracks
                    artist_percentage = random.uniform(0.3, 0.5)
                    artist_count = int(SONGS_PER_PLAYLIST * artist_percentage)
                    artist_count = min(artist_count, len(artist_tracks))
                    log_info(f"📊 Selecting {artist_count} tracks from main artist ({artist_percentage*100:.0f}%), rest from similar artists")
                else:
                    # If no similar tracks, use more from the artist (up to MAX_ARTIST_PERCENTAGE)
                    max_artist_count = int(SONGS_PER_PLAYLIST * MAX_ARTIST_PERCENTAGE)
                    artist_count = min(max_artist_count, len(artist_tracks), SONGS_PER_PLAYLIST)
                    log_info(f"📊 No similar tracks found, using up to {MAX_ARTIST_PERCENTAGE*100:.0f}% from artist ({artist_count} tracks)")
                
                selected_artist_tracks = random.sample(artist_tracks, artist_count) if artist_tracks else []
                remaining_slots = SONGS_PER_PLAYLIST - len(selected_artist_tracks)
                
                log_info(f"📊 Selected {len(selected_artist_tracks)} tracks from main artist, {remaining_slots} slots remaining for similar tracks")
                
                available_similar = [t for t in similar_tracks if t not in selected_artist_tracks]
                if available_similar and remaining_slots > 0:
                    similar_count = min(remaining_slots, len(available_similar))
                    selected_similar = random.sample(available_similar, similar_count)
                    playlist_songs = selected_artist_tracks + selected_similar
                    
                    # Show which artists are in the final selection
                    final_artists = {}
                    for track in playlist_songs:
                        track_artist = get_artist_name_original(track)
                        if track_artist:
                            final_artists[track_artist] = final_artists.get(track_artist, 0) + 1
                    
                    log_info(f"✅ Selected {len(selected_similar)} tracks from similar artists/other sources")
                    log_info(f"📊 Final playlist artists: {len(final_artists)} unique artists")
                    if LOG_LEVEL == "DEBUG":
                        for artist, count in sorted(final_artists.items(), key=lambda x: x[1], reverse=True):
                            log_debug(f"  - {artist}: {count} tracks")
                elif not similar_tracks and remaining_slots > 0:
                    # If no similar tracks but we need more, use more artist tracks (up to limit)
                    max_total_artist = int(SONGS_PER_PLAYLIST * MAX_ARTIST_PERCENTAGE)
                    if len(selected_artist_tracks) < max_total_artist and len(artist_tracks) > len(selected_artist_tracks):
                        additional_needed = min(remaining_slots, max_total_artist - len(selected_artist_tracks), len(artist_tracks) - len(selected_artist_tracks))
                        if additional_needed > 0:
                            available_artist = [t for t in artist_tracks if t not in selected_artist_tracks]
                            if available_artist:
                                additional = random.sample(available_artist, min(additional_needed, len(available_artist)))
                                selected_artist_tracks.extend(additional)
                                log_info(f"📊 Added {len(additional)} more tracks from artist to fill playlist")
                    playlist_songs = selected_artist_tracks
                else:
                    playlist_songs = selected_artist_tracks
            
            # Get the main artist name for logging (different for artist vs song based)
            main_artist_name = artist_original if selected_method == "similar_artists" else (track_artist if 'track_artist' in locals() else "Unknown")
            if selected_method == "similar_tracks":
                log_info(f"✅ Selected {len(playlist_songs)} tracks total ({len(artist_tracks)} base song(s), {len(playlist_songs) - len(artist_tracks)} similar tracks)")
            else:
                log_info(f"✅ Selected {len(selected_artist_tracks)} tracks from main artist and {len(playlist_songs) - len(selected_artist_tracks)} similar tracks")
            
            # Balance artist representation (use target playlist size for calculation)
            playlist_songs = balance_artist_representation(playlist_songs, all_available_tracks, MAX_ARTIST_PERCENTAGE, SONGS_PER_PLAYLIST)
            
            # Apply quality filters
            log_info(f"🔄 Applying quality filters for Playlist {i + 1}...")
            playlist_songs = apply_quality_filters(
                playlist_songs,
                all_available_tracks,
                min_duration_seconds=MIN_SONG_DURATION_SECONDS,
                max_songs_per_album=MAX_SONGS_PER_ALBUM,
                prevent_consecutive=PREVENT_CONSECUTIVE_ARTISTS,
                mood_grouping=MOOD_GROUPING_ENABLED
            )
            
            # Poster artist name is already set above for both methods
            
            # Download poster from Spotify
            poster_image = None
            log_info(f"📥 Downloading poster from Spotify for '{poster_artist_name}'...")
            poster_image = download_spotify_poster(poster_artist_name)
            
            # Note: We rely on Spotify posters only, no local fallback needed
            
            # Create or update the playlist
            playlist_name = f"Artist Mix ({i + 1})"
            existing_playlist = plex.playlist(playlist_name) if playlist_name in [pl.title for pl in plex.playlists()] else None
            
            if existing_playlist:
                log_info(f"🔄 Updating existing playlist: {playlist_name}")
                existing_playlist.removeItems(existing_playlist.items())
                existing_playlist.addItems(playlist_songs)
                
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Convert similarity method to plain English
                if selected_method == "similar_artists":
                    similarity_info = "Used similar artists"
                    summary_text = f"Artist: {artist_original}\nUpdated on: {timestamp}\n{similarity_info}"
                elif selected_method == "similar_tracks":
                    similarity_info = "Used similar tracks from a liked song"
                    track_info = f"Based on: {track_title} by {track_artist}" if 'track_title' in locals() and 'track_artist' in locals() else "Based on a liked song"
                    summary_text = f"{track_info}\nUpdated on: {timestamp}\n{similarity_info}"
                else:
                    similarity_info = f"Used similar songs (method: {selected_method})"
                    summary_text = f"Updated on: {timestamp}\n{similarity_info}"
                
                existing_playlist.editSummary(summary_text)
                
                if poster_image:
                    upload_playlist_poster(existing_playlist, poster_image)
                playlist = existing_playlist
            else:
                log_info(f"✨ Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)
                
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Convert similarity method to plain English
                if selected_method == "similar_artists":
                    similarity_info = "Used similar artists"
                    summary_text = f"Artist: {artist_original}\nCreated on: {timestamp}\n{similarity_info}"
                elif selected_method == "similar_tracks":
                    similarity_info = "Used similar tracks from a liked song"
                    track_info = f"Based on: {track_title} by {track_artist}" if 'track_title' in locals() and 'track_artist' in locals() else "Based on a liked song"
                    summary_text = f"{track_info}\nCreated on: {timestamp}\n{similarity_info}"
                else:
                    similarity_info = f"Used similar songs (method: {selected_method})"
                    summary_text = f"Created on: {timestamp}\n{similarity_info}"
                
                playlist.editSummary(summary_text)
                
                if poster_image:
                    upload_playlist_poster(playlist, poster_image)
            
            log_info(f"✅ Playlist '{playlist_name}' successfully created/updated with {len(playlist_songs)} songs.")
            
            # Add the artist to the log (only for artist-based playlists)
            if selected_method == "similar_artists":
                log_entries.append(artist_normalized)
            
            # Keep the log size to a maximum
            if len(log_entries) > MAX_LOG_ENTRIES:
                log_entries = log_entries[-MAX_LOG_ENTRIES:]
        
        except Exception as e:
            log_error(f"❌ Error during playlist generation for Playlist {i + 1}: {e}")
            import traceback
            traceback.print_exc()
        
        playlist_end_time = time.time()
        elapsed_time = playlist_end_time - playlist_start_time
        if playlist_songs and len(playlist_songs) > 0:
            log_info(f"⏱️  Generation time for Playlist {i + 1}: {format_duration(elapsed_time)}")
        else:
            log_info(f"⏱️  Time taken for Playlist {i + 1} (failed): {format_duration(elapsed_time)}")
        log_info("---------------------------------------------")
    
    # Write the updated log back to the file
    write_log(log_entries)

# Run the script
if __name__ == "__main__":
    script_start_time = time.time()
    log_info("🚀 Starting the Liked Artists playlist generation process...")
    generate_liked_artists_playlists()
    script_end_time = time.time()
    total_elapsed_time = script_end_time - script_start_time
    log_info("\n✅ Liked Artists playlists updated successfully.")
    log_info(f"⏱️  Total script execution time: {format_duration(total_elapsed_time)}")


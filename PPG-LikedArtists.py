
from plexapi.server import PlexServer
import random
import json
import os
import time
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

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
# Available similarity methods (will be randomly selected per playlist)
AVAILABLE_SIMILARITY_METHODS = ["genre", "similar_artists", "similar_tracks", "combined"]
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

# Upload poster to a playlist
def upload_playlist_poster(playlist, image_path):
    """Upload a poster image to a Plex playlist."""
    try:
        if image_path and os.path.exists(image_path):
            playlist.uploadPoster(filepath=image_path)
            log_info(f"✅ Uploaded poster: {os.path.basename(image_path)}")
        else:
            log_warning(f"⚠️  Poster file not found: {image_path}")
    except Exception as e:
        log_warning(f"⚠️  Could not upload poster: {e}")

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

# Get track mood
def get_track_mood(track):
    """Get the mood from a track."""
    try:
        if hasattr(track, 'mood') and track.mood:
            if isinstance(track.mood, list):
                return track.mood[0] if track.mood else None
            return track.mood
        elif hasattr(track, 'moods') and track.moods:
            if isinstance(track.moods, list):
                return track.moods[0] if track.moods else None
            return track.moods
        return None
    except Exception as e:
        log_debug(f"Error getting mood for track '{track.title}': {e}")
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
    """Group and sort tracks by mood for better flow."""
    log_debug(f"🎵 Starting mood grouping for {len(playlist_songs)} tracks")
    
    tracks_with_mood = []
    tracks_without_mood = []
    mood_counts = {}
    
    for track in playlist_songs:
        mood = get_track_mood(track)
        if mood:
            tracks_with_mood.append((track, mood))
            mood_counts[mood] = mood_counts.get(mood, 0) + 1
        else:
            tracks_without_mood.append(track)
    
    log_debug(f"  📊 Mood data found: {len(tracks_with_mood)} tracks have mood, {len(tracks_without_mood)} tracks missing mood")
    
    if not tracks_with_mood:
        log_debug(f"  ⚠️  No mood data available. Shuffling playlist randomly.")
        random.shuffle(playlist_songs)
        return playlist_songs
    
    log_debug(f"  🎭 Found {len(mood_counts)} unique moods:")
    for mood, count in sorted(mood_counts.items(), key=lambda x: x[1], reverse=True):
        log_debug(f"    - {mood}: {count} tracks")
    
    if mood_counts:
        selected_mood = random.choice(list(mood_counts.keys()))
        log_info(f"  🎯 Selected mood for grouping: '{selected_mood}' ({mood_counts[selected_mood]} tracks)")
        
        tracks_matching_mood = [track for track, mood in tracks_with_mood if mood == selected_mood]
        tracks_other_moods = [track for track, mood in tracks_with_mood if mood != selected_mood]
        
        grouped = tracks_matching_mood.copy()
        random.shuffle(grouped)
        
        random.shuffle(tracks_other_moods)
        grouped.extend(tracks_other_moods)
        
        if tracks_without_mood:
            log_debug(f"  🔀 Interleaving {len(tracks_without_mood)} tracks without mood data randomly")
            random.shuffle(tracks_without_mood)
            for track in tracks_without_mood:
                if len(grouped) > len(tracks_matching_mood):
                    pos = random.randint(len(tracks_matching_mood), len(grouped))
                    grouped.insert(pos, track)
                else:
                    grouped.append(track)
        
        log_info(f"✅ Mood grouping complete")
        return grouped
    else:
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
    
    if mood_grouping and len(playlist_songs) > 1:
        log_info(f"🔄 Grouping songs by mood...")
        playlist_songs = group_by_mood(playlist_songs)
    
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

# Balance artist representation in playlist to max percentage per artist
def balance_artist_representation(playlist_songs, all_available_songs, max_percentage=0.3):
    """Ensure no single artist represents more than max_percentage of the playlist."""
    total_songs = len(playlist_songs)
    max_songs_per_artist = int(total_songs * max_percentage)
    
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
    
    songs_needed = total_songs - len(balanced_playlist)
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
    """Load liked artists and track count from cache file."""
    log_debug("🔍 Checking liked artists cache...")
    if not os.path.exists(LIKED_ARTISTS_CACHE_FILE):
        log_debug("❌ No liked artists cache found.")
        return None, 0, None
    
    try:
        with open(LIKED_ARTISTS_CACHE_FILE, "r", encoding='utf-8') as file:
            cache_data = json.load(file)
            raw_artists = cache_data.get("liked_artists", [])
            liked_artists = set()
            artist_name_map = {}  # normalized -> original
            for artist in raw_artists:
                normalized = normalize_artist_name(artist)
                if normalized:
                    liked_artists.add(normalized)
                    artist_name_map[normalized] = artist
            cached_track_count = cache_data.get("liked_track_count", 0)
            cache_timestamp = cache_data.get("cache_timestamp", None)
            
            if cache_timestamp:
                from datetime import datetime
                cache_date = datetime.fromisoformat(cache_timestamp)
                days_old = (datetime.now() - cache_date).days
                log_info(f"✅ Loaded {len(liked_artists):,} liked artists from cache (from {cached_track_count:,} tracks)")
                log_debug(f"📅 Cache is {days_old} days old")
                return liked_artists, cached_track_count, cache_timestamp, artist_name_map
            else:
                log_info(f"✅ Loaded {len(liked_artists):,} liked artists from cache (from {cached_track_count:,} tracks)")
                log_warning("⚠️ Cache has no timestamp - will refresh to add timestamp")
                return liked_artists, cached_track_count, None, artist_name_map
    except Exception as e:
        log_error(f"❌ Error loading liked artists cache: {e}")
        return None, 0, None, {}

# Get artist object by name
def get_artist_object(music_library, artist_name):
    """Get the artist object from Plex by name."""
    try:
        # Try searching for the artist
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

# Get similar artists from Plex API
def get_similar_artists(music_library, artist_name):
    """Get similar artists using Plex's relatedItems API."""
    try:
        artist_obj = get_artist_object(music_library, artist_name)
        if not artist_obj:
            log_debug(f"Could not find artist object for '{artist_name}'")
            return []
        
        # Try to get related items (similar artists)
        similar_artists = []
        try:
            # Check if artist has relatedItems method
            if hasattr(artist_obj, 'relatedItems'):
                related = artist_obj.relatedItems()
                if related:
                    for item in related:
                        if hasattr(item, 'type') and item.type == 'artist':
                            similar_artists.append(item)
        except Exception as e:
            log_debug(f"Error accessing relatedItems: {e}")
        
        # Try alternative method: check for similar attribute
        if not similar_artists:
            try:
                if hasattr(artist_obj, 'similar'):
                    similar = artist_obj.similar()
                    if similar:
                        similar_artists = similar
            except Exception as e:
                log_debug(f"Error accessing similar: {e}")
        
        # Try alternative: use the API directly
        if not similar_artists:
            try:
                # Try to access via API endpoint for related items
                url = f"/library/metadata/{artist_obj.ratingKey}/related"
                response = artist_obj._server.query(url)
                
                # Parse XML response
                if response and hasattr(response, 'attrib'):
                    # Try to find related artists in the response
                    from xml.etree import ElementTree as ET
                    if isinstance(response, ET.Element):
                        for item in response.findall('.//Directory'):
                            if item.get('type') == 'artist':
                                # Create artist object from the XML
                                artist_key = item.get('key')
                                if artist_key:
                                    try:
                                        related_artist = music_library.fetchItem(artist_key)
                                        if related_artist:
                                            similar_artists.append(related_artist)
                                    except:
                                        pass
            except Exception as e:
                log_debug(f"Error accessing related via API: {e}")
        
        return similar_artists
    except Exception as e:
        log_debug(f"Error getting similar artists for '{artist_name}': {e}")
        return []

# Get a random liked track
def get_random_liked_track(music_library):
    """Get a random track from liked tracks (1+ star rating)."""
    try:
        # Try different approaches to find liked tracks
        liked_tracks = []
        
        # Method 1: Try searchTracks with userRating__gte
        try:
            liked_tracks = music_library.searchTracks(userRating__gte=1)
        except Exception as e1:
            log_debug(f"Method 1 failed: {e1}")
        
        # Method 2: Try search with different filter syntax
        if not liked_tracks:
            try:
                liked_tracks = music_library.search(libtype="track", filters={'userRating>=': 1}, limit=None)
            except Exception as e2:
                log_debug(f"Method 2 failed: {e2}")
        
        # Method 3: Try search with userRating__gte in filters
        if not liked_tracks:
            try:
                liked_tracks = music_library.search(libtype="track", filters={'userRating__gte': 1}, limit=None)
            except Exception as e3:
                log_debug(f"Method 3 failed: {e3}")
        
        if liked_tracks:
            return random.choice(liked_tracks)
        else:
            log_warning("⚠️  No liked tracks found")
            return None
    except Exception as e:
        log_error(f"❌ Error getting random liked track: {e}")
        return None

# Get similar tracks from Plex API
def get_similar_tracks(music_library, track):
    """Get similar tracks using Plex's similar tracks feature."""
    try:
        similar_tracks = []
        
        # Try to get related items (similar tracks)
        try:
            # Check if track has relatedItems method
            if hasattr(track, 'relatedItems'):
                related = track.relatedItems()
                if related:
                    for item in related:
                        if hasattr(item, 'type') and item.type == 'track':
                            similar_tracks.append(item)
        except Exception as e:
            log_debug(f"Error accessing relatedItems: {e}")
        
        # Try alternative method: check for similar attribute
        if not similar_tracks:
            try:
                if hasattr(track, 'similar'):
                    similar = track.similar()
                    if similar:
                        similar_tracks = similar
            except Exception as e:
                log_debug(f"Error accessing similar: {e}")
        
        # Try alternative: use the API directly
        if not similar_tracks:
            try:
                # Try to access via API endpoint for related items
                url = f"/library/metadata/{track.ratingKey}/related"
                response = track._server.query(url)
                
                # Parse XML response
                if response and hasattr(response, 'attrib'):
                    from xml.etree import ElementTree as ET
                    if isinstance(response, ET.Element):
                        for item in response.findall('.//Track'):
                            track_key = item.get('key')
                            if track_key:
                                try:
                                    related_track = music_library.fetchItem(track_key)
                                    if related_track:
                                        similar_tracks.append(related_track)
                                except:
                                    pass
            except Exception as e:
                log_debug(f"Error accessing related via API: {e}")
        
        return similar_tracks
    except Exception as e:
        log_debug(f"Error getting similar tracks: {e}")
        return []

# Get tracks by artist name
def get_tracks_by_artist(music_library, artist_name):
    """Get all tracks by a specific artist."""
    try:
        # Try searching by artist name
        tracks = music_library.searchTracks(artist=artist_name, limit=None)
        if tracks:
            return tracks
        
        # Fallback: search by grandparentTitle
        all_tracks = music_library.searchTracks(limit=None)
        matching_tracks = []
        for track in all_tracks:
            track_artist = get_artist_name_original(track)
            if track_artist and normalize_artist_name(track_artist) == normalize_artist_name(artist_name):
                matching_tracks.append(track)
        return matching_tracks
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
def find_similar_tracks_via_artists(music_library, artist_name, exclude_artists=None):
    """Find tracks from similar artists using Plex's similar artists feature."""
    if exclude_artists is None:
        exclude_artists = set()
    
    similar_tracks = []
    seen_tracks = set()
    
    log_info(f"🔍 Finding similar artists for '{artist_name}'...")
    similar_artists = get_similar_artists(music_library, artist_name)
    
    if not similar_artists:
        log_warning(f"⚠️  No similar artists found for '{artist_name}'. Falling back to genre-based search.")
        return []
    
    log_info(f"✅ Found {len(similar_artists)} similar artists")
    
    # Get tracks from each similar artist
    for similar_artist in tqdm(similar_artists, desc="Getting tracks from similar artists", unit="artist", disable=(LOG_LEVEL in ["WARNING", "ERROR"])):
        try:
            artist_name_similar = similar_artist.title if hasattr(similar_artist, 'title') else str(similar_artist)
            artist_normalized = normalize_artist_name(artist_name_similar)
            
            if artist_normalized and artist_normalized not in exclude_artists:
                # Get tracks by this similar artist
                tracks = get_tracks_by_artist(music_library, artist_name_similar)
                for track in tracks:
                    track_id = getattr(track, 'ratingKey', None) or id(track)
                    if track_id not in seen_tracks:
                        similar_tracks.append(track)
                        seen_tracks.add(track_id)
        except Exception as e:
            log_debug(f"Error getting tracks from similar artist: {e}")
    
    log_info(f"✅ Found {len(similar_tracks)} tracks from similar artists")
    return similar_tracks

# Find similar tracks using a liked track
def find_similar_tracks_via_track(music_library, exclude_artists=None):
    """Find tracks similar to a random liked track using Plex's similar tracks feature."""
    if exclude_artists is None:
        exclude_artists = set()
    
    similar_tracks = []
    seen_tracks = set()
    
    log_info(f"🔍 Getting a random liked track...")
    liked_track = get_random_liked_track(music_library)
    
    if not liked_track:
        log_warning(f"⚠️  No liked track found. Cannot use similar_tracks method.")
        return []
    
    track_artist = get_artist_name(liked_track)
    track_title = getattr(liked_track, 'title', 'Unknown')
    log_info(f"✅ Selected liked track: '{track_title}' by {track_artist if track_artist else 'Unknown'}")
    
    log_info(f"🔍 Finding similar tracks for '{track_title}'...")
    similar_tracks_list = get_similar_tracks(music_library, liked_track)
    
    if not similar_tracks_list:
        log_warning(f"⚠️  No similar tracks found for '{track_title}'. Falling back to genre-based search.")
        return []
    
    log_info(f"✅ Found {len(similar_tracks_list)} similar tracks")
    
    # Filter out tracks from excluded artists
    for track in similar_tracks_list:
        track_id = getattr(track, 'ratingKey', None) or id(track)
        if track_id not in seen_tracks:
            artist = get_artist_name(track)
            if artist not in exclude_artists:
                similar_tracks.append(track)
                seen_tracks.add(track_id)
    
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
    if genre_attrs:
        for attr in tqdm(genre_attrs, desc="Searching genres", unit="genre", disable=(LOG_LEVEL in ["WARNING", "ERROR"])):
            try:
                tracks = music_library.search(genre=attr, libtype="track", limit=None)
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
            except Exception as e:
                log_debug(f"Error searching for genre '{attr}': {e}")
    
    # For combined method, also try to get similar artists and similar tracks if available
    if method == "combined":
        if artist_name:
            log_info(f"📊 Also searching for similar artists...")
            similar_artist_tracks = find_similar_tracks_via_artists(music_library, artist_name, exclude_artists)
            for track in similar_artist_tracks:
                track_id = getattr(track, 'ratingKey', None) or id(track)
                if track_id not in seen_tracks:
                    similar_tracks.append(track)
                    seen_tracks.add(track_id)
        
        log_info(f"📊 Also searching for similar tracks from a liked song...")
        similar_track_tracks = find_similar_tracks_via_track(music_library, exclude_artists)
        for track in similar_track_tracks:
            track_id = getattr(track, 'ratingKey', None) or id(track)
            if track_id not in seen_tracks:
                similar_tracks.append(track)
                seen_tracks.add(track_id)
    
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

    # Load liked artists
    log_info("🎵 Loading liked artists from cache...")
    cache_result = load_liked_artists_cache()
    if cache_result[0] is None:
        log_error("❌ No liked artists cache found. Run fetch-liked-artists.py to create the cache.")
        return
    
    liked_artists, cached_track_count, cache_timestamp, artist_name_map = cache_result
    log_info(f"✅ Loaded {len(liked_artists):,} liked artists from cache")

    # Get available poster images
    log_debug("🖼️  Loading poster images...")
    available_images = get_available_images(PLAYLIST_POSTERS_DIR)
    used_images = set()
    
    if available_images:
        log_info(f"✅ Found {len(available_images)} poster images in '{PLAYLIST_POSTERS_DIR}'")
    else:
        log_warning(f"⚠️  No poster images found in '{PLAYLIST_POSTERS_DIR}'. Playlists will be created without posters.")

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

    # Select random artists for playlists
    selected_artists = random.sample(list(available_artists.items()), min(PLAYLIST_COUNT, len(available_artists)))

    for i, (artist_normalized, artist_original) in enumerate(selected_artists):
        playlist_start_time = time.time()
        log_info(f"\n🎵 Starting generation for Playlist {i + 1} (Artist: {artist_original})...")
        playlist_songs = []
        
        try:
            # Get tracks by this artist
            log_info(f"🔍 Fetching tracks by {artist_original}...")
            artist_tracks = get_tracks_by_artist(music_library, artist_original)
            
            if not artist_tracks:
                log_warning(f"⚠️  No tracks found for artist '{artist_original}'. Skipping playlist {i + 1}.")
                continue
            
            log_info(f"✅ Found {len(artist_tracks)} tracks by {artist_original}")
            
            # Randomly select a similarity method for this playlist
            selected_method = random.choice(AVAILABLE_SIMILARITY_METHODS)
            log_info(f"🎲 Randomly selected similarity method: {selected_method}")
            
            # Extract similarity attributes from artist's tracks
            log_info(f"🔍 Extracting similarity attributes ({selected_method}) from artist's tracks...")
            similarity_data = extract_similarity_attributes(artist_tracks, selected_method)
            
            # Handle return value (tuple for combined, set for single method, or special marker for similar_artists/similar_tracks)
            if selected_method == "similar_artists" or selected_method == "similar_tracks":
                # For these methods, we'll get similar content directly
                similarity_attributes = None  # Not used for these methods
            elif selected_method == "combined":
                similarity_attributes, genre_attrs, similar_artists_list, similar_tracks_list = similarity_data
                log_info(f"✅ Found {len(genre_attrs)} genres")
            else:
                similarity_attributes = similarity_data
            
            # Find similar tracks (excluding the original artist)
            exclude_artists = {artist_normalized}
            
            if selected_method == "similar_artists" or selected_method == "similar_tracks":
                # Use Plex's similar artists or similar tracks API
                similar_tracks = find_similar_tracks(music_library, similarity_data, selected_method, exclude_artists, artist_original)
            else:
                if not similarity_attributes:
                    log_warning(f"⚠️  No similarity attributes found for '{artist_original}'. Using artist's tracks only.")
                    playlist_songs = random.sample(artist_tracks, min(len(artist_tracks), SONGS_PER_PLAYLIST))
                    similar_tracks = []
                else:
                    log_info(f"✅ Found {len(similarity_attributes)} unique similarity attributes")
                    log_debug(f"   Attributes: {', '.join(list(similarity_attributes)[:10])}{'...' if len(similarity_attributes) > 10 else ''}")
                    
                    similar_tracks = find_similar_tracks(music_library, similarity_data, selected_method, exclude_artists, artist_original)
            
            if selected_method not in ["similar_artists", "similar_tracks"] and not similarity_attributes:
                # Already handled above, skip to quality filters
                pass
            else:
                
                # Combine artist's tracks with similar tracks
                all_available_tracks = list(artist_tracks) + similar_tracks
                
                # Select tracks for playlist (prefer artist's tracks but include similar ones)
                # Use 30-50% from the artist, rest from similar tracks
                artist_percentage = random.uniform(0.3, 0.5)
                artist_count = int(SONGS_PER_PLAYLIST * artist_percentage)
                artist_count = min(artist_count, len(artist_tracks))
                
                selected_artist_tracks = random.sample(artist_tracks, artist_count) if artist_tracks else []
                remaining_slots = SONGS_PER_PLAYLIST - len(selected_artist_tracks)
                
                available_similar = [t for t in similar_tracks if t not in selected_artist_tracks]
                if available_similar and remaining_slots > 0:
                    similar_count = min(remaining_slots, len(available_similar))
                    selected_similar = random.sample(available_similar, similar_count)
                    playlist_songs = selected_artist_tracks + selected_similar
                else:
                    playlist_songs = selected_artist_tracks
                
                log_info(f"✅ Selected {len(selected_artist_tracks)} tracks from {artist_original} and {len(playlist_songs) - len(selected_artist_tracks)} similar tracks")
            
            # Balance artist representation
            playlist_songs = balance_artist_representation(playlist_songs, all_available_tracks, MAX_ARTIST_PERCENTAGE)
            
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
            
            # Get a random unused poster image
            poster_image = None
            if available_images:
                selected_image_name = get_random_unused_image(available_images, used_images)
                if selected_image_name:
                    poster_image = os.path.join(PLAYLIST_POSTERS_DIR, selected_image_name)
                    used_images.add(selected_image_name)
                    log_debug(f"📸 Selected poster: {selected_image_name}")
            
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
                if selected_method == "genre":
                    similarity_info = "Used similar songs based on genres"
                elif selected_method == "similar_artists":
                    similarity_info = "Used similar artists"
                elif selected_method == "similar_tracks":
                    similarity_info = "Used similar tracks from a liked song"
                elif selected_method == "combined":
                    similarity_info = "Used similar songs based on genres, similar artists, and similar tracks"
                else:
                    similarity_info = f"Used similar songs (method: {selected_method})"
                
                existing_playlist.editSummary(f"Artist: {artist_original}\nUpdated on: {timestamp}\n{similarity_info}")
                
                if poster_image:
                    upload_playlist_poster(existing_playlist, poster_image)
                playlist = existing_playlist
            else:
                log_info(f"✨ Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)
                
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Convert similarity method to plain English
                if selected_method == "genre":
                    similarity_info = "Used similar songs based on genres"
                elif selected_method == "similar_artists":
                    similarity_info = "Used similar artists"
                elif selected_method == "similar_tracks":
                    similarity_info = "Used similar tracks from a liked song"
                elif selected_method == "combined":
                    similarity_info = "Used similar songs based on genres, similar artists, and similar tracks"
                else:
                    similarity_info = f"Used similar songs (method: {selected_method})"
                
                playlist.editSummary(f"Artist: {artist_original}\nCreated on: {timestamp}\n{similarity_info}")
                
                if poster_image:
                    upload_playlist_poster(playlist, poster_image)
            
            log_info(f"✅ Playlist '{playlist_name}' successfully created/updated with {len(playlist_songs)} songs.")
            
            # Add the artist to the log
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


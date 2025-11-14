from plexapi.server import PlexServer
import random
import json
import os
import time
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import requests
from urllib.parse import quote
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

# Define required environment variables for PPG-Genres.py
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
    # Genres-specific
    "GENRES_MIN_SONGS_REQUIRED",
    "GENRE_MIXES_FILE"
]

# Validate environment variables before proceeding
validate_env_vars(REQUIRED_ENV_VARS, "PPG-Genres.py")

# Fetch all configuration from environment variables (no defaults)
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")

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

# Genres-specific configuration
MIN_SONGS_REQUIRED = float(os.getenv("GENRES_MIN_SONGS_REQUIRED")) * SONGS_PER_PLAYLIST
GENRE_MIXES_FILE = os.getenv("GENRE_MIXES_FILE")
GENRES_REPLACE_POSTERS = os.getenv("GENRES_AUTO_REPLACE_POSTERS", "false").lower() == "true"

# Connect to the Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

# Normalize artist name for consistent comparison
def normalize_artist_name(artist_name):
    """Normalize artist name for consistent comparison.
    Handles Unicode (German ÄÖÜ, Cyrillic), whitespace around slashes, 
    multiple spaces, and strips leading/trailing whitespace."""
    if not artist_name:
        return None
    
    import unicodedata
    # Normalize Unicode characters (NFC form - preserves German ÄÖÜ and Cyrillic properly)
    # This handles composed vs decomposed forms (e.g., Ä vs A+̈)
    normalized = unicodedata.normalize('NFC', artist_name)
    
    # Strip leading/trailing whitespace
    normalized = normalized.strip()
    
    # Normalize whitespace around slashes (e.g., "Artist / Featuring" -> "Artist/Featuring")
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
            # Plex stores duration in milliseconds
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

# Get album release year from a track
def get_album_release_year(track):
    """Get the release year from the track's parent album."""
    try:
        # Get the parent album
        if hasattr(track, 'album') and track.album:
            album = track.album() if callable(track.album) else track.album
            if album and hasattr(album, 'originallyAvailableAt') and album.originallyAvailableAt:
                # originallyAvailableAt is a datetime, extract year
                from datetime import datetime
                release_date = album.originallyAvailableAt
                if isinstance(release_date, str):
                    release_date = datetime.fromisoformat(release_date.replace('Z', '+00:00'))
                return release_date.year
        return None
    except Exception as e:
        log_debug(f"⚠️  Error getting album release year for track '{track.title}': {e}")
        return None

# Helper function to filter a batch of tracks by release date
def filter_track_batch_by_date(track_batch, condition, start_year, end_year):
    """Filter a batch of tracks by release date. Used for parallel processing."""
    filtered_batch = []
    for track in track_batch:
        release_year = get_album_release_year(track)
        if release_year is None:
            # If we can't determine the release year, skip this track
            continue
        
        if condition == 'between':
            if start_year <= release_year <= end_year:
                filtered_batch.append(track)
        elif condition == 'before':
            if release_year < end_year:
                filtered_batch.append(track)
        elif condition == 'after':
            if release_year >= start_year:
                filtered_batch.append(track)
    
    return filtered_batch

# Filter tracks by release date
def filter_by_release_date(tracks, date_filter):
    """Filter tracks based on their album's release date.
    
    Args:
        tracks: List of track objects
        date_filter: Dict with keys 'condition' and date parameters
            - condition: 'between', 'before', 'after'
            - start_date: Year (int or str) for 'between' and 'after'
            - end_date: Year (int or str) for 'between' and 'before'
    
    Returns:
        Filtered list of tracks
    """
    if not date_filter:
        return tracks
    
    condition = date_filter.get('condition', '').lower()
    if condition not in ['between', 'before', 'after']:
        log_warning(f"⚠️  Unknown date filter condition: {condition}. Skipping date filter.")
        return tracks
    
    start_year = None
    end_year = None
    
    if condition == 'between':
        start_year = int(date_filter.get('start_date', 0))
        end_year = int(date_filter.get('end_date', 9999))
    elif condition == 'before':
        end_year = int(date_filter.get('end_date', 9999))
    elif condition == 'after':
        start_year = int(date_filter.get('start_date', 0))
    
    log_info(f"📅 Filtering {len(tracks)} tracks by release date: {condition} ({start_year if start_year else ''} - {end_year if end_year else ''}) (multi-threaded)")
    
    filtered = []
    
    # Determine optimal batch size and number of workers
    # Use smaller batches for better load distribution, but not too small to avoid overhead
    batch_size = max(50, len(tracks) // 20)  # Aim for ~20 batches, minimum 50 tracks per batch
    num_workers = min(10, max(4, len(tracks) // batch_size))  # 4-10 workers depending on track count
    
    # Split tracks into batches
    track_batches = [tracks[i:i + batch_size] for i in range(0, len(tracks), batch_size)]
    
    # Process batches in parallel
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Submit all batches
        future_to_batch = {executor.submit(filter_track_batch_by_date, batch, condition, start_year, end_year): batch for batch in track_batches}
        
        # Collect results with progress bar
        with tqdm(total=len(track_batches), desc="Filtering by release date", unit="batch", disable=(LOG_LEVEL in ["WARNING", "ERROR"])) as pbar:
            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                try:
                    filtered_batch = future.result()
                    filtered.extend(filtered_batch)
                    pbar.update(1)
                    pbar.set_postfix({"filtered": len(filtered), "total": len(tracks)})
                except Exception as e:
                    log_error(f"Error processing batch: {e}")
                    pbar.update(1)
    
    if len(tracks) > 0:
        log_info(f"✅ Release date filter: {len(tracks)} tracks -> {len(filtered)} tracks ({len(filtered)/len(tracks)*100:.1f}% matched)")
    else:
        log_info(f"✅ Release date filter: {len(tracks)} tracks -> {len(filtered)} tracks (no tracks to filter)")
    return filtered

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


# Filter tracks by minimum duration
def filter_by_minimum_duration(tracks, min_duration_seconds=90):
    """Filter out tracks shorter than the minimum duration."""
    if min_duration_seconds <= 0:
        return tracks
    
    filtered = []
    removed = 0
    for track in tracks:
        duration = get_track_duration_seconds(track)
        if duration is None or duration >= min_duration_seconds:
            filtered.append(track)
        else:
            removed += 1
    
    if removed > 0:
        print(f"⏱️  Removed {removed} tracks shorter than {min_duration_seconds} seconds")
    
    return filtered

# Limit songs per album
def limit_songs_per_album(playlist_songs, all_available_songs, max_per_album=1):
    """Ensure no more than max_per_album songs from the same album."""
    if max_per_album <= 0:
        return playlist_songs
    
    album_counts = {}
    album_tracks = {}
    
    # Group tracks by album
    for track in playlist_songs:
        album_name = get_album_name(track)
        if album_name:
            if album_name not in album_tracks:
                album_tracks[album_name] = []
            album_tracks[album_name].append(track)
            album_counts[album_name] = album_counts.get(album_name, 0) + 1
    
    # Find albums that exceed the limit
    albums_to_reduce = {
        album: count - max_per_album 
        for album, count in album_counts.items() 
        if count > max_per_album
    }
    
    if not albums_to_reduce:
        return playlist_songs
    
    print(f"💿 Limiting songs per album (max {max_per_album} per album)")
    print(f"Albums with excess songs: {albums_to_reduce}")
    
    # Remove excess tracks from albums
    filtered_playlist = []
    for album_name, tracks in album_tracks.items():
        if album_name in albums_to_reduce:
            # Keep only max_per_album random tracks from this album
            tracks_to_keep = random.sample(tracks, max_per_album)
            filtered_playlist.extend(tracks_to_keep)
            print(f"  Album '{album_name}': kept {len(tracks_to_keep)} of {len(tracks)} tracks")
        else:
            filtered_playlist.extend(tracks)
    
    # Fill back up to target size from available songs
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
            print(f"  Added {len(additional)} additional songs to maintain playlist size")
        else:
            # Try to fill with any available songs
            available_any = [s for s in all_available_songs if s not in filtered_playlist]
            if available_any:
                additional = random.sample(available_any, min(songs_needed, len(available_any)))
                filtered_playlist.extend(additional)
                print(f"  Added {len(additional)} additional songs (some may be from same albums)")
    
    return filtered_playlist

# Prevent consecutive same artist
def prevent_consecutive_artists(playlist_songs):
    """Reorder playlist to prevent same artist appearing consecutively."""
    if len(playlist_songs) < 2:
        return playlist_songs
    
    # Group tracks by artist
    artist_tracks = {}
    for track in playlist_songs:
        artist = get_artist_name(track)
        if artist:
            if artist not in artist_tracks:
                artist_tracks[artist] = []
            artist_tracks[artist].append(track)
        else:
            # Tracks without artist go to a special group
            if 'Unknown' not in artist_tracks:
                artist_tracks['Unknown'] = []
            artist_tracks['Unknown'].append(track)
    
    if len(artist_tracks) <= 1:
        return playlist_songs  # Can't reorder if only one artist
    
    # Shuffle each artist's tracks
    for artist in artist_tracks:
        random.shuffle(artist_tracks[artist])
    
    # Interleave artists to avoid consecutive repeats
    reordered = []
    artist_queue = list(artist_tracks.keys())
    random.shuffle(artist_queue)
    
    while len(reordered) < len(playlist_songs):
        # Find an artist to add next (not the same as last)
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
        
        # If we couldn't avoid a repeat, just take any available artist
        if not next_artist:
            available = [a for a in artist_queue if artist_tracks[a]]
            if available:
                next_artist = random.choice(available)
        
        if next_artist and artist_tracks[next_artist]:
            reordered.append(artist_tracks[next_artist].pop())
        else:
            # No more tracks available, break
            break
    
    # Add any remaining tracks at the end
    for tracks in artist_tracks.values():
        reordered.extend(tracks)
    
    print(f"🔄 Reordered playlist to minimize consecutive artist repeats")
    return reordered[:len(playlist_songs)]

# Group and sort by BPM
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
    
    # 1. Filter by minimum duration
    if min_duration_seconds > 0:
        playlist_songs = filter_by_minimum_duration(playlist_songs, min_duration_seconds)
    
    # 2. Limit songs per album
    if max_songs_per_album > 0 and len(playlist_songs) > max_songs_per_album:
        playlist_songs = limit_songs_per_album(playlist_songs, all_available_songs, max_songs_per_album)
    
    # 3. Prevent consecutive artists (after limiting albums, may need reordering)
    if prevent_consecutive and len(playlist_songs) > 1:
        playlist_songs = prevent_consecutive_artists(playlist_songs)
    
    # 4. Group by mood if enabled (after other filters, before finalizing)
    if mood_grouping and len(playlist_songs) > 1:
        playlist_songs = group_by_mood(playlist_songs)
    
    log_info(f"✅ Quality filters applied: {original_count} tracks -> {len(playlist_songs)} tracks")
    return playlist_songs

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
        # Find all songs by this artist (get_artist_name already normalizes)
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
        log_info(f"✅ Selected {variety_count} songs from other artists for guaranteed variety")
    
    # Fill remaining slots with liked artists (up to max percentage)
    remaining_slots = target_count - len(selected_songs)
    if liked_songs and remaining_slots > 0:
        liked_count = min(len(liked_songs), remaining_slots, max_liked_count)
        selected_songs.extend(random.sample(liked_songs, liked_count))
        log_info(f"✅ Selected {liked_count} songs from liked artists")
    
    # Fill any remaining slots with more other songs if needed
    remaining_slots = target_count - len(selected_songs)
    if other_songs and remaining_slots > 0:
        other_count = min(len(other_songs), remaining_slots)
        # Remove already selected songs from available pool
        available_other_songs = [song for song in other_songs if song not in selected_songs]
        if available_other_songs:
            other_count = min(len(available_other_songs), other_count)
            selected_songs.extend(random.sample(available_other_songs, other_count))
            log_info(f"✅ Selected {other_count} additional songs from other artists to fill playlist")
    
    # Show final distribution
    final_liked_count = sum(1 for song in selected_songs if get_artist_name(song) and get_artist_name(song) in liked_artists)
    final_other_count = len(selected_songs) - final_liked_count
    final_liked_percentage = (final_liked_count / len(selected_songs)) * 100 if selected_songs else 0
    final_other_percentage = (final_other_count / len(selected_songs)) * 100 if selected_songs else 0
    
    log_info(f"📊 Final selection: {final_liked_count} from liked artists ({final_liked_percentage:.1f}%), {final_other_count} from other artists ({final_other_percentage:.1f}%)")
    
    return selected_songs

# Load liked artists from cache file
def load_liked_artists_cache():
    """Load liked artists and track count from cache file.
    Supports both old format (list of strings) and new format (list of dicts with 'id' and 'name').
    Returns (liked_artists_set, track_count, cache_timestamp)"""
    print("🔍 Checking liked artists cache...")
    if not os.path.exists(LIKED_ARTISTS_CACHE_FILE):
        print("❌ No liked artists cache found.")
        return None, 0, None
    
    try:
        with open(LIKED_ARTISTS_CACHE_FILE, "r", encoding='utf-8') as file:
            cache_data = json.load(file)
            
            # Try new format first (detailed with IDs)
            detailed_artists = cache_data.get("liked_artists_detailed", [])
            # Fallback to old format
            raw_artists = cache_data.get("liked_artists", [])
            
            liked_artists = set()
            
            # Process detailed format (new format with IDs)
            if detailed_artists and isinstance(detailed_artists[0], dict):
                print("📊 Loading artists from detailed format (with IDs)...")
                for artist_info in detailed_artists:
                    artist_name = artist_info.get('name', '')
                    if artist_name:
                        normalized = normalize_artist_name(artist_name)
                        if normalized:
                            liked_artists.add(normalized)
            # Fallback to old format (just names)
            elif raw_artists:
                print("📊 Loading artists from legacy format (names only)...")
                for artist in raw_artists:
                    if isinstance(artist, str):
                        normalized = normalize_artist_name(artist)
                        if normalized:
                            liked_artists.add(normalized)
            
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


# Fetch Spotify poster image
def fetch_spotify_poster(genre_mix_name):
    """Fetch poster image from Spotify using the genre mix name exactly as provided."""
    try:
        # Use the genre mix name exactly as-is (capital letters and spaces preserved)
        # URL-encode only special characters that need encoding
        url_encoded_name = quote(genre_mix_name.strip(), safe=' ')
        
        # Construct Spotify poster URL
        url = f"https://seed-mix-image.spotifycdn.com/v6/img/desc/{url_encoded_name}/en/default"
        
        log_debug(f"🎨 Fetching Spotify poster from: {url}")
        response = requests.get(url, timeout=10, allow_redirects=True)
        
        if response.status_code == 200 and response.content:
            # Check if it's actually an image (not HTML error page)
            content_type = response.headers.get('content-type', '').lower()
            if 'image' in content_type or response.content.startswith(b'\xff\xd8') or response.content.startswith(b'\x89PNG'):
                log_info(f"✅ Successfully fetched Spotify poster for '{genre_mix_name}'")
                return response.content
            else:
                log_debug(f"⚠️  Response is not an image (content-type: {content_type})")
                return None
        else:
            log_debug(f"⚠️  Failed to fetch poster (status: {response.status_code})")
            return None
    except Exception as e:
        log_debug(f"⚠️  Error fetching Spotify poster for '{genre_mix_name}': {e}")
        return None

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

# Upload poster from image data
def upload_playlist_poster_from_data(playlist, image_data):
    """Upload a poster image to a Plex playlist from image data bytes."""
    try:
        if not image_data:
            return False
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            tmp_file.write(image_data)
            tmp_path = tmp_file.name
        
        try:
            upload_playlist_poster(playlist, tmp_path)
            return True
        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        
        return False
    except Exception as e:
        log_warning(f"⚠️  Could not upload poster from data: {e}")
        return False

# Load genre mixes from JSON file
# Supports both old format (key -> array) and new format (key -> {genres: array, release_date_filter: {...}})
def load_genre_mixes():
    print("Loading genre mixes from file...")
    if not os.path.exists(GENRE_MIXES_FILE):
        print(f"Error: {GENRE_MIXES_FILE} not found.")
        return {}
    try:
        with open(GENRE_MIXES_FILE, "r") as file:
            raw_data = json.load(file)
            
            # Handle case where JSON root is a list instead of a dict
            if isinstance(raw_data, list):
                print(f"⚠️  JSON file contains a list at root level, expected a dictionary. Converting...")
                # Convert list to dict (use index as key, or skip if not applicable)
                print(f"❌ Cannot convert list to dictionary format. Please ensure JSON root is a dictionary.")
                return {}
            
            if not isinstance(raw_data, dict):
                print(f"❌ Invalid JSON format: root must be a dictionary, got {type(raw_data).__name__}")
                return {}
            
            genre_mixes = {}
            
            # Handle both old format (key -> array) and new format (key -> object)
            for key, value in raw_data.items():
                if isinstance(value, list):
                    # Old format: just an array of genres
                    genre_mixes[key] = {
                        'genres': value,
                        'release_date_filter': None
                    }
                elif isinstance(value, dict):
                    # New format: object with genres and optional release_date_filter
                    genre_mixes[key] = {
                        'genres': value.get('genres', []),
                        'release_date_filter': value.get('release_date_filter', None)
                    }
                else:
                    print(f"⚠️  Invalid format for genre mix '{key}': expected array or object, got {type(value).__name__}")
            
            print(f"Loaded {len(genre_mixes)} genre mixes successfully!")
            return genre_mixes
    except Exception as e:
        print(f"Error loading genre mixes: {e}")
        import traceback
        traceback.print_exc()
        return {}

# Generate playlists based on genre mixes
def generate_genre_playlists():
    print("🔌 Connecting to Plex server...")
    try:
        music_library = plex.library.section("Music")  # Adjust if your music library name differs
        print("✅ Successfully connected to Plex server and accessed 'Music' library.")
    except Exception as e:
        print(f"❌ Error connecting to Plex server or accessing library: {e}")
        return

    # Load genre mixes
    genre_mixes = load_genre_mixes()
    if not genre_mixes:
        print("❌ No genre mixes available. Exiting.")
        return

    # Load liked artists from cache
    print("🎵 Loading liked artists from cache...")
    cached_artists, cached_track_count, cache_timestamp = load_liked_artists_cache()
    
    if cached_artists is not None:
        print(f"✅ Loaded {len(cached_artists):,} liked artists from cache")
        liked_artists = cached_artists
        if cache_timestamp:
            from datetime import datetime
            cache_date = datetime.fromisoformat(cache_timestamp)
            days_old = (datetime.now() - cache_date).days
            print(f"📅 Cache is {days_old} days old")
    else:
        print("⚠️ No liked artists cache found. Run fetch-liked-artists.py to create the cache.")
        print("⚠️ Continuing without liked artists data.")
        liked_artists = set()

    for i, (genre_group, group_data) in enumerate(genre_mixes.items()):
        playlist_name = f"{genre_group} Mix"
        playlist_start_time = time.time()
        log_info(f"\n🎵 Starting generation for Playlist '{playlist_name}'...")
        playlist_songs = []
        try:
            # Defensive check: ensure group_data is a dictionary
            # If it's still a list (shouldn't happen after load_genre_mixes, but handle it anyway)
            if isinstance(group_data, list):
                log_warning(f"⚠️  Genre mix '{genre_group}' has list format, converting to dict format...")
                group_data = {
                    'genres': group_data,
                    'release_date_filter': None
                }
            elif not isinstance(group_data, dict):
                log_error(f"❌ Invalid format for genre mix '{genre_group}': expected dict or list, got {type(group_data).__name__}")
                continue
            
            genres = group_data.get('genres', [])
            if not genres:
                log_warning(f"⚠️  No genres found for '{genre_group}', skipping...")
                continue
            
            release_date_filter = group_data.get('release_date_filter', None)
            
            if release_date_filter:
                log_debug(f"Release date filter: {release_date_filter}")
            
            # Collect all tracks for the selected genres (multi-threaded)
            songs = []
            def fetch_genre_tracks(genre):
                """Fetch tracks for a single genre. Used for parallel execution."""
                try:
                    log_debug(f"Fetching tracks for genre: {genre}")
                    tracks = music_library.search(genre=genre, libtype="track", limit=None)
                    log_debug(f"Found {len(tracks)} tracks for genre: {genre}")
                    return (genre, tracks)
                except Exception as e:
                    log_error(f"Error fetching tracks for genre '{genre}': {e}")
                    return (genre, [])
            
            # Fetch all genres in parallel with progress bar
            log_info(f"🔄 Fetching tracks for {len(genres)} genre(s)...")
            with ThreadPoolExecutor(max_workers=len(genres)) as executor:
                future_to_genre = {executor.submit(fetch_genre_tracks, genre): genre for genre in genres}
                # Use tqdm to show progress
                with tqdm(total=len(genres), desc="Fetching genres", unit="genre", disable=(LOG_LEVEL in ["WARNING", "ERROR"])) as pbar:
                    for future in as_completed(future_to_genre):
                        genre = future_to_genre[future]
                        try:
                            genre_name, tracks = future.result()
                            songs.extend(tracks)
                            pbar.update(1)
                            pbar.set_postfix({"current": genre_name, "total_tracks": len(songs)})
                        except Exception as e:
                            log_error(f"Error processing results for genre '{genre}': {e}")
                            pbar.update(1)
            log_info(f"✅ Fetched {len(songs)} total tracks from {len(genres)} genre(s)")

            # Apply release date filter if specified
            if release_date_filter:
                songs = filter_by_release_date(songs, release_date_filter)

            total_songs = len(songs)
            print(f"Total songs after filtering: {total_songs}")

            # Check if the number of songs is >= MIN_SONGS_REQUIRED
            if total_songs >= MIN_SONGS_REQUIRED:
                print(f"Found sufficient songs ({total_songs}) for Playlist '{playlist_name}'. Creating playlist.")
            else:
                print(f"Not enough songs for Playlist '{playlist_name}', skipping.")
                continue

            # Select the required number of songs (up to SONGS_PER_PLAYLIST)
            if liked_artists:
                playlist_songs = prefer_liked_artists(songs, liked_artists, min(len(songs), SONGS_PER_PLAYLIST), 
                                                    MAX_LIKED_ARTISTS_PERCENTAGE, MIN_VARIETY_PERCENTAGE)
                print(f"Selected {len(playlist_songs)} songs (preferring liked artists) for Playlist '{playlist_name}'.")
            else:
                playlist_songs = random.sample(songs, min(len(songs), SONGS_PER_PLAYLIST))
                print(f"Selected {len(playlist_songs)} random songs for Playlist '{playlist_name}'.")

            # Balance artist representation to ensure no single artist exceeds the configured limit
            print(f"Checking artist distribution for Playlist '{playlist_name}'...")
            playlist_songs = balance_artist_representation(playlist_songs, songs, MAX_ARTIST_PERCENTAGE)

            # Apply quality filters (duration, album variety, consecutive artists, mood grouping)
            log_debug(f"Applying quality filters for Playlist '{playlist_name}'...")
            playlist_songs = apply_quality_filters(
                playlist_songs, 
                songs,
                min_duration_seconds=MIN_SONG_DURATION_SECONDS,
                max_songs_per_album=MAX_SONGS_PER_ALBUM,
                prevent_consecutive=PREVENT_CONSECUTIVE_ARTISTS,
                mood_grouping=MOOD_GROUPING_ENABLED
            )

            # Create or update the playlist
            existing_playlist = plex.playlist(playlist_name) if playlist_name in [pl.title for pl in plex.playlists()] else None

            if existing_playlist:
                print(f"Updating existing playlist: {playlist_name}")
                existing_playlist.removeItems(existing_playlist.items())
                existing_playlist.addItems(playlist_songs)
                
                # Update the description with the selected genres and timestamp
                genre_description = ", ".join(genres)
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                existing_playlist.editSummary(f"{genre_group}\nUpdated on: {timestamp}\nGenres used: {genre_description}")
                
                # Fetch and upload Spotify poster if enabled
                if GENRES_REPLACE_POSTERS:
                    poster_data = fetch_spotify_poster(genre_group)
                    if poster_data:
                        upload_playlist_poster_from_data(existing_playlist, poster_data)
                playlist = existing_playlist
            else:
                print(f"Creating new playlist: {playlist_name}")
                playlist = plex.createPlaylist(playlist_name, items=playlist_songs)
                
                # Set the description with the selected genres and timestamp
                genre_description = ", ".join(genres)
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                playlist.editSummary(f"{genre_group}\nUpdated on: {timestamp}\nGenres used: {genre_description}")
                
                # Fetch and upload Spotify poster if enabled
                if GENRES_REPLACE_POSTERS:
                    poster_data = fetch_spotify_poster(genre_group)
                    if poster_data:
                        upload_playlist_poster_from_data(playlist, poster_data)

            log_info(f"✅ Playlist '{playlist_name}' successfully created/updated with {len(playlist_songs)} songs.")

        except Exception as e:
            log_error(f"❌ Error during playlist generation for Playlist '{playlist_name}': {e}")
        
        # Always output the time taken for this playlist, even if there was an error
        playlist_end_time = time.time()
        elapsed_time = playlist_end_time - playlist_start_time
        if playlist_songs and len(playlist_songs) > 0:
            log_info(f"⏱️  Generation time for '{playlist_name}': {format_duration(elapsed_time)}")
        else:
            log_info(f"⏱️  Time taken for '{playlist_name}' (failed): {format_duration(elapsed_time)}")
        log_info("---------------------------------------------")

# Run the script
if __name__ == "__main__":
    script_start_time = time.time()
    log_info("🚀 Starting the Genre playlist generation process...")
    generate_genre_playlists()
    script_end_time = time.time()
    total_elapsed_time = script_end_time - script_start_time
    log_info("\n✅ Genre playlists updated successfully.")
    log_info(f"⏱️  Total script execution time: {format_duration(total_elapsed_time)}")
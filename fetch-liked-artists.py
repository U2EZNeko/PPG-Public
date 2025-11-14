
from plexapi.server import PlexServer
import json
import os
import sys
import threading
import time
from dotenv import load_dotenv
from tqdm import tqdm
from datetime import datetime

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

# Define required environment variables
REQUIRED_ENV_VARS = [
    "PLEX_URL",
    "PLEX_TOKEN",
    "LIKED_ARTISTS_CACHE_FILE"
]

# Validate environment variables before proceeding
validate_env_vars(REQUIRED_ENV_VARS, "fetch-liked-artists.py")

# Fetch configuration from environment variables
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
LIKED_ARTISTS_CACHE_FILE = os.getenv("LIKED_ARTISTS_CACHE_FILE")

# Connect to the Plex server
print("🔌 Connecting to Plex server...")
plex = PlexServer(PLEX_URL, PLEX_TOKEN)
print("✅ Connected to Plex server successfully!")


# Normalize artist name for consistent matching
def normalize_artist_name(artist_name):
    """Normalize artist name for consistent comparison."""
    if not artist_name:
        return None
    
    # Convert to lowercase
    normalized = artist_name.lower()
    
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


# Get artist name from a track (original, non-normalized)
def get_artist_name_original(track):
    """Get the original artist name from a track, preserving casing."""
    if hasattr(track, 'artist') and track.artist:
        artist_name = track.artist().title if callable(track.artist) else track.artist
    elif hasattr(track, 'grandparentTitle') and track.grandparentTitle:
        artist_name = track.grandparentTitle
    else:
        return None
    
    # Strip leading/trailing whitespace and normalize whitespace around slashes
    if artist_name:
        artist_name = artist_name.strip()
        artist_name = artist_name.replace(' / ', '/').replace('/ ', '/').replace(' /', '/')
        artist_name = ' '.join(artist_name.split())
    
    return artist_name


# Get liked artists directly from Plex (artists with 1+ star rating)
def get_liked_artists_directly():
    """Get a list of artist info (ID and name) that are directly rated/liked in Plex (1+ stars).
    Returns a list of dicts with 'id' and 'name' keys."""
    try:
        print("🎤 Fetching liked artists directly from Plex (rated artists)...")
        liked_artists_normalized = set()  # For deduplication
        liked_artists_dict = {}  # Maps normalized -> {"id": ratingKey, "name": original_name}
        
        # Get music library
        music_library = plex.library.section("Music")
        
        # Try different approaches to find liked artists
        print("🔍 Attempting to query Plex for artists with 1+ star rating...")
        print()
        
        liked_artists_items = []
        
        # Method 1: Try searchArtists with userRating__gte
        print("📡 Method 1: Trying searchArtists(userRating__gte=1)...")
        sys.stdout.flush()
        try:
            liked_artists_items = music_library.searchArtists(userRating__gte=1)
            print(f"✅ Method 1 (searchArtists): Found {len(liked_artists_items):,} liked artists")
            sys.stdout.flush()
        except Exception as e1:
            print(f"❌ Method 1 failed: {e1}")
            sys.stdout.flush()
        
        # Method 2: Try search with different filter syntax
        if not liked_artists_items:
            print()
            print("📡 Method 2: Trying search(libtype='artist', filters={'userRating>=': 1})...")
            sys.stdout.flush()
            try:
                liked_artists_items = music_library.search(libtype="artist", filters={'userRating>=': 1}, limit=None)
                print(f"✅ Method 2 (search with userRating>=): Found {len(liked_artists_items):,} liked artists")
                sys.stdout.flush()
            except Exception as e2:
                print(f"❌ Method 2 failed: {e2}")
                sys.stdout.flush()
        
        # Method 3: Try search with userRating__gte in filters
        if not liked_artists_items:
            print()
            print("📡 Method 3: Trying search(libtype='artist', filters={'userRating__gte': 1})...")
            sys.stdout.flush()
            try:
                liked_artists_items = music_library.search(libtype="artist", filters={'userRating__gte': 1}, limit=None)
                print(f"✅ Method 3 (search with userRating__gte): Found {len(liked_artists_items):,} liked artists")
                sys.stdout.flush()
            except Exception as e3:
                print(f"❌ Method 3 failed: {e3}")
                sys.stdout.flush()
        
        # Method 4: Fallback - get all artists and filter manually (for debugging)
        if not liked_artists_items:
            print("⚠️ All direct filtering methods failed. Falling back to manual filtering for debugging...")
            print("🐌 This will be slower but will help us debug the issue.")
            all_artists = music_library.search(libtype="artist", limit=None)
            print(f"📊 Loaded {len(all_artists):,} total artists for manual filtering...")
            
            # Debug: Check a few artists for their userRating
            print("🔍 Checking first 10 artists for userRating values:")
            for i, artist in enumerate(all_artists[:10]):
                rating = getattr(artist, 'userRating', 'No userRating attribute')
                print(f"  Artist {i+1}: {artist.title} - userRating: {rating}")
            
            # Filter manually
            liked_artists_items = []
            for i, artist in enumerate(all_artists):
                if hasattr(artist, 'userRating') and artist.userRating and artist.userRating >= 1:
                    liked_artists_items.append(artist)
                
                # Show progress every 1000 artists
                if i % 1000 == 0 and i > 0:
                    print(f"Manual filtering progress: {i:,}/{len(all_artists):,} artists - Found {len(liked_artists_items):,} liked artists so far", end='\r')
            
            print(f"\n✅ Manual filtering complete: Found {len(liked_artists_items):,} liked artists")
        
        if not liked_artists_items:
            print("⚠️ No directly rated artists found. This is normal if you only rate tracks, not artists.")
            return []
        
        print(f"🎯 Found {len(liked_artists_items):,} directly rated artists, extracting IDs and names...")
        
        # Extract artist IDs and names
        for i, artist in enumerate(liked_artists_items, 1):
            artist_name = artist.title
            artist_id = getattr(artist, 'ratingKey', None)
            
            if artist_name:
                # Normalize whitespace
                artist_name = artist_name.strip()
                artist_name = artist_name.replace(' / ', '/').replace('/ ', '/').replace(' /', '/')
                artist_name = ' '.join(artist_name.split())
                
                artist_normalized = normalize_artist_name(artist_name)
                if artist_normalized:
                    liked_artists_normalized.add(artist_normalized)
                    # Store ID and name (preserve casing)
                    if artist_normalized not in liked_artists_dict:
                        liked_artists_dict[artist_normalized] = {
                            "id": artist_id,
                            "name": artist_name
                        }
            
            # Show progress
            if i % 50 == 0 or i == len(liked_artists_items):
                progress_percent = (i / len(liked_artists_items)) * 100
                print(f"Processing artists: {i:,}/{len(liked_artists_items):,} ({progress_percent:.1f}%) - Found {len(liked_artists_normalized):,} unique so far", end='\r')
        
        # Return list of artist info dicts
        artist_info_list = [liked_artists_dict[norm] for norm in sorted(liked_artists_normalized)]
        
        print(f"\n🎉 Found {len(artist_info_list):,} unique directly rated artists")
        return artist_info_list
        
    except Exception as e:
        print(f"❌ Error fetching liked artists directly: {e}")
        import traceback
        traceback.print_exc()
        return []


# Get artist ID from a track
def get_artist_id(track):
    """Get the artist ID (ratingKey) from a track."""
    try:
        if hasattr(track, 'artist') and track.artist:
            artist_obj = track.artist() if callable(track.artist) else track.artist
            if hasattr(artist_obj, 'ratingKey'):
                return artist_obj.ratingKey
        # Try to get from grandparent (album -> artist)
        if hasattr(track, 'grandparentRatingKey'):
            return track.grandparentRatingKey
        return None
    except Exception as e:
        return None

# Get liked artists from Plex by fetching liked tracks directly (1+ stars)
def get_liked_artists_from_tracks():
    """Get a list of artist info (ID and name) from all liked tracks (1+ stars) in Plex.
    Returns a tuple of (artist_info_list, track_count, liked_tracks_list).
    artist_info_list contains dicts with 'id' and 'name' keys.
    liked_tracks_list contains the actual track objects for caching."""
    try:
        print("🎵 Fetching liked artists from Plex by querying liked tracks...")
        liked_artists_normalized = set()  # For deduplication
        liked_artists_dict = {}  # Maps normalized -> {"id": ratingKey, "name": original_name}
        
        # Get music library
        music_library = plex.library.section("Music")
        
        # Try different approaches to find liked tracks
        print("🔍 Attempting to query Plex for tracks with 1+ star rating...")
        print()
        
        liked_items = []
        
        # Method 1: Try searchTracks with userRating__gte
        print("📡 Method 1: Trying searchTracks(userRating__gte=1)...")
        print("   ⏳ Querying Plex...", end='', flush=True)
        
        query_done = threading.Event()
        query_result = {'items': None, 'error': None, 'count': 0}
        start_time = time.time()
        
        def show_progress():
            """Show progress dots while query is running"""
            dots = 0
            while not query_done.is_set():
                dots = (dots + 1) % 4
                status_dots = '.' * dots + ' ' * (3 - dots)
                if query_result['count'] > 0:
                    print(f"\r   ⏳ Querying Plex{status_dots} (found {query_result['count']:,} tracks)", end='', flush=True)
                else:
                    elapsed = int(time.time() - start_time)
                    print(f"\r   ⏳ Querying Plex{status_dots} ({elapsed}s)", end='', flush=True)
                time.sleep(0.5)
        
        def run_query():
            """Run the actual query in background"""
            try:
                result = music_library.searchTracks(userRating__gte=1)
                query_result['items'] = result
                query_result['count'] = len(result) if result else 0
            except Exception as e:
                query_result['error'] = e
            finally:
                query_done.set()
        
        # Start progress indicator thread
        progress_thread = threading.Thread(target=show_progress, daemon=True)
        progress_thread.start()
        
        # Start query thread
        query_thread = threading.Thread(target=run_query)
        query_thread.start()
        query_thread.join()
        
        query_done.set()
        time.sleep(0.6)  # Let progress indicator finish its last update
        
        elapsed_time = int(time.time() - start_time)
        
        if query_result['items'] is not None:
            liked_items = query_result['items']
            print(f"\r   ✅ Query complete! Found {len(liked_items):,} liked tracks (took {elapsed_time}s)")
            print(f"✅ Method 1 (searchTracks): Found {len(liked_items):,} liked tracks")
            sys.stdout.flush()
        else:
            print(f"\r   ❌ Query failed: {query_result['error']}")
            print(f"❌ Method 1 failed: {query_result['error']}")
            sys.stdout.flush()
        
        # Method 2: Try search with different filter syntax
        if not liked_items:
            print()
            print("📡 Method 2: Trying search(libtype='track', filters={'userRating>=': 1})...")
            print("   ⏳ Querying Plex...", end='', flush=True)
            
            query_done = threading.Event()
            query_result = {'items': None, 'error': None, 'count': 0}
            start_time = time.time()
            
            def show_progress():
                """Show progress dots while query is running"""
                dots = 0
                while not query_done.is_set():
                    dots = (dots + 1) % 4
                    status_dots = '.' * dots + ' ' * (3 - dots)
                    if query_result['count'] > 0:
                        print(f"\r   ⏳ Querying Plex{status_dots} (found {query_result['count']:,} tracks)", end='', flush=True)
                    else:
                        elapsed = int(time.time() - start_time)
                        print(f"\r   ⏳ Querying Plex{status_dots} ({elapsed}s)", end='', flush=True)
                    time.sleep(0.5)
            
            def run_query():
                """Run the actual query in background"""
                try:
                    result = music_library.search(libtype="track", filters={'userRating>=': 1}, limit=None)
                    query_result['items'] = result
                    query_result['count'] = len(result) if result else 0
                except Exception as e:
                    query_result['error'] = e
                finally:
                    query_done.set()
            
            # Start progress indicator thread
            progress_thread = threading.Thread(target=show_progress, daemon=True)
            progress_thread.start()
            
            # Start query thread
            query_thread = threading.Thread(target=run_query)
            query_thread.start()
            query_thread.join()
            
            query_done.set()
            time.sleep(0.6)  # Let progress indicator finish its last update
            
            elapsed_time = int(time.time() - start_time)
            
            if query_result['items'] is not None:
                liked_items = query_result['items']
                print(f"\r   ✅ Query complete! Found {len(liked_items):,} liked tracks (took {elapsed_time}s)")
                print(f"✅ Method 2 (search with userRating>=): Found {len(liked_items):,} liked tracks")
                sys.stdout.flush()
            else:
                print(f"\r   ❌ Query failed: {query_result['error']}")
                print(f"❌ Method 2 failed: {query_result['error']}")
                sys.stdout.flush()
        
        # Method 3: Try search with userRating__gte in filters
        if not liked_items:
            print()
            print("📡 Method 3: Trying search(libtype='track', filters={'userRating__gte': 1})...")
            print("   ⏳ Querying Plex...", end='', flush=True)
            
            query_done = threading.Event()
            query_result = {'items': None, 'error': None, 'count': 0}
            start_time = time.time()
            
            def show_progress():
                """Show progress dots while query is running"""
                dots = 0
                while not query_done.is_set():
                    dots = (dots + 1) % 4
                    status_dots = '.' * dots + ' ' * (3 - dots)
                    if query_result['count'] > 0:
                        print(f"\r   ⏳ Querying Plex{status_dots} (found {query_result['count']:,} tracks)", end='', flush=True)
                    else:
                        elapsed = int(time.time() - start_time)
                        print(f"\r   ⏳ Querying Plex{status_dots} ({elapsed}s)", end='', flush=True)
                    time.sleep(0.5)
            
            def run_query():
                """Run the actual query in background"""
                try:
                    result = music_library.search(libtype="track", filters={'userRating__gte': 1}, limit=None)
                    query_result['items'] = result
                    query_result['count'] = len(result) if result else 0
                except Exception as e:
                    query_result['error'] = e
                finally:
                    query_done.set()
            
            # Start progress indicator thread
            progress_thread = threading.Thread(target=show_progress, daemon=True)
            progress_thread.start()
            
            # Start query thread
            query_thread = threading.Thread(target=run_query)
            query_thread.start()
            query_thread.join()
            
            query_done.set()
            time.sleep(0.6)  # Let progress indicator finish its last update
            
            elapsed_time = int(time.time() - start_time)
            
            if query_result['items'] is not None:
                liked_items = query_result['items']
                print(f"\r   ✅ Query complete! Found {len(liked_items):,} liked tracks (took {elapsed_time}s)")
                print(f"✅ Method 3 (search with userRating__gte): Found {len(liked_items):,} liked tracks")
                sys.stdout.flush()
            else:
                print(f"\r   ❌ Query failed: {query_result['error']}")
                print(f"❌ Method 3 failed: {query_result['error']}")
                sys.stdout.flush()
        
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
                
                # Show progress every 1000 tracks or at the end
                if i % 1000 == 0 or i == len(all_tracks):
                    progress_percent = (i / len(all_tracks)) * 100 if all_tracks else 0
                    print(f"📊 Manual filtering: {i:,}/{len(all_tracks):,} tracks ({progress_percent:.1f}%) | Songs found: {len(liked_items):,}", end='\r')
                    sys.stdout.flush()
            
            print(f"\n✅ Manual filtering complete: Found {len(liked_items):,} liked tracks")
        
        if not liked_items:
            print("❌ No liked tracks found with any method. Please check:")
            print("1. Do you have tracks rated 1+ stars in Plex?")
            print("2. Are you logged in as the correct user?")
            print("3. Is your Plex server up to date?")
            return [], 0, []
        
        print(f"🎯 Found {len(liked_items):,} liked tracks, extracting artists...")
        print()
        
        # Extract artists with progress display
        for i, track in enumerate(liked_items, 1):
            artist_original = get_artist_name_original(track)
            artist_id = get_artist_id(track)
            
            if artist_original:
                artist_normalized = normalize_artist_name(artist_original)
                if artist_normalized:
                    liked_artists_normalized.add(artist_normalized)
                    # Store ID and name (preserve the first occurrence's casing)
                    if artist_normalized not in liked_artists_dict:
                        liked_artists_dict[artist_normalized] = {
                            "id": artist_id,
                            "name": artist_original
                        }
            
            # Show progress every 50 tracks or at the end
            if i % 50 == 0 or i == len(liked_items):
                progress_percent = (i / len(liked_items)) * 100
                print(f"📊 Processing: {i:,}/{len(liked_items):,} tracks ({progress_percent:.1f}%) | Songs found: {i:,} | Unique artists: {len(liked_artists_normalized):,}", end='\r')
                sys.stdout.flush()
        
        # Return list of artist info dicts (sorted for consistent output)
        artist_info_list = [liked_artists_dict[norm] for norm in sorted(liked_artists_normalized)]
        
        print()  # Clear the progress line
        print(f"✅ Extraction complete!")
        print(f"   📊 Total tracks processed: {len(liked_items):,}")
        print(f"   🎤 Unique artists found: {len(artist_info_list):,}")
        return artist_info_list, len(liked_items), liked_items
        
    except Exception as e:
        print(f"❌ Error fetching liked artists: {e}")
        import traceback
        traceback.print_exc()
        return [], 0, []


# Save liked artists to cache file
def save_liked_artists_cache(liked_artists_list, track_count, liked_tracks_list=None):
    """Save liked artists, track count, and liked tracks to cache file.
    liked_artists_list should be a list of dicts with 'id' and 'name' keys, or a list of strings (for backward compatibility).
    liked_tracks_list should be a list of track ratingKeys (for quick lookup)."""
    print("💾 Saving liked artists and tracks to cache...")
    try:
        # Handle both new format (dicts with id/name) and old format (strings) for backward compatibility
        if liked_artists_list and isinstance(liked_artists_list[0], dict):
            # New format: list of dicts with 'id' and 'name'
            sorted_artists = sorted(liked_artists_list, key=lambda x: x.get('name', '').lower())
            # Also create a simple name list for backward compatibility
            artist_names = [artist.get('name', '') for artist in sorted_artists if artist.get('name')]
        else:
            # Old format: list of strings
            sorted_artists = sorted(liked_artists_list) if liked_artists_list else []
            artist_names = sorted_artists
        
        # Extract track ratingKeys for caching
        liked_track_keys = []
        if liked_tracks_list:
            print(f"📝 Extracting track keys from {len(liked_tracks_list):,} liked tracks...")
            for track in liked_tracks_list:
                if hasattr(track, 'ratingKey'):
                    liked_track_keys.append(track.ratingKey)
            print(f"✅ Extracted {len(liked_track_keys):,} track keys")
        
        cache_data = {
            "liked_artists": artist_names,  # Backward compatible: simple list of names
            "liked_artists_detailed": sorted_artists,  # New format: list of dicts with id and name
            "liked_track_count": track_count,
            "liked_track_keys": liked_track_keys,
            "cache_timestamp": datetime.now().isoformat()
        }
        with open(LIKED_ARTISTS_CACHE_FILE, "w", encoding='utf-8') as file:
            json.dump(cache_data, file, indent=2, ensure_ascii=False)
        print(f"✅ Saved {len(artist_names):,} liked artists to cache (from {track_count:,} tracks)")
        if liked_track_keys:
            print(f"✅ Saved {len(liked_track_keys):,} liked track keys to cache")
        print(f"📅 Cache timestamp: {cache_data['cache_timestamp']}")
        print(f"📁 Cache file: {LIKED_ARTISTS_CACHE_FILE}")
    except Exception as e:
        print(f"❌ Error saving liked artists cache: {e}")
        import traceback
        traceback.print_exc()


# Merge artist lists from multiple sources, deduplicating by normalized names
def merge_artist_lists(*artist_lists):
    """Merge multiple lists of artists, deduplicating by normalized names.
    Handles both new format (dicts with 'id' and 'name') and old format (strings).
    Returns a list of dicts with 'id' and 'name' keys (preserving ID and name from first occurrence)."""
    merged_normalized = set()
    merged_dict = {}  # Maps normalized -> {"id": ratingKey, "name": original_name}
    
    for artist_list in artist_lists:
        for artist_item in artist_list:
            if artist_item:
                # Handle both new format (dict) and old format (string)
                if isinstance(artist_item, dict):
                    artist_name = artist_item.get('name', '')
                    artist_id = artist_item.get('id', None)
                else:
                    # Old format: just a string
                    artist_name = artist_item
                    artist_id = None
                
                if artist_name:
                    artist_normalized = normalize_artist_name(artist_name)
                    if artist_normalized and artist_normalized not in merged_normalized:
                        merged_normalized.add(artist_normalized)
                        # Prefer ID from first occurrence, but keep name from first occurrence
                        merged_dict[artist_normalized] = {
                            "id": artist_id,
                            "name": artist_name
                        }
    
    # Return sorted list of artist info dicts
    return [merged_dict[norm] for norm in sorted(merged_normalized)]


# Main function
def main():
    """Main function to fetch and save liked artists."""
    print("=" * 60)
    print("🎵 Fetch Liked Artists from Plex")
    print("=" * 60)
    print()
    
    # Fetch liked artists from both sources
    print("📊 Fetching liked artists from multiple sources...")
    print()
    
    # Source 1: Directly rated artists
    direct_artists = get_liked_artists_directly()
    print()
    
    # Source 2: Artists from liked tracks (also returns the tracks themselves)
    track_artists, track_count, liked_tracks = get_liked_artists_from_tracks()
    print()
    
    # Merge results from both sources
    print("🔄 Merging artists from all sources...")
    all_liked_artists = merge_artist_lists(direct_artists, track_artists)
    
    # Report summary
    print(f"📈 Summary:")
    print(f"   - Directly rated artists: {len(direct_artists):,}")
    print(f"   - Artists from liked tracks: {len(track_artists):,}")
    print(f"   - Total unique artists: {len(all_liked_artists):,}")
    # Count how many have IDs
    artists_with_ids = sum(1 for artist in all_liked_artists if isinstance(artist, dict) and artist.get('id'))
    if artists_with_ids > 0:
        print(f"   - Artists with IDs: {artists_with_ids:,}")
    if track_count > 0:
        print(f"   - Liked tracks processed: {track_count:,}")
    if liked_tracks:
        print(f"   - Liked track objects cached: {len(liked_tracks):,}")
    print()
    
    if not all_liked_artists:
        print("\n❌ No liked artists found. Exiting.")
        return
    
    # Save to cache (including liked tracks)
    save_liked_artists_cache(all_liked_artists, track_count, liked_tracks)
    
    print()
    print("=" * 60)
    print("✅ Successfully fetched and cached liked artists!")
    print("=" * 60)


# Run the script
if __name__ == "__main__":
    main()


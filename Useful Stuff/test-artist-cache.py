#!/usr/bin/env python3
"""
Test script to verify that all artists in the liked artists cache file
can be found in Plex and return data correctly.
"""

from plexapi.server import PlexServer
import json
import os
import unicodedata
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# Load environment variables
load_dotenv()

# Plex connection
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
LIKED_ARTISTS_CACHE_FILE = os.getenv("LIKED_ARTISTS_CACHE_FILE", "liked_artists_cache.json")

# Normalize artist name for consistent comparison
def normalize_artist_name(artist_name):
    """Normalize artist name for consistent comparison.
    Handles all Unicode characters (German ÄÖÜ, Cyrillic, Chinese, Japanese, etc.),
    various dash types, quote types, special symbols, whitespace, and more."""
    if not artist_name:
        return None
    
    # Normalize Unicode characters (NFC form - preserves special characters properly)
    # This handles composed vs decomposed forms (e.g., Ä vs A+̈)
    # NFC (Canonical Composition) is best for preserving international characters
    normalized = unicodedata.normalize('NFC', artist_name)
    
    # Remove zero-width characters (ZWNJ, ZWJ, etc.)
    normalized = normalized.replace('\u200B', '')  # Zero-width space
    normalized = normalized.replace('\u200C', '')  # Zero-width non-joiner
    normalized = normalized.replace('\u200D', '')  # Zero-width joiner
    normalized = normalized.replace('\uFEFF', '')  # Zero-width no-break space
    
    # Normalize various dash types to standard hyphen
    # Em dash (—), En dash (–), Figure dash (‒), Horizontal bar (―), etc.
    dash_variants = [
        '\u2014',  # Em dash
        '\u2013',  # En dash
        '\u2012',  # Figure dash
        '\u2015',  # Horizontal bar
        '\u2010',  # Hyphen
        '\u2011',  # Non-breaking hyphen
        '\u2043',  # Hyphen bullet
        '\u2212',  # Minus sign
        '\uFF0D',  # Full-width hyphen-minus
    ]
    for dash in dash_variants:
        normalized = normalized.replace(dash, '-')
    
    # Normalize various quote types to standard quotes
    # Left/Right single quotes, left/right double quotes, etc.
    quote_pairs = [
        ('\u2018', "'"),  # Left single quotation mark
        ('\u2019', "'"),  # Right single quotation mark / apostrophe
        ('\u201A', "'"),  # Single low-9 quotation mark
        ('\u201B', "'"),  # Single high-reversed-9 quotation mark
        ('\u201C', '"'),  # Left double quotation mark
        ('\u201D', '"'),  # Right double quotation mark
        ('\u201E', '"'),  # Double low-9 quotation mark
        ('\u201F', '"'),  # Double high-reversed-9 quotation mark
        ('\uFF02', '"'),  # Full-width quotation mark
        ('\uFF07', "'"),  # Full-width apostrophe
    ]
    for old_char, new_char in quote_pairs:
        normalized = normalized.replace(old_char, new_char)
    
    # Normalize various space types to standard space
    space_variants = [
        '\u00A0',  # Non-breaking space
        '\u2000',  # En quad
        '\u2001',  # Em quad
        '\u2002',  # En space
        '\u2003',  # Em space
        '\u2004',  # Three-per-em space
        '\u2005',  # Four-per-em space
        '\u2006',  # Six-per-em space
        '\u2007',  # Figure space
        '\u2008',  # Punctuation space
        '\u2009',  # Thin space
        '\u200A',  # Hair space
        '\u202F',  # Narrow no-break space
        '\u205F',  # Medium mathematical space
        '\u3000',  # Ideographic space (CJK)
    ]
    for space in space_variants:
        normalized = normalized.replace(space, ' ')
    
    # Strip leading/trailing whitespace
    normalized = normalized.strip()
    
    # Normalize whitespace around slashes and other separators
    normalized = normalized.replace(' / ', '/').replace('/ ', '/').replace(' /', '/')
    normalized = normalized.replace(' & ', '&').replace('& ', '&').replace(' &', '&')
    normalized = normalized.replace(' + ', '+').replace('+ ', '+').replace(' +', '+')
    normalized = normalized.replace(' x ', ' x ').replace(' x', ' x').replace('x ', ' x ')
    
    # Normalize multiple spaces to single space (handles all Unicode space types now)
    normalized = ' '.join(normalized.split())
    
    # Remove combining marks that might cause issues (but preserve them for actual characters)
    # This is a careful balance - we want to preserve actual accented characters
    # but remove stray combining marks
    
    return normalized


# Test a single artist - simplified to just check if artist has 1+ songs in Plex
def test_artist(plex, artist_name):
    """Test if an artist can be found in Plex by searching for tracks.
    Returns True if artist has 1 or more songs, False otherwise."""
    try:
        # Get music library
        music_library = plex.library.section("Music")
        
        # Method 1: Search for the artist by title, then get their tracks
        # This is the most reliable method
        try:
            artists = music_library.search(libtype="artist", title=artist_name, limit=None)
            if artists and len(artists) > 0:
                # Found artist(s), get tracks from the first matching artist
                artist = artists[0]
                tracks = artist.tracks()
                if tracks and len(tracks) >= 1:
                    return {
                        "artist_name": artist_name,
                        "valid": True,
                        "track_count": len(tracks),
                        "error": None
                    }
        except Exception as e1:
            # Try next method
            pass
        
        # Method 2: Try with normalized name if different
        normalized_name = normalize_artist_name(artist_name)
        if normalized_name and normalized_name != artist_name:
            try:
                artists = music_library.search(libtype="artist", title=normalized_name, limit=None)
                if artists and len(artists) > 0:
                    artist = artists[0]
                    tracks = artist.tracks()
                    if tracks and len(tracks) >= 1:
                        return {
                            "artist_name": artist_name,
                            "valid": True,
                            "track_count": len(tracks),
                            "error": None
                        }
            except Exception as e2:
                pass
        
        # Method 3: Try case-insensitive search by getting all artists and matching
        # This handles cases where Plex stores names with different casing
        try:
            all_artists = music_library.search(libtype="artist", limit=None)
            normalized_cache_name = normalize_artist_name(artist_name)
            
            if normalized_cache_name:
                normalized_cache_name_lower = normalized_cache_name.lower()
                for artist in all_artists:
                    try:
                        artist_title = artist.title
                        normalized_artist_title = normalize_artist_name(artist_title)
                        if normalized_artist_title and normalized_artist_title.lower() == normalized_cache_name_lower:
                            # Found matching artist
                            tracks = artist.tracks()
                            if tracks and len(tracks) >= 1:
                                return {
                                    "artist_name": artist_name,
                                    "valid": True,
                                    "track_count": len(tracks),
                                    "error": None
                                }
                    except:
                        continue
        except Exception as e3:
            pass
        
        # If no tracks found, artist is invalid
        return {
            "artist_name": artist_name,
            "valid": False,
            "track_count": 0,
            "error": None
        }
            
    except Exception as e:
        return {
            "artist_name": artist_name,
            "valid": False,
            "track_count": 0,
            "error": str(e)
        }

# Save cache with validation status
def save_cache_with_validation(cache_data, validation_results):
    """Update cache file with validation results."""
    # Create validation mapping: artist_name -> {"valid": bool, "track_count": int, "validated_at": timestamp}
    validation_map = {}
    from datetime import datetime
    validation_timestamp = datetime.now().isoformat()
    
    for result in validation_results:
        validation_map[result["artist_name"]] = {
            "valid": result["valid"],
            "track_count": result["track_count"],
            "validated_at": validation_timestamp
        }
        if result["error"]:
            validation_map[result["artist_name"]]["error"] = result["error"]
    
    # Update cache data
    cache_data["validation"] = validation_map
    cache_data["validation_timestamp"] = validation_timestamp
    
    # Save updated cache
    try:
        with open(LIKED_ARTISTS_CACHE_FILE, "w", encoding="utf-8") as file:
            json.dump(cache_data, file, indent=2, ensure_ascii=False)
        print(f"✅ Updated cache file with validation results")
    except Exception as e:
        print(f"❌ Error saving cache file: {e}")

# Main test function
def main():
    print("=" * 80)
    print("Artist Cache Validation Test")
    print("=" * 80)
    print()
    
    # Check Plex connection
    if not PLEX_URL or not PLEX_TOKEN:
        print("❌ ERROR: PLEX_URL and PLEX_TOKEN must be set in .env file")
        return
    
    # Connect to Plex
    print(f"🔌 Connecting to Plex server: {PLEX_URL}")
    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        print("✅ Connected to Plex server")
    except Exception as e:
        print(f"❌ Failed to connect to Plex server: {e}")
        return
    
    print()
    
    # Load cache file (full data structure, not just artist list)
    if not os.path.exists(LIKED_ARTISTS_CACHE_FILE):
        print(f"❌ Cache file not found: {LIKED_ARTISTS_CACHE_FILE}")
        return
    
    try:
        with open(LIKED_ARTISTS_CACHE_FILE, "r", encoding="utf-8") as file:
            cache_data = json.load(file)
            cached_artists = cache_data.get("liked_artists", [])
            print(f"📁 Loaded {len(cached_artists)} artists from cache file")
    except Exception as e:
        print(f"❌ Error loading cache file: {e}")
        return
    
    if not cached_artists:
        print("❌ No artists found in cache file")
        return
    
    print()
    print(f"🧪 Testing {len(cached_artists)} artists against Plex...")
    print("   (An artist is valid if Plex returns 1 or more songs)")
    print()
    
    # Test artists with threading for speed
    results = []
    valid_count = 0
    invalid_count = 0
    
    # Use threading for faster testing with progress bar
    num_workers = min(20, max(5, len(cached_artists) // 10))  # 5-20 workers depending on artist count
    
    with tqdm(total=len(cached_artists), desc="Testing artists", unit="artist", 
              bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            # Submit all tasks
            future_to_artist = {executor.submit(test_artist, plex, artist): artist for artist in cached_artists}
            
            # Process completed tasks
            for future in as_completed(future_to_artist):
                result = future.result()
                results.append(result)
                
                if result["valid"]:
                    valid_count += 1
                else:
                    invalid_count += 1
                
                # Update progress bar
                pbar.update(1)
                pbar.set_postfix({
                    "valid": valid_count,
                    "invalid": invalid_count,
                    "valid_pct": f"{valid_count/len(results)*100:.1f}%" if results else "0%"
                })
    
    print(f"\n✅ Testing complete!")
    print()
    
    # Sort results by valid status, then by track count
    results.sort(key=lambda x: (not x["valid"], -x["track_count"]))
    
    # Save validation results to cache
    print("💾 Updating cache file with validation results...")
    save_cache_with_validation(cache_data, results)
    print()
    
    # Summary statistics
    print("=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"Total artists tested: {len(results)}")
    print(f"✅ Valid artists (1+ songs): {valid_count} ({valid_count/len(results)*100:.1f}%)")
    print(f"❌ Invalid artists (0 songs): {invalid_count} ({invalid_count/len(results)*100:.1f}%)")
    print()
    
    if valid_count > 0:
        total_tracks = sum(r["track_count"] for r in results if r["valid"])
        avg_tracks = total_tracks / valid_count if valid_count > 0 else 0
        print(f"📊 Average tracks per valid artist: {avg_tracks:.1f}")
        print(f"📊 Total tracks from valid artists: {total_tracks:,}")
        print()
    
    print()
    print("=" * 80)
    print("INVALID ARTISTS (No songs found in Plex)")
    print("=" * 80)
    
    invalid_artists = [r for r in results if not r["valid"]]
    if invalid_artists:
        for i, result in enumerate(invalid_artists, 1):
            print(f"{i}. {result['artist_name']}")
            if result["error"]:
                print(f"   Error: {result['error']}")
    else:
        print("🎉 All artists are valid!")
    
    print()
    print("=" * 80)
    print("ARTISTS WITH MOST TRACKS (Top 20)")
    print("=" * 80)
    
    top_artists = sorted([r for r in results if r["valid"]], key=lambda x: x["track_count"], reverse=True)[:20]
    for i, result in enumerate(top_artists, 1):
        print(f"{i:2}. {result['artist_name']:40} {result['track_count']:5} tracks")
    
    print()
    print("=" * 80)
    print("DETAILED RESULTS")
    print("=" * 80)
    print("(Showing first 50 results for brevity)")
    print()
    
    for i, result in enumerate(results[:50], 1):
        status = "✅" if result["valid"] else "❌"
        print(f"{status} {result['artist_name']}")
        if result["valid"]:
            print(f"   Tracks: {result['track_count']}")
        if result["error"]:
            print(f"   Error: {result['error']}")
    
    if len(results) > 50:
        print(f"\n... and {len(results) - 50} more artists")
    
    print()
    print("=" * 80)
    print("Test complete! Cache file updated with validation results.")
    print("=" * 80)

if __name__ == "__main__":
    main()


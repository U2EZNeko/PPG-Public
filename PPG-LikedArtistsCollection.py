from plexapi.server import PlexServer
import json
import os
import time
from tqdm import tqdm
from module.ppg_run_logger import (
    fail_playlist,
    finish_run,
    playlist_succeeded,
    record_playlist_result,
    start_run,
)
from module.ppg_single_playlist import skip_unless_target_playlist
from module.ppg_track_filters import filter_tracks_by_title_album_regex, load_skip_title_album_regexes

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


if load_dotenv:
    load_dotenv()


def validate_env_vars(required_vars, script_name):
    missing_vars = []
    for var in required_vars:
        value = os.getenv(var)
        if value is None or value.strip() == "":
            missing_vars.append(var)
    if missing_vars:
        print(f"❌ ERROR: Missing required environment variables for {script_name}:")
        for var in missing_vars:
            print(f"   - {var}")
        raise SystemExit(1)


REQUIRED_ENV_VARS = [
    "PLEX_URL",
    "PLEX_TOKEN",
    "LIKED_ARTISTS_CACHE_FILE",
]
validate_env_vars(REQUIRED_ENV_VARS, "PPG-LikedArtistsCollection.py")


PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
LIKED_ARTISTS_CACHE_FILE = os.getenv("LIKED_ARTISTS_CACHE_FILE")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

_SKIP_SONG_TITLE_RE, _SKIP_ALBUM_TITLE_RE = load_skip_title_album_regexes()


LOG_LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}


def log(level, message):
    if LOG_LEVELS.get(level, 1) >= LOG_LEVELS.get(LOG_LEVEL, 1):
        print(message)


def normalize_artist_name(artist_name):
    if not artist_name:
        return None
    import unicodedata

    normalized = unicodedata.normalize("NFC", artist_name).strip()
    normalized = normalized.replace(" / ", "/").replace("/ ", "/").replace(" /", "/")
    normalized = " ".join(normalized.split())
    return normalized


def load_liked_artists_cache():
    """Returns list of dicts: {normalized, name, id} sorted by name."""
    if not os.path.exists(LIKED_ARTISTS_CACHE_FILE):
        log("ERROR", f"❌ Cache file not found: {LIKED_ARTISTS_CACHE_FILE}")
        return []

    with open(LIKED_ARTISTS_CACHE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    detailed = data.get("liked_artists_detailed", [])
    legacy = data.get("liked_artists", [])

    artists = []
    if detailed and isinstance(detailed[0], dict):
        for a in detailed:
            name = a.get("name", "")
            if not name:
                continue
            artists.append(
                {
                    "normalized": normalize_artist_name(name) or name,
                    "name": name,
                    "id": a.get("id"),
                }
            )
    else:
        for name in legacy:
            if isinstance(name, str) and name.strip():
                artists.append(
                    {
                        "normalized": normalize_artist_name(name) or name,
                        "name": name.strip(),
                        "id": None,
                    }
                )

    # de-dupe by normalized name (prefer entries with IDs)
    by_norm = {}
    for a in artists:
        k = a["normalized"]
        if k not in by_norm or (not by_norm[k].get("id") and a.get("id")):
            by_norm[k] = a

    result = list(by_norm.values())
    result.sort(key=lambda x: (x["name"] or "").casefold())
    return result


def get_artist_object(music_library, artist):
    """artist: dict with {name, id}"""
    artist_id = artist.get("id")
    artist_name = artist.get("name")

    if artist_id:
        try:
            obj = music_library.fetchItem(artist_id)
            if obj and getattr(obj, "type", None) == "artist":
                return obj
        except Exception as e:
            log("DEBUG", f"⚠️  Could not fetch artist by ID {artist_id}: {e}")

    try:
        hits = music_library.searchArtists(title=artist_name)
        if hits:
            # prefer exact normalized match
            target_norm = normalize_artist_name(artist_name)
            for h in hits:
                if normalize_artist_name(getattr(h, "title", "")) == target_norm:
                    return h
            return hits[0]
    except Exception as e:
        log("WARNING", f"⚠️  Error searching artist '{artist_name}': {e}")

    return None


def get_all_tracks_for_artist(artist_obj):
    """Best-effort fetch of all tracks for an artist."""
    # Fast path: artist.tracks()
    try:
        if hasattr(artist_obj, "tracks"):
            tracks = artist_obj.tracks()
            if tracks:
                return list(tracks)
    except Exception as e:
        log("DEBUG", f"⚠️  artist.tracks() failed for '{getattr(artist_obj, 'title', 'Unknown')}': {e}")

    # Fallback: albums -> tracks
    tracks = []
    try:
        if hasattr(artist_obj, "albums"):
            albums = artist_obj.albums()
            for album in albums or []:
                try:
                    if hasattr(album, "tracks"):
                        tracks.extend(album.tracks() or [])
                except Exception:
                    continue
    except Exception as e:
        log("WARNING", f"⚠️  artist.albums()->tracks failed for '{getattr(artist_obj, 'title', 'Unknown')}': {e}")

    return tracks


def track_sort_key(track):
    album = getattr(track, "parentTitle", "") or ""
    disc = getattr(track, "parentIndex", 0) or 0
    idx = getattr(track, "index", 0) or 0
    title = getattr(track, "title", "") or ""
    return (album.casefold(), disc, idx, title.casefold())


def build_liked_artists_collection():
    playlist_title = "Liked Artists Collection"
    build_start = time.time()
    if skip_unless_target_playlist(playlist_title):
        log("INFO", "Skipping — single-playlist target does not match Liked Artists Collection.")
        return

    log("INFO", "🔌 Connecting to Plex server...")
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    music = plex.library.section("Music")

    artists = load_liked_artists_cache()
    if not artists:
        log("ERROR", "❌ No liked artists found in cache.")
        fail_playlist("(setup)", "No liked artists in cache")
        record_playlist_result(
            playlist_title,
            time.time() - build_start,
            False,
            "No liked artists in cache",
        )
        return

    log("INFO", f"✅ Loaded {len(artists):,} liked artists from cache")

    try:
        all_tracks_ordered = []
        total_tracks = 0

        for artist in tqdm(artists, desc="Processing artists", unit="artist"):
            name = artist.get("name", "Unknown")
            artist_obj = get_artist_object(music, artist)
            if not artist_obj:
                log("WARNING", f"⚠️  Could not find artist in Plex: {name}")
                continue

            tracks = get_all_tracks_for_artist(artist_obj)
            if not tracks:
                log("WARNING", f"⚠️  No tracks found for artist: {name}")
                continue

            # Keep stable order within artist
            tracks = sorted(tracks, key=track_sort_key)

            all_tracks_ordered.extend(tracks)
            total_tracks += len(tracks)

        all_tracks_ordered = filter_tracks_by_title_album_regex(
            all_tracks_ordered,
            _SKIP_SONG_TITLE_RE,
            _SKIP_ALBUM_TITLE_RE,
            lambda msg: log("INFO", msg),
        )

        if not all_tracks_ordered:
            log("ERROR", "❌ No tracks collected. Playlist not updated.")
            fail_playlist("Liked Artists Collection", "No tracks collected from Plex")
            record_playlist_result(
                playlist_title,
                time.time() - build_start,
                False,
                "No tracks collected from Plex",
            )
            return

        total_tracks_collected = len(all_tracks_ordered)

        def add_items_batched(pl, items, batch_size=500):
            total = len(items)
            for start in range(0, total, batch_size):
                batch = items[start : start + batch_size]
                pl.addItems(batch)
                log("INFO", f"  ➕ Added {min(start + len(batch), total):,}/{total:,} tracks")

        # Create or update playlist
        existing = None
        try:
            existing_titles = [pl.title for pl in plex.playlists()]
            if playlist_title in existing_titles:
                existing = plex.playlist(playlist_title)
        except Exception:
            existing = None

        if existing:
            log("INFO", f"🔄 Updating existing playlist: {playlist_title}")
            try:
                existing.removeItems(existing.items())
            except Exception as e:
                log("WARNING", f"⚠️  Could not clear playlist items cleanly: {e}")
            playlist = existing
        else:
            log("INFO", f"✨ Creating new playlist: {playlist_title}")
            # PlexAPI requires at least one item when creating a playlist
            first_batch = all_tracks_ordered[:1]
            playlist = plex.createPlaylist(playlist_title, items=first_batch)
            all_tracks_ordered = all_tracks_ordered[1:]

        # Add items in grouped-by-artist order
        if all_tracks_ordered:
            log("INFO", f"➕ Adding {len(all_tracks_ordered):,} tracks to playlist...")
            add_items_batched(playlist, all_tracks_ordered, batch_size=500)

        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        playlist.editSummary(
            f"Built from liked artists cache\nUpdated on: {timestamp}\nArtists: {len(artists):,}\nTracks: {total_tracks_collected:,}"
        )

        log("INFO", f"✅ Playlist '{playlist_title}' updated with {total_tracks_collected:,} tracks (grouped by artist)")
        playlist_succeeded()
        record_playlist_result(
            playlist_title,
            time.time() - build_start,
            True,
            "",
        )
    except Exception as e:
        log("ERROR", f"❌ {playlist_title} failed: {e}")
        fail_playlist(playlist_title, str(e))
        record_playlist_result(
            playlist_title,
            time.time() - build_start,
            False,
            str(e)[:400],
        )
        raise


if __name__ == "__main__":
    import sys

    start_run("PPG-LikedArtistsCollection.py")
    try:
        t0 = time.time()
        build_liked_artists_collection()
        log("INFO", f"⏱️  Done in {time.time() - t0:.1f}s")
    finally:
        exc = sys.exc_info()
        crashed = exc[0] is not None and not issubclass(exc[0], SystemExit)
        finish_run(had_exception=crashed)


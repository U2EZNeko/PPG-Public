from plexapi.server import PlexServer
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tqdm import tqdm
from module.ppg_plex_retry import call_plex_with_retry
from module.ppg_run_logger import (
    fail_playlist,
    finish_run,
    playlist_succeeded,
    record_playlist_result,
    set_status,
    start_run,
)
from module.ppg_single_playlist import skip_unless_target_playlist
from module.ppg_track_filters import (
    filter_tracks_by_title_album_regex,
    load_skip_title_album_regexes,
)

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


if load_dotenv:
    load_dotenv(override=True)


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
    "MIN_SONG_DURATION_SECONDS",
]
validate_env_vars(REQUIRED_ENV_VARS, "PPG-LikedArtistsCollection.py")


PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
LIKED_ARTISTS_CACHE_FILE = os.getenv("LIKED_ARTISTS_CACHE_FILE")
MIN_SONG_DURATION_SECONDS = int(os.getenv("MIN_SONG_DURATION_SECONDS"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LAC_KEYS_CACHE_FILE = Path(
    os.getenv(
        "LIKED_ARTISTS_COLLECTION_KEYS_CACHE_FILE",
        "webui/data/liked_artists_collection_keys_cache.json",
    )
)
LAC_REMOVE_WORKERS = max(
    1,
    min(16, int(os.getenv("LIKED_ARTISTS_COLLECTION_REMOVE_WORKERS", "6"))),
)

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


def _load_keys_cache():
    try:
        if not LAC_KEYS_CACHE_FILE.is_file():
            return None
        data = json.loads(LAC_KEYS_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        keys = data.get("keys")
        if not isinstance(keys, list):
            return None
        return [str(k) for k in keys if str(k).strip()]
    except Exception:
        return None


def _save_keys_cache(keys):
    try:
        LAC_KEYS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"keys": [str(k) for k in keys], "updated_at": time.time()}
        LAC_KEYS_CACHE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log("WARNING", f"⚠️  Could not update keys cache: {e}")


def get_track_duration_seconds(track):
    """Get the track duration in seconds."""
    try:
        if hasattr(track, "duration"):
            duration_ms = track.duration
            if duration_ms:
                return duration_ms / 1000.0
        return None
    except Exception as e:
        log(
            "DEBUG",
            f"⚠️  Error getting duration for track '{getattr(track, 'title', 'Unknown')}': {e}",
        )
        return None


def filter_by_minimum_duration(tracks, min_duration_seconds):
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
    return filtered, removed


def build_liked_artists_collection():
    playlist_title = "Liked Artists Collection"
    build_start = time.time()
    if skip_unless_target_playlist(playlist_title):
        log("INFO", "Skipping — single-playlist target does not match Liked Artists Collection.")
        return

    log("INFO", "🔌 Connecting to Plex server...")
    set_status("Connecting to Plex...")
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)
    music = plex.library.section("Music")

    set_status("Loading liked artists cache...")
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
    set_status(f"Processing artists (0/{len(artists):,})...")

    try:
        all_tracks_ordered = []
        total_tracks = 0
        artists_with_tracks = 0

        for idx, artist in enumerate(
            tqdm(artists, desc="Processing artists", unit="artist"), start=1
        ):
            if idx == 1 or idx % 25 == 0 or idx == len(artists):
                set_status(f"Processing artists ({idx:,}/{len(artists):,})...")
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
            tracks, removed_short = filter_by_minimum_duration(
                tracks, MIN_SONG_DURATION_SECONDS
            )
            if removed_short:
                log(
                    "INFO",
                    f"⏱️  Min duration removed {removed_short} track(s) for artist '{name}'",
                )
            if not tracks:
                log(
                    "WARNING",
                    f"⚠️  All tracks filtered out by min duration for artist: {name}",
                )
                continue

            pre_filter_count = len(tracks)
            tracks = filter_tracks_by_title_album_regex(
                tracks,
                _SKIP_SONG_TITLE_RE,
                _SKIP_ALBUM_TITLE_RE,
                None,
            )
            removed_for_artist = pre_filter_count - len(tracks)
            if removed_for_artist:
                log(
                    "INFO",
                    f"🚫 Regex removed {removed_for_artist} track(s) for artist '{name}'",
                )
            if not tracks:
                log(
                    "WARNING",
                    f"⚠️  All tracks filtered out by title/album regex for artist: {name}",
                )
                continue

            all_tracks_ordered.extend(tracks)
            total_tracks += len(tracks)
            artists_with_tracks += 1
        log(
            "INFO",
            f"📊 Artist pass complete: {artists_with_tracks:,}/{len(artists):,} artists contributed tracks",
        )
        set_status(
            f"Artist pass complete ({artists_with_tracks:,} contributors). Preparing playlist sync..."
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
        log("INFO", f"📦 Total tracks queued for playlist: {total_tracks_collected:,}")

        def add_items_batched(pl, items, batch_size=500):
            total = len(items)
            if total <= 0:
                return
            batch_starts = range(0, total, batch_size)
            for start in tqdm(
                batch_starts,
                total=(total + batch_size - 1) // batch_size,
                desc="Uploading track batches",
                unit="batch",
            ):
                batch = items[start : start + batch_size]
                call_plex_with_retry(
                    lambda b=batch: pl.addItems(b),
                    log_fn=lambda m: log("WARNING", m),
                    op_label=f"Plex addItems batch ({len(batch)} tracks) to {playlist_title!r}",
                )
                log("INFO", f"  ➕ Added {min(start + len(batch), total):,}/{total:,} tracks")

        def track_key(track):
            rk = getattr(track, "ratingKey", None)
            return str(rk) if rk is not None else ""

        desired_keys_all = [k for k in (track_key(t) for t in all_tracks_ordered) if k]

        def plan_playlist_delta(existing_items, desired_items):
            t_delta = time.time()
            log(
                "INFO",
                f"🔎 Computing playlist delta (existing {len(existing_items):,} vs desired {len(desired_items):,})...",
            )
            existing_counts = Counter()
            desired_counts = Counter()
            for item in existing_items:
                k = track_key(item)
                if k:
                    existing_counts[k] += 1
            for item in desired_items:
                k = track_key(item)
                if k:
                    desired_counts[k] += 1

            to_remove = []
            removal_budget = {
                k: max(0, existing_counts.get(k, 0) - desired_counts.get(k, 0))
                for k in existing_counts
            }
            for item in existing_items:
                k = track_key(item)
                if not k:
                    continue
                if removal_budget.get(k, 0) > 0:
                    to_remove.append(item)
                    removal_budget[k] -= 1

            to_add = []
            add_budget = {
                k: max(0, desired_counts.get(k, 0) - existing_counts.get(k, 0))
                for k in desired_counts
            }
            for item in desired_items:
                k = track_key(item)
                if not k:
                    continue
                if add_budget.get(k, 0) > 0:
                    to_add.append(item)
                    add_budget[k] -= 1

            log(
                "INFO",
                f"✅ Delta computed in {time.time() - t_delta:.1f}s (remove {len(to_remove):,}, add {len(to_add):,})",
            )
            return to_remove, to_add

        def remove_items_batched(pl, items, batch_size=500):
            total = len(items)
            if total <= 0:
                return
            batches = [items[start : start + batch_size] for start in range(0, total, batch_size)]
            done_tracks = 0
            set_status(
                f"Removing stale tracks ({total:,}) using {LAC_REMOVE_WORKERS} worker(s)..."
            )

            def _remove_batch(batch):
                call_plex_with_retry(
                    lambda b=batch: pl.removeItems(b),
                    log_fn=lambda m: log("WARNING", m),
                    op_label=f"Plex removeItems batch ({len(batch)} tracks) from {playlist_title!r}",
                )
                return len(batch)

            with ThreadPoolExecutor(max_workers=LAC_REMOVE_WORKERS) as pool:
                futures = [pool.submit(_remove_batch, b) for b in batches]
                with tqdm(
                    total=len(futures),
                    desc=f"Removing stale batches ({LAC_REMOVE_WORKERS} workers)",
                    unit="batch",
                ) as pbar:
                    for i, fut in enumerate(as_completed(futures), start=1):
                        n = fut.result()
                        done_tracks += n
                        pbar.update(1)
                        if i == 1 or i % 10 == 0 or i == len(futures):
                            set_status(
                                f"Removing stale tracks: {done_tracks:,}/{total:,} done"
                            )
                        log(
                            "INFO",
                            f"  ➖ Removed {done_tracks:,}/{total:,} stale tracks",
                        )

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
            cached_keys = _load_keys_cache()
            if cached_keys is not None and cached_keys == desired_keys_all:
                log("INFO", "⚡ Cache hit: desired key list unchanged from last successful sync.")
                log("INFO", "✅ Skipping playlist delta sync (no changes detected).")
                set_status("No changes detected from cached keys; skipping playlist sync.")
                all_tracks_ordered = []
            else:
                set_status("Loading existing playlist items...")
            try:
                if all_tracks_ordered:
                    with tqdm(total=3, desc="Updating existing playlist", unit="step") as update_bar:
                        t_existing = time.time()
                        existing_items = existing.items()
                        update_bar.set_postfix_str(f"loaded {len(existing_items):,} existing tracks")
                        update_bar.update(1)
                        log("INFO", f"📥 Loaded existing playlist items in {time.time() - t_existing:.1f}s")
                        set_status("Computing add/remove delta...")
                        t_plan = time.time()
                        to_remove, to_add = plan_playlist_delta(existing_items, all_tracks_ordered)
                        update_bar.set_postfix_str(
                            f"delta: remove {len(to_remove):,}, add {len(to_add):,}"
                        )
                        update_bar.update(1)
                        log("INFO", f"🧮 Delta planning step finished in {time.time() - t_plan:.1f}s")
                        if to_remove:
                            set_status(f"Removing stale tracks ({len(to_remove):,})...")
                            t_remove = time.time()
                            remove_items_batched(existing, to_remove, batch_size=500)
                            log("INFO", f"🧹 Removed stale tracks in {time.time() - t_remove:.1f}s")
                        update_bar.set_postfix_str("applied removals")
                        update_bar.update(1)
                    if not to_remove and not to_add:
                        log("INFO", "✅ Playlist already up to date (no add/remove delta).")
                        set_status("Playlist already up to date.")
                    else:
                        log(
                            "INFO",
                            f"🧮 Delta plan ready: remove {len(to_remove):,}, add {len(to_add):,}",
                        )
                        set_status(f"Delta ready: add {len(to_add):,} track(s).")
                    all_tracks_ordered = to_add
            except Exception as e:
                log("WARNING", f"⚠️  Could not clear playlist items cleanly: {e}")
                set_status("Could not fully clear stale tracks; continuing with add phase...")
            playlist = existing
        else:
            log("INFO", f"✨ Creating new playlist: {playlist_title}")
            set_status("Creating playlist...")
            # PlexAPI requires at least one item when creating a playlist
            first_batch = all_tracks_ordered[:1]
            playlist = call_plex_with_retry(
                lambda: plex.createPlaylist(playlist_title, items=first_batch),
                log_fn=lambda m: log("WARNING", m),
                op_label=f"Plex create playlist {playlist_title!r}",
            )
            all_tracks_ordered = all_tracks_ordered[1:]

        # Add items in grouped-by-artist order
        if all_tracks_ordered:
            log("INFO", f"➕ Adding {len(all_tracks_ordered):,} tracks to playlist...")
            set_status(f"Adding tracks in batches ({len(all_tracks_ordered):,} total)...")
            add_items_batched(playlist, all_tracks_ordered, batch_size=500)
        else:
            set_status("No additions required.")

        # Mark playlist success as soon as the playlist content update is complete.
        # This keeps external run-state reporting accurate even if later metadata calls fail.
        playlist_succeeded()

        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            playlist.editSummary(
                f"Built from liked artists cache\nUpdated on: {timestamp}\nArtists: {len(artists):,}\nTracks: {total_tracks_collected:,}"
            )
        except Exception as e:
            log("WARNING", f"⚠️  Could not update playlist summary: {e}")

        log("INFO", f"✅ Playlist '{playlist_title}' updated with {total_tracks_collected:,} tracks (grouped by artist)")
        set_status("Finalizing run...")
        _save_keys_cache(desired_keys_all)
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


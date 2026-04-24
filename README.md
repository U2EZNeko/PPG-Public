# PPG - Plex Playlist Generator

**Automation scripts to generate music Playlists on your Plex Server.** 

**Since Spotify disabled playlists through their API, I had to do it myself.**


![Daily](https://github.com/user-attachments/assets/b8c2842a-84d9-433e-a5d1-0367af1799d6)

![Weekly](https://github.com/user-attachments/assets/bbfd1053-b59e-4b52-b2e2-3958ff299e2a)

### Introduction

These scripts are designed for rather big Plex instances, it will work with smaller databases but will obviously be less random.

I run the scripts with cronjobs to generate playlists for me. My Plex has over 300k tracks on it, your experience may vary.

I'm more than happy to extend the scripts myself and through your Pull Requests. 

The .json files can easily be extended, you can find a list of genres and moods in the .idea folder -> Usefulstuff Folder contains genres.txt it's a list of all unique genres on MY server. You may have a genre on your server that I do not have.

**Genre JSON — two files:** `daily_weekly_genre_pools.json` is only for **PPG-Daily / PPG-Weekly** (each entry is a *pool*; each playlist randomly uses one pool). `named_genre_mix_playlists.json` is only for **PPG-Genres** (each entry becomes a Plex playlist `{name} Mix`). Same JSON shape; different scripts. I used AI to help author these; keep pool/mix *names* distinct so logs and playlists stay readable.

### Content table

- [Introduction](#introduction)
- [Requirements](#requirements)
- [Setup](#setup)
- [Web UI](#web-ui)
  - [Mobile-compatible UI](#mobile-compatible-ui)
  - [Screenshots](#web-ui-screenshots)
- [Telegram notifications](#telegram-notifications)
- [Track filters (regex)](#track-filters-regex)
- [Cronjob Examples](#cronjob-examples)
- [Shared Python module](#shared-python-module)
- [Usage Description](#usage-description)
  - [PPG-Daily and PPG-Weekly](#ppg-daily-and-ppg-weekly)
  - [PPG-Moods](#ppg-moods)
  - [PPG-Genres](#ppg-genres)
  - [Fetch-Artist-Cache](#fetch-artist-cache)
  - [Copy-Playlist-To-Subuser](#copy-playlist-to-subuser)
- [Update Log](#update-log)
- [Information](#information)
- [Not Working](#not-working)
- [Planned](#planned)

### Requirements:
  - Plex server and Access Token (Navigate to some item on your Plex -> click "view XML" -> Copy token from URL
  - Python3

### Setup:
  1. Grab your Plex Token and IP and put it into the .env (remove the example from the file name). If you are upgrading from an older tree, rename `genre_groups.json` → `daily_weekly_genre_pools.json` and `genre_mixes.json` → `named_genre_mix_playlists.json` (or set `DAILY_GENRE_GROUPS_FILE`, `WEEKLY_GENRE_GROUPS_FILE`, and `GENRE_MIXES_FILE` to your old paths).
  2. **Dependencies:** Use a virtual environment (required on Debian/Ubuntu and other distros that show `externally-managed-environment` / PEP 668):
     ```bash
     cd /path/to/PPG
     python3 -m venv .venv
     .venv/bin/pip install -r requirements.txt
     ```
     Run scripts with `.venv/bin/python PPG-Daily.py` (etc.) or activate the venv first. For the web UI systemd unit, point `ExecStart` at `.venv/bin/python webui/app.py`.
  3. Test run the script once, check your Playlists.
  4. Optional: Set Playlist posters manually, there's no way to do it through API.
     I've included a few obviously self-drawn examples. ;)
  5. Create cronjobs/Windows Scheduled Tasks (Make sure to use full paths in the config and your cronjob)
  6. **Optional — Web UI:** install dependencies (`flask` is in `requirements.txt`), then run from the repo root:
     ```bash
     python webui/app.py
     ```
     Bind address defaults come from `webui/config.json`; override with `PPG_WEB_HOST` and `PPG_WEB_PORT` in `.env` (see `example.env`). Use a real browser for best results (mobile layout and live logs are tuned for normal clients).

## Web UI

The **PPG Web UI** (`webui/app.py`) is a local Flask app to run the same generator scripts you would start from the CLI, watch **live stdout**, edit **genre / mood / pool JSON**, browse and save **`.env`**, manage **Plex playlists** linked to PPG, and inspect **run statistics** from `log.txt` without leaving the browser.

<img width="2544" height="650" alt="image" src="https://github.com/user-attachments/assets/4df764fe-6b7f-4d72-bd3e-cf6f9e32c909" />


### Tabs

| Tab | Purpose |
| --- | --- |
| **Scripts** | Start Daily / Weekly / Genres / Moods / Liked Artists (and related flows). One output card per script with progress and a live log streamed over SSE. |
| **Errors** | Playlist-level failures surfaced during runs (also persisted in the browser). Points you to chronic failure tracking in **Statistics** when the same title keeps failing. |
| **Group JSON** | Load and edit `daily_weekly_genre_pools.json`, `named_genre_mix_playlists.json`, `mood_groups.json`, etc., with search and structure helpers. |
| **Configs** | View and edit environment variables (backed by project `.env`). |
| **Playlists** | List Plex music playlists, filter, **multi-select**, delete with an in-page confirmation dialog (not `window.confirm`), and trigger **regenerate** for PPG-managed titles where supported. |
| **Statistics** | Aggregates from `log.txt`: slowest successful builds, failed playlists, runs per script, recent runs, and **Playlists needing attention** (see below). |

### Runs, reconnects, and statistics

- Subprocesses are started **on the server**; closing a tab does **not** stop a run. Reopening the UI (or reconnecting the event stream) **reloads buffered output** and continues live updates.
- Completed jobs expose **`GET /api/job/<job_id>/info`** so the page can recover **exit code** and **done** state even if the browser missed the last SSE message.
- **Structured events** for each run are appended to `webui/data/ppg_events.jsonl`. Active web-started jobs are also tracked under `webui/data/active_web_jobs.json` so a **server restart** can reconnect to still-running PIDs when possible.
- **Chronic failures:** repeated failures for the same real playlist title (streak resets after a **successful** build) are recorded in `webui/data/playlist_chronic_failures.json` and listed under **Statistics → Playlists needing attention**. Threshold: `PPG_CHRONIC_FAILURE_THRESHOLD` (default **3**); see `example.env`.

### Mobile-compatible UI

The Web UI is built to work on **phones and tablets**, not only desktop:

- **Viewport:** `viewport-fit=cover` so notched devices respect **safe-area** insets; padding on `.wrap` uses `env(safe-area-inset-*)` so content stays clear of the status bar and home indicator.
- **Full width:** The main column uses the **whole screen width** (no narrow max-width column), with comfortable side padding that tightens slightly on very small screens.
- **Navigation:** Tab labels (**Scripts**, **Errors**, **Group JSON**, etc.) sit in a **horizontally scrollable** strip. On narrow screens you **swipe** the strip to reach **Statistics** and the rest. The scrollbar uses **`overflow-x: auto`**, so it **only appears when the row actually overflows** (no permanent empty scrollbar on desktop).
- **Sticky tabs (tablet / narrow desktop):** On viewports up to ~960px wide, the tab bar can **stick** under the top of the viewport while you scroll long pages (e.g. Statistics), so you can switch tabs without scrolling back up.
- **Touch-friendly:** Run buttons and other controls use **larger tap targets** where it matters; output and playlist tables use **horizontal scrolling** inside their panels so wide tables do not blow up the page layout.
- **Dialogs:** Destructive actions (for example **deleting Plex playlists**) use an **in-page `<dialog>`** with proper focus and layout on small screens instead of the browser’s tiny `confirm()` box.
- **Live logs:** Script output panes and the JSON editor use **dynamic viewport units (`dvh`)** where helpful so visible height adapts on mobile browsers with collapsing chrome.

Use a normal mobile browser (or responsive mode in devtools) for the best match; embedded preview panes may not reproduce scrolling and touch behavior perfectly.

### Configuration highlights (`example.env`)

- **`PPG_MIN_SONGS_REQUIRED_PERCENT`** — optional **global** minimum pool size as a fraction of `SONGS_PER_PLAYLIST` for all generators; when set, you can rely on this instead of each script’s own min-percent variable.
- **`PPG_CHRONIC_FAILURE_THRESHOLD`** — consecutive failures before a playlist is flagged for review (see above).
- **`PPG_WEB_HOST` / `PPG_WEB_PORT`** — Web UI bind address.
- **`TELEGRAM_*`** — see [Telegram notifications](#telegram-notifications).
- **`SKIP_SONG_TITLE_REGEX` / `SKIP_ALBUM_TITLE_REGEX`** — see [Track filters (regex)](#track-filters-regex).

### Dev server console

When you run `webui/app.py` in a terminal, high-frequency **`GET /api/status`** polling is **not** printed for every request. Other requests are summarized in a **rolling “last 10”** panel in the **lower half** of the terminal (upper half stays as the normal Flask banner). This keeps logs readable while you develop.

### Web UI screenshots


| Suggested file | What to show |
| --- | --- |
| <img width="2544" height="650" alt="image" src="https://github.com/user-attachments/assets/5e07730b-0ad7-4303-9c49-562c26848932" />
 | **Scripts** — grid of generators + live log / progress |
| <img width="2534" height="557" alt="image" src="https://github.com/user-attachments/assets/86e32d1e-dc4a-4c00-8f2f-7ff75f98e2c6" />
 | **Playlists** — list, search, selection, delete/regenerate |
| <img width="2535" height="603" alt="image" src="https://github.com/user-attachments/assets/7ba6c6ed-57af-45a9-a985-2bc86bcaa483" />
| **Statistics** — slowest builds, failures, **Playlists needing attention** |
| <img width="2525" height="721" alt="image" src="https://github.com/user-attachments/assets/543778f9-474f-46c2-9c60-cd56bb861eee" />
 | **Group JSON** editor (optional) |


## Telegram notifications

Optional **Telegram** messages when a **generator run finishes** (success or uncaught crash), so you get a summary on your phone without watching the console. This applies to runs started from the **CLI**, **cron / Task Scheduler**, or the **Web UI** (the UI runs the same scripts as subprocesses).

**What you get in one message (typical):**

- Script name and optional run id  
- Total **duration**  
- **Result** (completed vs crashed)  
- Count of playlists updated successfully  
- **Per-playlist** lines with duration and ok/failed (and short failure notes when present)  
- A **Failures** section when anything failed  

Long summaries are **truncated** to Telegram’s size limit (~4096 characters) with a clear “truncated” marker.

**Environment variables** (set in `.env`; see `example.env`):

| Variable | Meaning |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather). |
| `TELEGRAM_CHAT_ID` | Chat or channel id to send to (numeric id or string for supergroups). |
| `TELEGRAM_NOTIFICATIONS` | If `false`, `0`, `no`, or `off`, **no messages are sent** but tokens stay in `.env` (handy for testing). Default behavior sends when token + chat are set. |

If either **token** or **chat id** is missing, nothing is sent (no error). Failed HTTP calls are printed to **stderr** only.

Implementation lives in **`module/ppg_telegram.py`** and is invoked from the shared run logger when a run completes. Dependencies: **`requests`** (already in `requirements.txt`).

## Track filters (regex)

You can **globally exclude** tracks from generator pools and candidate lists by matching **song title** and/or **album title** with **Python regular expressions** (case-insensitive). This is useful for skits, live-only cuts, demos, interludes, or any pattern you want to keep out of automated playlists.

**Environment variables** (in `.env`):

| Variable | Effect |
| --- | --- |
| `SKIP_SONG_TITLE_REGEX` | If non-empty, any track whose **title** matches this regex is dropped. |
| `SKIP_ALBUM_TITLE_REGEX` | If non-empty, any track whose **album** title matches this regex is dropped. |

**Rules:**

- Matching is **case-insensitive** (`IGNORECASE` + `UNICODE`).  
- Leave a variable **empty or unset** to disable that side of the filter.  
- If a regex is **invalid**, the process **exits immediately** with a clear error on stderr (fail-fast so you do not get silent “no filters” behavior).  
- When tracks are removed, scripts log a short line (for example how many were removed from the pool vs the current candidate list).

**Where it applies:** the filters are loaded in **PPG-Daily**, **PPG-Weekly**, **PPG-Genres**, **PPG-Moods**, **PPG-LikedArtists**, **PPG-LikedArtistsCollection**, and **fetch-liked-artists** so cached liked data and generated playlists stay consistent with the same rules.

**Example** (one line in `.env`; adjust for your library):

```env
# Example: drop obvious skits / live / demo patterns (tune to taste)
SKIP_SONG_TITLE_REGEX=\b(skit|live(\s+from|\s+at)?|demo(\s+version)?|interlude|acoustic session)\b
```

`example.env` includes commented examples and notes for these variables.

Implementation: **`module/ppg_track_filters.py`**.

## Shared Python module

Shared helpers live under **`module/`** (import as `module.*` from repo root scripts): run logging and `log.txt` / `ppg_events.jsonl`, minimum-song / pool thresholds, track title/album regex filters, single-playlist (`PPG_ONLY_PLAYLIST_TITLE`) helpers, Telegram summaries, and **chronic failure** tracking for the Web UI. Generator scripts at the repo root stay the main entry points.

# Cronjob examples:

![cron](https://github.com/user-attachments/assets/94063b48-99f4-42f7-b149-6034984218fe)



Make sure to remove the "/user/bin/xterm -hold -e" if you do not want your terminal window to stay open. I just like seeing that it ran through over night.



# Usage description:

### PPG-Daily and PPG-Weekly
  
  These are there to replace Spotify's Daily Mixes and Weekly Mixes

  They randomly pick **one entry** from `daily_weekly_genre_pools.json` for each new playlist (each entry is a *pool* of Plex genres, not a separate Plex playlist name).

  It writes used pools to a log file to avoid repeating the same pool too soon.

  JSON example
```
   "Rock": ["Classic Rock", "Alternative Rock", "Hard Rock", "Indie Rock", "Psychedelic Rock", "Grunge", "Proto-punk"],
```
### PPG-Moods
  
  Used to update "mood Mix", similar to Spotify.

  You can set the moods to create mixes for in mood_groups.
  
  JSON example
```
    "Melancholy": [
    "Melancholy",
    "Sad",
    "Wistful",
    "Lonely",
    "Nostalgic",
    "Poignant",
    "Somber"
  ]
  ```

### PPG-Genres
  
  Creates or updates "genre Mix" playlists, similar to Spotify.

  Definitions live in `named_genre_mix_playlists.json`: one Plex playlist per key, named `{key} Mix`.

  This allows you to select multiple similar genres and pick random songs from those. You can also extend the json entry with a date filter, you can chose before, after or between release years. 

  Since plex does not save the release date for each song, I have to use the Album's year to filter. This still does the same, the problem is Plex being unable to keep up with my database so I'm missing a bunch of metadata.

  JSON example
```
  "90s Gangster Rap Underground": {
    "genres": [
      "Country rap",
      "Rap/r&b",
      "Cali rap",
      "Pop rap / rock",
      "Vapor trap",
      "Gangsta rap",
      "Mixtape"
    ],
    "release_date_filter": {
      "condition": "between",
      "start_date": "1990",
      "end_date": "1999"
    }
  },
  ```

### PPG-LikedArtists

  Uses Liked artists to create playlists.
  
  Should use similar artists or similar tracks depending on the playlist. 


### Fetch-liked-artists
  
  Fetches liked artists from Plex and writes them to a cache file.
  
  Will fetch directly liked artists and grabs artists from liked tracks. 

  Best to run once weekly, takes a hot minute to fetch all data.

  Also now fetches all liked songs for faster access.


### Copy-Playlist-To-Subuser

  As the name suggests, lets you copy playlists to sub-users. 

  You will have to set Posters manually.

  To get sub-user plex token:
  
  Log into sub user -> Go to some item -> CTRL Shift I -> Go to network tab -> Find "x-Plex-Token" in the Header (might need to click on another item with the network tab open)

  Largely deprecated now that they actually show shared playlists in Plexamp


![collection](https://github.com/user-attachments/assets/1862f8eb-1854-41c3-b288-f6c39a4cb0b2)

# Update log

### 23.04.2026:

- **Web UI:** Scripts, Errors, Group JSON, Configs, Playlists (multi-select delete + confirm dialog, regenerate), Statistics; **full-width**, **mobile-oriented** layout (safe areas, sticky tabs on smaller viewports, horizontal tab strip with overflow only when needed, touch-friendly controls, in-page dialogs, `dvh`-aware panes).
- **Run recovery:** server-side job buffers, SSE reconnect, `GET /api/job/<id>/info`, and polling so finished runs report exit state even if the tab was closed or the stream dropped.
- **Chronic failures:** `webui/data/playlist_chronic_failures.json`, Statistics section **Playlists needing attention**, `PPG_CHRONIC_FAILURE_THRESHOLD`.
- **Telegram:** optional end-of-run summaries via `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (`module/ppg_telegram.py`); `TELEGRAM_NOTIFICATIONS=false` disables sends without removing credentials.
- **Track filters:** `SKIP_SONG_TITLE_REGEX` and `SKIP_ALBUM_TITLE_REGEX` in `.env` for case-insensitive exclusion by track/album title across generators and liked-artist tooling (`module/ppg_track_filters.py`).
- **Config:** optional global `PPG_MIN_SONGS_REQUIRED_PERCENT` for minimum pool size across generators (`example.env`).
- **Code layout:** shared helpers in **`module/`** (`ppg_run_logger`, `ppg_min_songs`, `ppg_chronic_failures`, `ppg_track_filters`, `ppg_single_playlist`, etc.).
- **Dev UX:** quieter Flask access log; rolling last-10 HTTP summary in the lower half of the terminal.

### 10.11.2025:

  - Added PPG-LikedArtists
  - Uses cache to get artists and creates a playlist with similar songs or artists.
  - Cache file will now hold all liked tracks. 


### 03.11.2025:

  - Liked artist fetching is now its own script
  - Automatically sets posters for genre and mood mixes (yoinked from Spotify)
  - Added cache validation script. (only checks if the artist in cache returns any songs)
  - Removed caching code from scripts

### 29.10.2025:
  - Date filters for genre pools / named mixes (JSON entries)
  - Multithreading!
  - Log levels
  - Moved everything to .env (scripts check for all values)
  - Mood-grouping for final track list (not possible all the time, Plex doesnt hold this all the time)
  - Prevent consecutive artists in playlists
  - Prevent multiple songs from single albums spamming playlists
  - Progress Bars!
  - Turns out theres never been a requirements.txt lol

### 27.10.2025:

  - Added randomized playlist posters

### 24.10.2025:

  - Moved most config values to .env, alternatively you can still define them in the scripts.
  - Hopefully final adjustment to Description
  - Updated the groups a bit
  - Prettied up output
  - Used AI to comment out code because im lazy
  - Fixed playlist shuffler, only works on regular playlists (Useful for smart home automations that cannot use the shuffle function)

### 03.10.2025:

  - Added Preference for liked artists
  - Added logic to avoid artists filling whole playlists
  - Clearer debug output

### 16.01.2025:

  - Added before, between and after time filters.   
  - Added logging to reduce getting the same playlists.
  - Removed useless fetch of all available genres from Daily script.


# Information:

- We're getting into territories with filters that will one way or another take a while to run. I'm multithreading a few things where possible but on slower CPUs this will be unavoidable.
  The bigger your library the more fetching it has to do, with my close to 400k track library fetching certain genres returns a solid 20k+ songs, running through all those will take a while. 

- I've created this script using a database of 300k+ songs. This left me with over 4000 unique genres and 300 moods which should cover quite a broad spectrum of songs.

- If you run the script through cronjobs, use full paths to the jsons and log files!

- If you add genre pools, named genre mixes, or mood_groups, make each top-level key unique (it identifies the pool or the `{name} Mix` playlist).

- Because sometimes the scripts cannot find enough songs to fill a playlist, it will try again if it cannot find at least 80% (can be defined in the script) of the SONGS_PER_PLAYLIST. It will retry this 10 times.

- The script is supposed to add used genres to the Playlist Description. This works on my PC but not on my VM for some reason, i had to change 2 lines of code there, check the "Not Working" section.

- Depending on your database size and processor power it may take a good chunk of time to fetch the unique genres and songs. This is expected, not much you can do to speed it up.

- Here's how you can get your own Spotify thumbnails: 

  https://seed-mix-image.spotifycdn.com/v6/img/desc/Nevergonnagiveyouupnevergonnaletyoudown/en/default


![example](https://github.com/user-attachments/assets/e7d246cb-2d09-4632-8778-c093415ccbf3)


# Update infos:


  change the URL to whatever you want and save the image. ezpz
  (or add the link directly in Plex)

  Update:
  - Date filters for genre pools / named mixes (JSON entries)
  - Multithreading! - For fetching operations and filtering
  - Log levels
  - Moved everything to .env (scripts check for all values)
  - Mood-grouping for final track list (not possible all the time, Plex doesnt hold this all the time)
  - Prevent consecutive artists in playlists
  - Prevent multiple songs from single albums spamming playlists
  - Progress Bars!
  - Turns out theres never been a requirements.txt lol


  27.10.2025 Update:
  - Added a toggle-able option to replace Playlist Posters on every run
    Will not use a poster twice per run, you can easily add your own to the folder. 
    Images are AI generated, if you end up making cool ones go ahead and add them to the repo. 

    UPDATE_POSTERS=true  is the .env value, it's true by default. Sorry if it replaced your images.
  
  
  24.10.2025 Update:
  - Config values were moved to .env, check example.env to see whats available. 
    Make sure you use full paths for log files just to be sure.
    Alternatively you can always have a value after the .env reference, i kept them in the scripts so everyone sees how. 


  03.10.2025 Update:

  - Liked Artist Preference:
    
    Once a week, the scripts will fetch all liked tracks and extract the artists from it.
    It will cache this data. Limited to Weekly as it can take forever to do on large libraries. Mine takes a solid 10 minutes. lol

    This should ensure more relevant playlists as a whole, I've tested it a bunch and I like it. 

    You can set a percentage of how many liked artist tracks to use in the script.
    Enabled by default, can be disabled for playlists in the json's like this.
```
  "Rock": {
    "genres": ["Classic Rock", "Alternative Rock", "Hard Rock", "Indie Rock", "Psychedelic Rock", "Grunge", "Proto-punk"],
    "prefer_liked_artists": true
  },
  "Classical": {
    "genres": ["Classical Music", "Baroque", "Opera", "Romantic Classical", "Classical Crossover", "Symphonic", "Chamber Music"],
    "prefer_liked_artists": false
  }
```

  - The scripts will now check a playlist once created and re-fetch tracks if an artist takes too many slots.
    
    Can be configured in the script.


# Not working

- Older versions of PlexAPI do not have "existing_playlist.editSummary". To set a Summary on an old version change the previous to "existing_playlist.edit(summary=f"Genres used: {genre_description}")"

# Planned

- Prefer artists the user has listened to before?
  This would probably have to be cached as it would take a long long time to fetch. Not sure if its worth yet. 

- Come up with more useful filters
  Tried but not working: BPM, Moods (semi working)

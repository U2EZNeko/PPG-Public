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

I used AI to generate the genre_groups, you can do the same by feeding it both files or at least the json formatting and genres. Make sure the "name" of the genre_group is unique and avoid creating groups that are too similar to each other. 

### Content table

- [Introduction](#introduction)
- [Requirements](#requirements)
- [Setup](#setup)
  - [Cronjob Examples](#cronjob-examples)
- [Usage Description](#usage-description)
  - [PPG-Daily and PPG-Weekly](#ppg-daily-and-ppg-weekly)
  - [PPG-Moods](#ppg-moods)
  - [PPG-Genres](#ppg-genres)
  - [Copy-Playlist-To-Subuser](#copy-playlist-to-subuser)
- [Update Log](#update-log)
- [Information](#information)
- [Not Working](#not-working)
- [Planned](#planned)

### Requirements:
  - Plex server and Access Token (Navigate to some item on your Plex -> click "view XML" -> Copy token from URL
  - Python3

### Setup:
  1. Grab your Plex Token and IP and put it into the .env (remove the example from the file name)
  2. Install plexapi through Python. (python -m pip install plexapi)
  3. Test run the script once, check your Playlists.
  4. Optional: Set Playlist posters manually, there's no way to do it through API.
     I've included a few obviously self-drawn examples. ;)
  5. Create cronjobs/Windows Scheduled Tasks (Make sure to use full paths in the config and your cronjob)

# Cronjob examples:

![cron](https://github.com/user-attachments/assets/94063b48-99f4-42f7-b149-6034984218fe)



Make sure to remove the "/user/bin/xterm -hold -e" if you do not want your terminal window to stay open. I just like seeing that it ran through over night.



# Usage description:

### PPG-Daily and PPG-Weekly
  
  These are there to replace Spotify's Daily Mixes and Weekly Mixes

  They will randomly select from genre_groups.json to create playlists.

  It will write the used genre's to a log file to avoid duplicates.

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

  This will create or update playlists containing multiple genres, defined in genre_mixes.json

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

### Copy-Playlist-To-Subuser

  As the name suggests, lets you copy playlists to sub-users. 

  You will have to set Posters manually.

  To get sub-user plex token:
  
  Log into sub user -> Go to some item -> CTRL Shift I -> Go to network tab -> Find "x-Plex-Token" in the Header (might need to click on another item with the network tab open)


![collection](https://github.com/user-attachments/assets/1862f8eb-1854-41c3-b288-f6c39a4cb0b2)

# Update log


### 16.01.2025:

  -   Added before, between and after time filters.   
  -   Added logging to reduce getting the same playlists.
  -   Removed useless fetch of all available genres from Daily script.


# Information:

- I've created this script using a database of 300k+ songs. This left me with over 4000 unique genres and 300 moods which should cover quite a broad spectrum of songs.

- If you run the script through cronjobs, use full paths to the jsons and log files!

- If you add genre_groups or mood_groups, make their name unique!

- Because sometimes the scripts cannot find enough songs to fill a playlist, it will try again if it cannot find at least 80% (can be defined in the script) of the SONGS_PER_PLAYLIST. It will retry this 10 times.

- The script is supposed to add used genres to the Playlist Description. This works on my PC but not on my VM for some reason, i had to change 2 lines of code there, check the "Not Working" section.

- Depending on your database size and processor power it may take a good chunk of time to fetch the unique genres and songs. This is expected, not much you can do to speed it up.

- Here's how you can get your own Spotify thumbnails: 

  https://seed-mix-image.spotifycdn.com/v6/img/desc/Nevergonnagiveyouupnevergonnaletyoudown/en/default


![example](https://github.com/user-attachments/assets/e7d246cb-2d09-4632-8778-c093415ccbf3)



  change the URL to whatever you want and save the image. ezpz
  (or add the link directly in Plex)


# Not working

- Setting a playlist Poster through API. You can set it once manually and it'll keep it forever. When you copy it to a sub-user the image will reset on their end, not sure why, you'd have to reset it everytime you copy the playlist over. 
- Older versions of PlexAPI do not have "existing_playlist.editSummary". To set a Summary on an old version change the previous to "existing_playlist.edit(summary=f"Genres used: {genre_description}")"

# Planned

- Extend genre_groups even more

  A lot of genre_groups are rather wide spread or have too many genres in them. Gonna need some manual fine tuning eventually.

- Come up with more useful filters

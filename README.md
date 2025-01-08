# PPG - Plex Playlist Generator

An automation script to generate daily/weekly music Playlists on your Plex Server. 
Since Spotify disabled playlists through their API, I had to do it myself.


### Requirements:
  - Plex server and Access Token
  - Python3

### Setup:
  1. Grab your Plex Token and IP and put it into the .env
  2. Install plexapi through Python. (python -m pip install plexapi)
  3. Test run the script once, check your Playlists.
  4. Optional: Set Playlist posters manually, there's no way to do it through API.
     I've included a few obviously self-drawn examples. ;)
  5. Create cronjobs/Windows Scheduled Tasks




## Information:

- I've created this script using a database of 300k+ songs. This left me with over 9000 unique genres which should cover quite a broad spectrum of songs.


- The script uses "Genre Groups" to combine multiple genres into a group and then randomly selects the set amount of songs to add. The json is formatted like this:

  "Rock": ["Classic Rock", "Alternative Rock", "Hard Rock", "Indie Rock", "Psychedelic Rock", "Grunge", "Proto-punk"],

  You can easily add your own genre_groups, just make sure it's a unique name. If you do, I'd appreciate if you share them.


- Because sometimes the script cannot find enough songs to fill a playlist, it will try again if it cannot find at least 80% of the SONGS_PER_PLAYLIST. It will retry this 10 times.

- The script is supposed to add used genres to the Playlist Description. This works on my PC but not on my VM for some reason.

- Depending on your database size and processor power it may take a good chunk of time to fetch the unique genres. This is expected, not much you can do to speed it up.



# PPG - Plex Playlist Generator

![wqeqwqeweweqw](https://github.com/user-attachments/assets/e8b22003-7b5a-4ee5-b445-518f276078b5)

![asdasdsa](https://github.com/user-attachments/assets/f2f51b93-aeef-4db8-aa4d-2c1dcc037fbd)


An automation script to generate daily/weekly music Playlists on your Plex Server. 
Since Spotify disabled playlists through their API, I had to do it myself.

This script is designed for rather big Plex instances, it will work with smaller databases but will obviously be less random.
I run this script once daily and once weekly to generate playlists for me. My Plex has over 300k tracks on it, your experience may vary.

I'm more than happy to extend this script myself and through your Pull Requests. 
The file genre_groups.json can easily be extended, you can find a list of genres in the genres.txt -> genres.txt is a list of all unique genres on MY server. You may have a genre on your server that I do not have.
I used AI to generate the genre_groups, you can do the same by feeding it both files or at least the json formatting. Make sure the "name" of the genre_group is unique.



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

## Not working

- Setting a playlist Poster through API. You can set it once manually and it'll keep it forever.
- Older versions of PlexAPI do not have "existing_playlist.editSummary". To set a Summary on an old version change the previous to "existing_playlist.edit(summary=f"Genres used: {genre_description}")"

## Planned

- Use "moods" that plex provides like genres
- Use user data to personalize playlists more. (prefer frequently played artists, do not include recently played songs etc.)
- Some sorta logging to avoid generating too similar playlists repeatedly or at least since last run.
- Extend genre_groups even more

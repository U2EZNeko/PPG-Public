# PPG - Plex Playlist Generator
Automation scripts to generate music Playlists on your Plex Server. 

Since Spotify disabled playlists through their API, I had to do it myself.


![Daily](https://github.com/user-attachments/assets/b8c2842a-84d9-433e-a5d1-0367af1799d6)

![Weekly](https://github.com/user-attachments/assets/bbfd1053-b59e-4b52-b2e2-3958ff299e2a)


These scripts are designed for rather big Plex instances, it will work with smaller databases but will obviously be less random.

I run the scripts with cronjobs to generate playlists for me. My Plex has over 300k tracks on it, your experience may vary.

I'm more than happy to extend the scripts myself and through your Pull Requests. 

The .json files can easily be extended, you can find a list of genres and moods in the .idea folder -> genres.txt is a list of all unique genres on MY server. You may have a genre on your server that I do not have.

I used AI to generate the genre_groups, you can do the same by feeding it both files or at least the json formatting. Make sure the "name" of the genre_group is unique.



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

Cronjob examples:

![cron](https://github.com/user-attachments/assets/94063b48-99f4-42f7-b149-6034984218fe)





Make sure to remove the "/user/bin/xterm -hold -e" if you do not want your terminal window to stay open. I just like seeing that it ran through over night.



## Usage description:

- PPG-Daily and PPG-Weekly
  
  These are there to replace Spotify's Daily Mixes and Weekly Mixes

  They will randomly select from genre_groups.json to create playlists

- PPG-Moods
  
  Used to update "mood Mix", similar to Spotify.

  You can set the moods to create mixes for in mood_groups. 

- PPG-Genres
  
  Creates or updates "genre Mix" playlists, similar to Spotify.

  This will create or update playlists containing multiple genres, defined in genre_mixes.json

  This allows you to select multiple similar genres and pick random songs from those. 

- Copy-Playlist-To-Subuser

  As the name suggests, lets you copy playlists to sub-users. 

  You will have to set Posters manually.

  To get sub-user plex token:
  
  Log into sub user -> Go to some item -> CTRL Shift I -> Go to network tab -> Find "x-Plex-Token" in the Header (might need to click on another item with the network tab open)


![collection](https://github.com/user-attachments/assets/1862f8eb-1854-41c3-b288-f6c39a4cb0b2)




## Information:

- I've created this script using a database of 300k+ songs. This left me with over 4000 unique genres and 300 moods which should cover quite a broad spectrum of songs.


- The script uses json files to combine multiple genres/moods into a group and then randomly selects the set amount of songs to add. The jsons are formatted like this:

  "Rock": ["Classic Rock", "Alternative Rock", "Hard Rock", "Indie Rock", "Psychedelic Rock", "Grunge", "Proto-punk"],

  You can easily add your own genre_groups or mood_groups just make sure it's a unique name. If you do, I'd appreciate if you share them.


- Because sometimes the scripts cannot find enough songs to fill a playlist, it will try again if it cannot find at least 80% (can be defined in the script) of the SONGS_PER_PLAYLIST. It will retry this 10 times.

- The script is supposed to add used genres to the Playlist Description. This works on my PC but not on my VM for some reason, i had to change 2 lines of code there, check the "Not Working" section.

- Depending on your database size and processor power it may take a good chunk of time to fetch the unique genres and songs. This is expected, not much you can do to speed it up.

- Here's how you can get your own Spotify thumbnails: 

  https://seed-mix-image.spotifycdn.com/v6/img/desc/Nevergonnagiveyouupnevergonnaletyoudown/en/default


![example](https://github.com/user-attachments/assets/e7d246cb-2d09-4632-8778-c093415ccbf3)



  change the URL to whatever you want and save the image. ezpz
  (or add the link directly in Plex)


## Not working

- Setting a playlist Poster through API. You can set it once manually and it'll keep it forever.
- Older versions of PlexAPI do not have "existing_playlist.editSummary". To set a Summary on an old version change the previous to "existing_playlist.edit(summary=f"Genres used: {genre_description}")"

## Planned

- Some sorta logging to avoid generating too similar playlists repeatedly or at least since last run.
- Extend genre_groups even more

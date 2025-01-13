from plexapi.server import PlexServer
from dotenv import load_dotenv
import os

# Load environment variables from the .env file
load_dotenv()

# Fetch the Plex server credentials from environment variables
PLEX_URL = os.getenv('PLEX_URL')
PLEX_TOKEN = os.getenv('PLEX_TOKEN')

# Ensure credentials are loaded
if not PLEX_URL or not PLEX_TOKEN:
    raise ValueError("PLEX_URL and PLEX_TOKEN must be set in the .env file")

# Connect to the Plex server
plex = PlexServer(PLEX_URL, PLEX_TOKEN)

# Fetch your music library
music_library = plex.library.section('Music')  # Replace 'Music' with the name of your music library if different

# Fetch all genres
genres = music_library.listFilterChoices('genre')

# Write genres to a text file with utf-8 encoding
output_file = "genresnew.txt"
with open(output_file, "w", encoding="utf-8") as file:
    file.write("Genres in your music library:\n")
    for genre in genres:
        file.write(f"{genre.title}\n")

print(f"Genres have been written to {output_file}")

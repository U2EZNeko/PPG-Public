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

# Fetch all moods
moods = music_library.listFilterChoices('mood')

# Write moods to a text file with utf-8 encoding
output_file = "moods.txt"
with open(output_file, "w", encoding="utf-8") as file:
    file.write("Moods in your music library:\n")
    for mood in moods:
        file.write(f"{mood.title}\n")

print(f"Moods have been written to {output_file}")

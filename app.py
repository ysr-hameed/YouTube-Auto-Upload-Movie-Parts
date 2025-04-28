import json
import os
import random
import ffmpeg
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# Settings
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920  # Increased video height
WATERMARK_TEXT = "Subscribe my channel @Quote Zen"
FONTFILE = "Poppins-Bold.ttf"  # Update if needed
TOKEN_FILE = "tokens.json"  # Store the tokens for each user
MOVIES_FILE = "movies.json"
OUTPUT_FILE = "final_video.mp4"
PROGRESS_FILE = "progress.json"

MIN_PART_DURATION = 40  # seconds
MAX_PART_DURATION = 60  # seconds
SKIP_START = 120  # seconds
SKIP_END = 120  # seconds

# Load tokens from the JSON file
def load_tokens():
    with open(TOKEN_FILE, 'r') as f:
        return json.load(f)

# Save progress
def save_progress(current_start, part_number, durations, movie_name):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({
            "current_start": current_start,
            "part_number": part_number,
            "durations": durations,
            "movie_name": movie_name  # Save the current movie name
        }, f)

# Load progress from the progress.json file
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                progress = json.load(f)
                if "movie_name" not in progress:
                    progress["movie_name"] = ""  # Initialize if it's missing
                return progress
        except json.JSONDecodeError:
            print("Error: progress.json is empty or invalid. Initializing with default values.")
            return {
                "current_start": 350,
                "part_number": 1,
                "durations": [],
                "movie_name": ""  # Initialize movie_name to avoid KeyError
            }
    else:
        return {
            "current_start": 350,
            "part_number": 1,
            "durations": [],
            "movie_name": ""  # Initialize movie_name to avoid KeyError
        }

# Create video part (with audio)
def create_part(url, start_time, duration, output_file, part_number, movie_name):
    try:
        input_stream = ffmpeg.input(url, ss=start_time, t=duration)
        
        video = (
            input_stream
            .filter('scale', VIDEO_WIDTH, -1)  
            .filter('pad', VIDEO_WIDTH, VIDEO_HEIGHT, '(ow-iw)/2', '(oh-ih)/2', color='white')  
            .drawtext(
                fontfile=FONTFILE,
                text=f'{movie_name} - Part {part_number}',
                fontsize=65,
                fontcolor='black',
                x='(w-text_w)/2',
                y='225',  
                shadowcolor='white',
                shadowx=2,
                shadowy=2
            )
            .drawtext(
                fontfile=FONTFILE,
                text=WATERMARK_TEXT,
                fontsize=45,
                fontcolor='black',
                x='(w-text_w)/2',
                y='h-120',  
                shadowcolor='white',
                shadowx=2,
                shadowy=2
            )
        )

        audio_stream = input_stream.audio
        (
            ffmpeg
            .output(video, audio_stream, output_file, vcodec='libx264', acodec='aac', strict='experimental', preset='ultrafast')
            .overwrite_output()
            .run()
        )
        print(f"Created Part {part_number}: {output_file} ({duration} sec)")
    except ffmpeg.Error as e:
        print(f"FFmpeg Error: {e}")

# Upload video to YouTube
def upload_to_youtube(file, title, description, tags, token_data):
    try:
        credentials = Credentials.from_authorized_user_info(info=token_data)
        youtube = build('youtube', 'v3', credentials=credentials)

        request_body = {
            'snippet': {
                'title': title,
                'description': description,
                'tags': tags
            },
            'status': {
                'privacyStatus': 'public',
            }
        }

        media = MediaFileUpload(file, mimetype='video/mp4', resumable=True)

        request = youtube.videos().insert(
            part="snippet,status",
            body=request_body,
            media_body=media
        )

        response = request.execute()
        print(f"Video uploaded successfully! Video ID: {response['id']}")
    except HttpError as error:
        print(f"An error occurred during upload: {error}")

# Load movie details from movies.json
def load_movies():
    if os.path.exists(MOVIES_FILE):
        with open(MOVIES_FILE, 'r') as f:
            return json.load(f)
    return []

# Save movie details to movies.json
def save_movie(movie_data):
    movies = load_movies()
    movies.append(movie_data)
    with open(MOVIES_FILE, 'w') as f:
        json.dump(movies, f)


def get_video_duration(video_path):
    try:
        probe = ffmpeg.probe(video_path)
        streams = probe.get('streams', [])
        if streams:
            # find the first video stream
            video_stream = next((stream for stream in streams if stream.get('codec_type') == 'video'), None)
            if video_stream:
                duration = video_stream.get('duration')
                if duration:
                    return float(duration)
        
        # fallback if no duration found in streams, try from 'format'
        format_info = probe.get('format', {})
        duration = format_info.get('duration')
        if duration:
            return float(duration)

        raise ValueError("Duration not found in video metadata.")

    except Exception as e:
        print(f"Error getting video duration: {e}")
        return 0.0
        
def upload_video():
    movies = load_movies()
    if not movies:
        print("No movies found in movies.json")
        return
    
    progress = load_progress()
    start_time = progress["current_start"]
    part_number = progress["part_number"]
    durations = progress["durations"]
    current_movie_name = progress["movie_name"]

    for movie in movies:
        if movie["name"] == current_movie_name or current_movie_name == "":
            video_url = movie["url"]
            movie_name = movie["name"]
            break
    else:
        print("No more movies left to upload.")
        return

    total_duration = get_video_duration(video_url)
    usable_duration = total_duration - (SKIP_START + SKIP_END)

    if start_time >= usable_duration:
        print(f"All parts of {movie_name} are already created.")
        reset_progress()
        return

    relative_start = start_time - SKIP_START
    part_time = random.randint(MIN_PART_DURATION, MAX_PART_DURATION)
    remaining_time = usable_duration - relative_start
    part_time = min(part_time, remaining_time)

    create_part(video_url, start_time, part_time, OUTPUT_FILE, part_number, movie_name)
    start_time += part_time
    part_number += 1
    durations.append(part_time)
    save_progress(start_time, part_number, durations, movie_name)

    tokens = load_tokens()

    for user, token_data in tokens.items():
        print(f"Uploading video for user: {user}")
        title = f"{movie_name} - Part {part_number-1} | Trending Now #Movie #Cinema #{movie_name.replace(' ', '')}"
        description = f"Enjoy part {part_number-1} of {movie_name}! Watch the best scenes! #Movie #Cinema #{movie_name.replace(' ', '')}"
        tags = ['movie', 'cinema', 'entertainment', 'bollywood', 'quotes', 'trending', 'viral']
        upload_to_youtube(OUTPUT_FILE, title, description, tags, token_data)

    print("Part uploaded successfully. Run again for next part.")

if __name__ == "__main__":
    upload_video()

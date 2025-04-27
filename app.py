import json
import os
import random
import ffmpeg
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# Settings
VIDEO_WIDTH = 720
VIDEO_HEIGHT = 1400  # Increased video height
WATERMARK_TEXT = "Quote Zen"
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
                # Make sure movie_name exists or initialize it
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
            .filter('scale', VIDEO_WIDTH, VIDEO_HEIGHT, force_original_aspect_ratio='decrease')
            .filter('pad', VIDEO_WIDTH, VIDEO_HEIGHT, '(ow-iw)/2', '(oh-ih)/2', color='white')
            .drawtext(
                fontfile=FONTFILE,
                text=f'{movie_name} - Part {part_number}',
                fontsize=50,
                fontcolor='black',
                x='(w-text_w)/2',
                y='100',  # Move part name down
                shadowcolor='white',
                shadowx=2,
                shadowy=2
            )
            .drawtext(
                fontfile=FONTFILE,
                text=WATERMARK_TEXT,
                fontsize=40,
                fontcolor='black',
                x='(w-text_w)/2',
                y='h-150',  # Move watermark down
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

# Get video duration
def get_video_duration(url):
    metadata = ffmpeg.probe(url)
    duration = float(metadata['format']['duration'])
    return duration

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

# Route to add movie details via a form
@app.route('/add_movie', methods=['GET', 'POST'])
def add_movie():
    if request.method == 'POST':
        movie_name = request.form['movie_name']
        movie_url = request.form['movie_url']
        save_movie({"name": movie_name, "url": movie_url})
        return redirect(url_for('upload_video'))
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Add Movie</title>
</head>
<body>
    <h1>Add Movie Details</h1>
    <form action="/add_movie" method="POST">
        <label for="movie_name">Movie Name:</label>
        <input type="text" name="movie_name" required><br><br>
        <label for="movie_url">Movie URL:</label>
        <input type="text" name="movie_url" required><br><br>
        <button type="submit">Add Movie</button>
    </form>
</body>
</html>"""

# Main function to upload videos from movies.json
@app.route('/upload_video', methods=['GET'])
def upload_video():
    movies = load_movies()
    if not movies:
        return "No movies found in movies.json"
    
    progress = load_progress()
    start_time = progress["current_start"]
    part_number = progress["part_number"]
    durations = progress["durations"]
    current_movie_name = progress["movie_name"]

    # Get the next movie to upload
    for movie in movies:
        if movie["name"] != current_movie_name:
            video_url = movie["url"]
            movie_name = movie["name"]
            break
    else:
        return "All parts are uploaded. Please add a new movie."
    
    total_duration = get_video_duration(video_url)
    usable_duration = total_duration - (SKIP_START + SKIP_END)

    if start_time >= (total_duration - SKIP_END):
        print(f"All parts of {movie_name} are already created.")
        save_progress(start_time, part_number, durations, movie_name)
        return redirect(url_for('upload_video'))

    part_time = random.randint(MIN_PART_DURATION, MAX_PART_DURATION)
    part_time = min(part_time, (total_duration - SKIP_END) - start_time)

    create_part(video_url, start_time, part_time, OUTPUT_FILE, part_number, movie_name)
    start_time += part_time
    part_number += 1
    durations.append(part_time)
    save_progress(start_time, part_number, durations, movie_name)

    # Load the tokens
    tokens = load_tokens()

    # Upload the video for each user
    for user, token_data in tokens.items():
        print(f"Uploading video for user: {user}")
        title = f"{movie_name} - Part {part_number} | Trending Now #Movie #Cinema #{movie_name.replace(' ', '')}"
        description = f"Watch the next part of {movie_name}!\n\nEnjoy the best movie moments! #Movie #Cinema #{movie_name.replace(' ', '')}"
        tags = ['movie', 'cinema', 'entertainment', 'bollywood', 'quotes', 'trending', 'viral']
        upload_to_youtube(OUTPUT_FILE, title, description, tags, token_data)

    return redirect(url_for('upload_video'))

if __name__ == "__main__":
    app.run(debug=True)
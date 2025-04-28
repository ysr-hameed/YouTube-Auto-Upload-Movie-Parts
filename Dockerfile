# Use a base Python image
FROM python:3.8-slim

# Install ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Set up your working directory
WORKDIR /workspace

# Install Python dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the rest of your app
COPY . .

# Set the command to run your app
CMD ["python", "app.py"

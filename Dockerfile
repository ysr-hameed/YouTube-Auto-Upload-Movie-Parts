# Start with a base image (e.g., Python image)
FROM python:3.9-slim

# Install ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install necessary Python packages
COPY requirements.txt /app/requirements.txt
WORKDIR /app
RUN pip install -r requirements.txt

# Copy your application code
COPY . /app

# Set environment variables if needed
ENV FLASK_APP=app.py

# Expose the required port
EXPOSE 8080

# Run the application
CMD ["python", "app.py"]

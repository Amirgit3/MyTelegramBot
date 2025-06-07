# Your base image
FROM python:3.9-slim-buster

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg \
    --no-install-recommends

# Install Python dependencies from requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Make sure yt-dlp is installed and up-to-date
RUN pip install --no-cache-dir yt-dlp --upgrade

# Set working directory
WORKDIR /app

# Copy your bot code
COPY . .

# Command to run your application
CMD ["python", "bot.py"]

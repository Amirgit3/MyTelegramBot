# Your base image, e.g.,
FROM python:3.9-slim-buster

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    # Add any other necessary system dependencies here if you had them before
    # For example, if you need git or other build tools:
    # git \
    # build-essential \
    # libssl-dev \
    # zlib1g-dev \
    # libbz2-dev \
    # libreadline-dev \
    # libsqlite3-dev \
    # libncursesw5-dev \
    # libgdbm-dev \
    # libc6-dev \
    # libffi-dev \
    # liblzma-dev \
    # wget \
    # curl \
    # --no-install-recommends

# Install Python dependencies from requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Make sure yt-dlp is installed and up-to-date
RUN pip install --no-cache-dir yt-dlp

# Set working directory
WORKDIR /app

# Copy your bot code
COPY . .

# Command to run your application
CMD ["python", "bot.py"]

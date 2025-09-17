#!/bin/bash

echo "parking camera client for pi"
echo "============================"

# check if config exists
if [ ! -f "config.json" ]; then
    echo "error: config.json not found!"
    echo "please create config.json file first"
    exit 1
fi

# install system dependencies
echo "checking system dependencies..."
if ! dpkg -l | grep -q libcap-dev; then
    echo "installing system dependencies (requires sudo)..."
    sudo apt update
    sudo apt install -y python3-venv python3-pip libcap-dev pkg-config \
        libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \
        libgomp1 libgtk-3-dev libavcodec-dev libavformat-dev libswscale-dev
fi

# create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "creating virtual environment..."
    python3 -m venv venv --system-site-packages
fi

# activate virtual environment
echo "activating virtual environment..."
source venv/bin/activate

# upgrade pip in virtual environment
echo "upgrading pip..."
pip install --upgrade pip

# install dependencies with --break-system-packages for compatibility
echo "installing dependencies..."
pip install --break-system-packages -r requirements.txt

# verify critical imports
echo "verifying python imports..."
python3 -c "import requests; import cv2; import numpy; print('all imports successful')"

# run the camera client
echo "starting camera client..."
python camera_client.py
#!/bin/bash

echo "Parking Camera Client for Pi"
echo "============================="

# check if config exists
if [ ! -f "config.json" ]; then
    echo "Error: config.json not found!"
    echo "Please create config.json with camera_id field"
    echo "Example: {\"camera_id\": \"entrance\"}"
    exit 1
fi

# read and validate camera_id from config.json
CAMERA_ID=$(python3 -c "
import json
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
    camera_id = config.get('camera_id', 'unknown')
    print(camera_id)
except Exception as e:
    print('error')
")

if [ "$CAMERA_ID" = "error" ]; then
    echo "Error: Cannot read camera_id from config.json"
    exit 1
fi

echo "Camera ID: $CAMERA_ID"

# validate camera_id
case $CAMERA_ID in
    "entrance"|"exit"|"area")
        echo "✓ Valid camera type: $CAMERA_ID"
        ;;
    *)
        echo "⚠ Warning: Unknown camera_id '$CAMERA_ID'"
        echo "  Valid options: entrance, exit, area"
        echo "  Proceeding anyway..."
        ;;
esac

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
python3 -c "
import requests
import cv2
import numpy
import json
import threading
import logging
print('✓ All imports successful')
"

if [ $? -ne 0 ]; then
    echo "✗ Import verification failed"
    exit 1
fi

# test camera availability
echo "testing camera access..."
python3 -c "
import cv2
import sys

# test USB camera
try:
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        print('✓ USB camera available')
        cap.release()
        usb_ok = True
    else:
        print('ℹ USB camera not available')
        usb_ok = False
except:
    print('ℹ USB camera test failed')
    usb_ok = False

# test Pi camera
try:
    from picamera2 import Picamera2
    print('✓ Pi camera module available')
    pi_ok = True
except ImportError:
    print('ℹ Pi camera module not available')
    pi_ok = False

if not usb_ok and not pi_ok:
    print('⚠ Warning: No cameras detected, but proceeding anyway')
else:
    print('✓ Camera hardware available')
"

# create logs directory
mkdir -p logs

# show final configuration
echo ""
echo "Final Configuration:"
python3 -c "
import json
with open('config.json', 'r') as f:
    config = json.load(f)

print(f'  Camera ID: {config.get(\"camera_id\", \"unknown\")}')
print(f'  Server URL: {config.get(\"server_url\", \"http://localhost:5000 (default)\")}')
print(f'  Camera Type: {config.get(\"camera_type\", \"auto (default)\")}')
"

# run the integrated camera client
echo ""
echo "Starting integrated camera client..."
echo "Press Ctrl+C to stop"
echo "Logs will be saved to: logs/camera_${CAMERA_ID}_$(date +%Y%m%d_%H%M%S).log"
echo ""

# start with logging
python integrated_camera_client.py --config config.json 2>&1 | tee "logs/camera_${CAMERA_ID}_$(date +%Y%m%d_%H%M%S).log"

echo ""
echo "Camera client stopped at: $(date)"
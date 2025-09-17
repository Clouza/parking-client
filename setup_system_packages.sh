#!/bin/bash

echo "parking camera client system setup for pi"
echo "=========================================="

# update system packages
echo "updating system packages..."
sudo apt update

# install python3 and system packages
echo "installing python3 and dependencies..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-opencv \
    python3-numpy \
    python3-requests \
    libcap-dev \
    pkg-config \
    python3-picamera2 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgtk-3-dev

# verify installations
echo "verifying system installations..."
python3 -c "
try:
    import cv2
    print('✓ opencv-python (system)')
except ImportError as e:
    print('✗ opencv-python failed:', e)

try:
    import numpy
    print('✓ numpy (system)')
except ImportError as e:
    print('✗ numpy failed:', e)

try:
    import requests
    print('✓ requests (system)')
except ImportError as e:
    print('✗ requests failed:', e)

try:
    from picamera2 import Picamera2
    print('✓ picamera2 (system)')
except ImportError as e:
    print('✗ picamera2 failed:', e)
"

echo "system setup complete!"
echo "you can now run: python3 camera_client.py"
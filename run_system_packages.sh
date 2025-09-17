#!/bin/bash

echo "parking camera client for pi (system packages)"
echo "==============================================="

# check if config exists
if [ ! -f "config.json" ]; then
    echo "error: config.json not found!"
    echo "please create config.json file first"
    exit 1
fi

# verify critical imports
echo "verifying python imports..."
python3 -c "
import sys
missing_modules = []

try:
    import requests
    print('✓ requests')
except ImportError:
    missing_modules.append('python3-requests')

try:
    import cv2
    print('✓ opencv-python')
except ImportError:
    missing_modules.append('python3-opencv')

try:
    import numpy
    print('✓ numpy')
except ImportError:
    missing_modules.append('python3-numpy')

try:
    from picamera2 import Picamera2
    print('✓ picamera2')
except ImportError:
    missing_modules.append('python3-picamera2')

if missing_modules:
    print('missing modules:', ', '.join(missing_modules))
    print('run: sudo apt install', ' '.join(missing_modules))
    sys.exit(1)
else:
    print('all imports successful')
"

if [ $? -ne 0 ]; then
    echo "dependencies missing. run ./setup_system_packages.sh first"
    exit 1
fi

# run the camera client
echo "starting camera client..."
python3 camera_client.py
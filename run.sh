#!/bin/bash

echo "parking camera client for pi"
echo "============================"

# check if config exists
if [ ! -f "config.json" ]; then
    echo "error: config.json not found!"
    echo "please create config.json file first"
    exit 1
fi

# install dependencies if needed
echo "installing dependencies..."
pip install -r requirements.txt

# run the camera client
echo "starting camera client..."
python3 camera_client.py
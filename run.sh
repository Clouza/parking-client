#!/bin/bash

echo "parking camera client for pi"
echo "============================"

# check if config exists
if [ ! -f "config.json" ]; then
    echo "error: config.json not found!"
    echo "please create config.json file first"
    exit 1
fi

# create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "creating virtual environment..."
    python3 -m venv venv
fi

# activate virtual environment
echo "activating virtual environment..."
source venv/bin/activate

# upgrade pip
pip install --upgrade pip

# install dependencies
echo "installing dependencies..."
pip install -r requirements.txt

# run the camera client
echo "starting camera client..."
python camera_client.py
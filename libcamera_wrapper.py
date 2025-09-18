#!/usr/bin/env python3
"""
LibCamera Wrapper for Pi Camera without picamera2 dependency
Uses libcamera-still command for Pi Camera capture
"""

import subprocess
import cv2
import numpy as np
import tempfile
import os

class LibCameraWrapper:
    def __init__(self, width=640, height=480):
        self.width = width
        self.height = height
        self.camera_type = "pi_libcamera"
        self.streaming_process = None

    def capture_array(self):
        """Capture image using libcamera-still and return as numpy array"""
        try:
            # create temporary file
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                temp_path = temp_file.name

            # capture single frame for analysis using libcamera-vid
            cmd = [
                'libcamera-vid',
                '--frames', '1',
                '--codec', 'mjpeg',
                '--output', temp_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                raise Exception(f"libcamera-vid failed: {result.stderr}")

            # read image file
            image = cv2.imread(temp_path)

            # cleanup temp file
            os.unlink(temp_path)

            if image is None:
                raise Exception("Failed to read captured image")

            # convert BGR to RGB for consistency with picamera2
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            return image_rgb

        except subprocess.TimeoutExpired:
            raise Exception("Camera capture timeout")
        except Exception as e:
            # cleanup temp file if exists
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
            raise e

    def start(self):
        """Compatibility method - libcamera doesn't need start"""
        pass

    def stop(self):
        """Compatibility method - libcamera doesn't need stop"""
        pass

    def start_streaming(self):
        """Start continuous streaming for real-time preview"""
        if self.streaming_process is None:
            try:
                # start continuous streaming
                cmd = [
                    'libcamera-vid',
                    '--inline',
                    '--listen',
                    '--codec', 'mjpeg'
                ]
                self.streaming_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                print("Started libcamera-vid streaming")
            except Exception as e:
                print(f"Failed to start streaming: {e}")

    def stop_streaming(self):
        """Stop continuous streaming"""
        if self.streaming_process:
            try:
                self.streaming_process.terminate()
                self.streaming_process.wait(timeout=5)
                self.streaming_process = None
                print("Stopped libcamera-vid streaming")
            except Exception as e:
                print(f"Error stopping streaming: {e}")

    def close(self):
        """Stop streaming and cleanup"""
        self.stop_streaming()

def test_libcamera():
    """Test function to verify libcamera works"""
    try:
        camera = LibCameraWrapper()
        image = camera.capture_array()
        print(f"✓ LibCamera capture successful: {image.shape}")
        return True
    except Exception as e:
        print(f"✗ LibCamera capture failed: {e}")
        return False

if __name__ == "__main__":
    test_libcamera()
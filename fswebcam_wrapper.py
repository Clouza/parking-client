#!/usr/bin/env python3
"""
FSWebcam Wrapper for USB Camera capture
Uses fswebcam command for USB camera capture
"""

import subprocess
import cv2
import tempfile
import os

class FSWebcamWrapper:
    def __init__(self, device=0, width=640, height=480):
        self.device = device if isinstance(device, str) else f"/dev/video{device}"
        self.width = width
        self.height = height
        self.camera_type = "usb_fswebcam"

    def capture_array(self):
        """capture image using fswebcam and return as numpy array"""
        try:
            # create temporary file
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                temp_path = temp_file.name

            # capture single frame using fswebcam
            cmd = [
                'fswebcam',
                '-d', self.device,
                '-r', f'{self.width}x{self.height}',
                '--no-banner',
                '--jpeg', '85',
                temp_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                raise Exception(f"fswebcam failed: {result.stderr}")

            # read image file
            image = cv2.imread(temp_path)

            # cleanup temp file
            os.unlink(temp_path)

            if image is None:
                raise Exception("failed to read captured image")

            # convert BGR to RGB for consistency
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

            return image_rgb

        except subprocess.TimeoutExpired:
            raise Exception("camera capture timeout")
        except Exception as e:
            # cleanup temp file if exists
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
            raise e

    def start(self):
        """compatibility method - fswebcam doesn't need start"""
        pass

    def stop(self):
        """compatibility method - fswebcam doesn't need stop"""
        pass

    def close(self):
        """cleanup method"""
        pass

def test_fswebcam(device=0):
    """test function to verify fswebcam works"""
    try:
        camera = FSWebcamWrapper(device=device)
        image = camera.capture_array()
        print(f"✓ fswebcam capture successful: {image.shape}")
        return True
    except Exception as e:
        print(f"✗ fswebcam capture failed: {e}")
        return False

if __name__ == "__main__":
    test_fswebcam()
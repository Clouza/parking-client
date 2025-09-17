#!/usr/bin/env python3

import json
import time
import requests
import base64
from datetime import datetime
import sys
import os
import cv2

try:
    from picamera2 import Picamera2
    PI_CAMERA_AVAILABLE = True
except ImportError:
    PI_CAMERA_AVAILABLE = False

class ParkingCameraClient:
    def __init__(self, config_file="config.json"):
        self.load_config(config_file)
        self.camera = None
        self.camera_type = None
        self.setup_camera()
        self.running = False

    def load_config(self, config_file):
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                self.server_url = config.get("server_url", "http://localhost:5000")
                self.camera_id = config["camera_id"]
                self.camera_type_config = config.get("camera_type", "auto")
        except FileNotFoundError:
            print(f"config file {config_file} not found!")
            sys.exit(1)

    def setup_camera(self):
        # try pi camera first
        if self.camera_type_config in ["auto", "pi", "picamera"] and PI_CAMERA_AVAILABLE:
            try:
                self.camera = Picamera2()
                self.camera.configure(self.camera.create_still_configuration())
                self.camera.start()
                self.camera_type = "pi"
                print("pi camera initialized successfully")
                return
            except Exception as e:
                print(f"pi camera setup failed: {e}")

        # fallback to usb camera
        if self.camera_type_config in ["auto", "usb"]:
            try:
                self.camera = cv2.VideoCapture(0)
                if not self.camera.isOpened():
                    raise Exception("cannot open usb camera")
                self.camera_type = "usb"
                print("usb camera initialized successfully")
                return
            except Exception as e:
                print(f"usb camera setup failed: {e}")

        print("no camera available!")
        sys.exit(1)

    def capture_image(self):
        if self.camera_type == "pi":
            # pi camera capture
            image_array = self.camera.capture_array()
            # convert rgb to bgr for opencv
            image_bgr = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
            return image_bgr
        else:
            # usb camera capture
            ret, frame = self.camera.read()
            if not ret:
                print("failed to capture image from usb camera")
                return None
            return frame

    def encode_image(self, image):
        _, buffer = cv2.imencode('.jpg', image)
        image_base64 = base64.b64encode(buffer).decode('utf-8')
        return image_base64

    def send_detection_result(self, plate_text, confidence, image_data):
        url = f"{self.server_url}/api/detection/result"

        payload = {
            "camera_id": self.camera_id,
            "detected_plate": plate_text,
            "confidence": confidence,
            "image_data": image_data,
            "timestamp": datetime.now().isoformat()
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                result = response.json()
                print(f"detection sent - action: {result.get('action', 'none')}")
                return result
            else:
                print(f"server error: {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"network error: {e}")
            return None

    def send_status(self):
        url = f"{self.server_url}/api/camera/status"

        payload = {
            "camera_id": self.camera_id,
            "status": "online",
            "camera_type": self.camera_type,
            "timestamp": datetime.now().isoformat()
        }

        try:
            response = requests.post(url, json=payload, timeout=5)
            return response.status_code == 200
        except:
            return False

    def check_for_triggers(self):
        # check for entrance trigger
        try:
            response = requests.get(f"{self.server_url}/api/camera/trigger-entrance", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('trigger', False):
                    print("entrance trigger received")
                    return "entrance"
        except:
            pass

        # check for exit trigger
        try:
            response = requests.get(f"{self.server_url}/api/camera/trigger-exit", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('trigger', False):
                    print("exit trigger received")
                    return "exit"
        except:
            pass

        return None

    def simple_plate_detection(self, image):
        # simple mock detection for demo
        # in real implementation, use plate recognition library
        return "ABC123", 0.85

    def run(self):
        print(f"parking camera client started")
        print(f"camera id: {self.camera_id}")
        print(f"camera type: {self.camera_type}")
        print(f"server: {self.server_url}")
        print("press ctrl+c to stop")

        self.running = True
        last_status = time.time()

        try:
            while self.running:
                current_time = time.time()

                # send status every 30 seconds
                if current_time - last_status > 30:
                    if self.send_status():
                        print("status sent successfully")
                    else:
                        print("failed to send status")
                    last_status = current_time

                # check for triggers
                trigger_type = self.check_for_triggers()

                if trigger_type:
                    print(f"processing {trigger_type} detection...")

                    # capture image
                    image = self.capture_image()
                    if image is not None:
                        # detect plate (mock implementation)
                        plate_text, confidence = self.simple_plate_detection(image)

                        # encode image
                        image_data = self.encode_image(image)

                        # send detection result
                        result = self.send_detection_result(plate_text, confidence, image_data)

                        if result:
                            print(f"plate detected: {plate_text} (confidence: {confidence:.2f})")
                        else:
                            print("failed to send detection result")

                # wait before next check
                time.sleep(2)

        except KeyboardInterrupt:
            print("\nstopping camera client...")
        finally:
            self.cleanup()

    def cleanup(self):
        self.running = False
        if self.camera:
            if self.camera_type == "pi":
                self.camera.stop()
            else:
                self.camera.release()
        print("camera client stopped")

if __name__ == "__main__":
    client = ParkingCameraClient()
    client.run()
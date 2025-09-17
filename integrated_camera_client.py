#!/usr/bin/env python3
"""
Integrated Camera Client with Real-time Streaming
Combines detection capabilities with real-time video streaming
"""

import json
import time
import requests
import base64
import threading
import logging
import argparse
import sys
from datetime import datetime
import cv2
from streaming_client import StreamingClient

# Disable picamera2 to avoid resource conflicts with libcamera
PI_CAMERA_AVAILABLE = False

# libcamera fallback
try:
    from libcamera_wrapper import LibCameraWrapper
    LIBCAMERA_AVAILABLE = True
except ImportError:
    LIBCAMERA_AVAILABLE = False

class IntegratedCameraClient:
    def __init__(self, config_file="config.json"):
        self.load_config(config_file)
        self.setup_logging()
        self.camera = None
        self.camera_type = None
        self.running = False
        self.streaming_client = None
        self.detection_thread = None

        # Initialize components based on camera role
        self.setup_camera()
        # disable streaming client to avoid camera resource conflicts
        # if self.config['features']['real_time_streaming']:
        #     self.streaming_client = StreamingClient(self.config)

    def load_config(self, config_file):
        try:
            with open(config_file, 'r') as f:
                self.config = json.load(f)

                # set default values for minimal config
                self.server_url = self.config.get("server_url", "http://localhost:5000")
                self.camera_id = self.config["camera_id"]  # required field
                self.camera_type_config = self.config.get("camera_type", "auto")

                # set default configuration sections
                if "streaming" not in self.config:
                    self.config["streaming"] = {
                        "enabled": True,
                        "fps": 15,
                        "quality": 80,
                        "resolution": {"width": 640, "height": 480}
                    }

                if "detection" not in self.config:
                    self.config["detection"] = {
                        "enabled": True,
                        "confidence_threshold": 0.3,
                        "cooldown": 5
                    }

                if "heartbeat" not in self.config:
                    self.config["heartbeat"] = {"interval": 30}

                if "features" not in self.config:
                    # auto-configure features based on camera_id
                    if self.camera_id == "entrance":
                        self.config["features"] = {
                            "entrance_detection": True,
                            "exit_detection": False,
                            "parking_monitor": False,
                            "real_time_streaming": True
                        }
                    elif self.camera_id == "exit":
                        self.config["features"] = {
                            "entrance_detection": False,
                            "exit_detection": True,
                            "parking_monitor": False,
                            "real_time_streaming": True
                        }
                    elif self.camera_id == "area":
                        self.config["features"] = {
                            "entrance_detection": False,
                            "exit_detection": False,
                            "parking_monitor": True,
                            "real_time_streaming": True
                        }
                    else:
                        self.config["features"] = {
                            "entrance_detection": True,
                            "exit_detection": False,
                            "parking_monitor": False,
                            "real_time_streaming": True
                        }

                if "logging" not in self.config:
                    self.config["logging"] = {"level": "INFO"}

                # set camera_role based on camera_id if not specified
                if "camera_role" not in self.config:
                    if self.camera_id == "area":
                        self.config["camera_role"] = "parking_monitor"
                    else:
                        self.config["camera_role"] = self.camera_id

        except FileNotFoundError:
            print(f"Config file {config_file} not found!")
            sys.exit(1)
        except KeyError as e:
            print(f"Missing required config field: {e}")
            print("Config must contain at least: camera_id")
            sys.exit(1)

    def setup_logging(self):
        """Setup logging system"""
        log_level = self.config.get('logging', {}).get('level', 'INFO')
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f'camera_{self.config["camera_id"]}.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def setup_camera(self):
        """Setup camera based on configuration"""
        camera_type = self.config.get('camera_type', 'auto')

        # Try Pi camera first
        if camera_type in ["auto", "pi", "picamera"] and PI_CAMERA_AVAILABLE:
            try:
                self.camera = Picamera2()
                self.camera.configure(self.camera.create_still_configuration())
                self.camera.start()
                self.camera_type = "pi"
                self.logger.info("Pi camera initialized successfully")
                return
            except Exception as e:
                self.logger.warning(f"Pi camera setup failed: {e}")

        # Try libcamera fallback for Pi
        if camera_type in ["auto", "pi", "picamera"] and LIBCAMERA_AVAILABLE:
            try:
                width = self.config['streaming']['resolution']['width']
                height = self.config['streaming']['resolution']['height']
                self.camera = LibCameraWrapper(width=width, height=height)
                self.camera.start()
                self.camera_type = "pi_libcamera"
                self.logger.info("Pi camera (libcamera) initialized successfully")
                return
            except Exception as e:
                self.logger.warning(f"Pi camera libcamera setup failed: {e}")

        # Fallback to USB camera
        if camera_type in ["auto", "usb"]:
            try:
                self.camera = cv2.VideoCapture(0)
                if not self.camera.isOpened():
                    raise Exception("Cannot open USB camera")
                self.camera_type = "usb"
                self.logger.info("USB camera initialized successfully")
                return
            except Exception as e:
                self.logger.error(f"USB camera setup failed: {e}")

        self.logger.error("No camera available!")
        sys.exit(1)

    def capture_image(self):
        """Capture image from camera"""
        if self.camera_type == "pi":
            image_array = self.camera.capture_array()
            image_bgr = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
            return image_bgr
        elif self.camera_type == "pi_libcamera":
            image_array = self.camera.capture_array()
            image_bgr = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
            return image_bgr
        else:
            ret, frame = self.camera.read()
            if not ret:
                self.logger.error("Failed to capture image from USB camera")
                return None
            return frame

    def encode_image(self, image):
        """Encode image to base64"""
        _, buffer = cv2.imencode('.jpg', image)
        image_base64 = base64.b64encode(buffer).decode('utf-8')
        return image_base64

    def send_detection_result(self, plate_text, confidence, image_data):
        """Send detection result to server"""
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
                self.logger.info(f"Detection sent - action: {result.get('action', 'none')}")
                return result
            else:
                self.logger.error(f"Server error: {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error: {e}")
            return None

    def send_status(self):
        """Send camera status to server"""
        url = f"{self.server_url}/api/camera/status"

        payload = {
            "camera_id": self.camera_id,
            "camera_role": self.config.get('camera_role', 'unknown'),
            "status": "online",
            "camera_type": self.camera_type,
            "streaming_active": self.streaming_client.streaming_active if self.streaming_client else False,
            "features": self.config['features'],
            "timestamp": datetime.now().isoformat()
        }

        try:
            response = requests.post(url, json=payload, timeout=5)
            return response.status_code == 200
        except:
            return False

    def check_for_triggers(self):
        """Check for detection triggers from server"""
        camera_role = self.config.get('camera_role', 'entrance')

        if camera_role == 'entrance' and self.config['features']['entrance_detection']:
            try:
                # use POST request with camera data
                payload = {
                    "camera_id": self.camera_id,
                    "camera_role": camera_role,
                    "status": "requesting_trigger"
                }
                response = requests.post(f"{self.server_url}/api/camera/trigger-entrance",
                                       json=payload, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success', False):
                        self.logger.info("Entrance trigger received")
                        return "entrance"
            except Exception as e:
                self.logger.warning(f"Failed to check entrance trigger: {e}")
                pass

        elif camera_role == 'exit' and self.config['features']['exit_detection']:
            try:
                # use POST request with camera data
                payload = {
                    "camera_id": self.camera_id,
                    "camera_role": camera_role,
                    "status": "requesting_trigger"
                }
                response = requests.post(f"{self.server_url}/api/camera/trigger-exit",
                                       json=payload, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success', False):
                        self.logger.info("Exit trigger received")
                        return "exit"
            except Exception as e:
                self.logger.warning(f"Failed to check exit trigger: {e}")
                pass

        return None

    def send_capture_for_preview(self):
        """Send high-quality camera capture for preview purposes"""
        try:
            image = self.capture_image()
            if image is not None:
                image_data = self.encode_image(image)
                # Send as detection result with empty plate for preview
                payload = {
                    "camera_id": self.camera_id,
                    "detected_plate": "",
                    "confidence": 0.0,
                    "image_data": image_data,
                    "timestamp": datetime.now().isoformat()
                }

                response = requests.post(f"{self.server_url}/api/detection/result", json=payload, timeout=15)
                if response.status_code == 200:
                    self.logger.debug("High-quality preview capture sent successfully")
                    return True
                else:
                    self.logger.warning(f"Preview capture failed: {response.status_code}")
            else:
                self.logger.warning("Failed to capture high-quality image for preview")
        except Exception as e:
            self.logger.error(f"Preview capture failed: {e}")
        return False

    def get_latest_capture_from_server(self):
        """Get latest capture from server"""
        try:
            response = requests.get(f"{self.server_url}/api/camera/latest-capture",
                                  params={'camera_id': self.camera_id}, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('success', False):
                    return data.get('capture_data')
            else:
                self.logger.debug(f"No latest capture available: {response.status_code}")
        except Exception as e:
            self.logger.warning(f"Failed to get latest capture: {e}")
        return None

    def simple_plate_detection(self, image):
        """Simple mock detection - replace with actual license plate recognition"""
        # This is a placeholder - implement actual plate detection here
        import random
        plates = ["ABC123", "XYZ789", "DEF456", "GHI321"]
        return random.choice(plates), round(random.uniform(0.7, 0.95), 2)

    def detection_worker(self):
        """Background thread for detection monitoring"""
        last_trigger_check = time.time()

        while self.running:
            current_time = time.time()

            # Check for triggers periodically
            if current_time - last_trigger_check > 2:
                trigger_type = self.check_for_triggers()

                if trigger_type:
                    self.logger.info(f"Processing {trigger_type} capture...")

                    # Capture high-quality image for user review
                    image = self.capture_image()
                    if image is not None:
                        # Encode image only (no detection yet)
                        image_data = self.encode_image(image)

                        # Send capture result without plate detection
                        result = self.send_detection_result("", 0.0, image_data)

                        if result:
                            self.logger.info(f"High-quality image captured and sent for user review")
                        else:
                            self.logger.warning("Failed to send capture result")

                last_trigger_check = current_time

            time.sleep(0.5)  # Check more frequently

    def start_services(self):
        """Start all configured services"""
        services_started = []

        # disable streaming to avoid camera resource conflicts
        # # Start streaming if enabled
        # if self.config['features']['real_time_streaming'] and self.streaming_client:
        #     if self.streaming_client.setup_camera() and self.streaming_client.connect_to_server():
        #         if self.streaming_client.start_streaming():
        #             services_started.append("video streaming")
        #             self.logger.info("Video streaming started")
        #     else:
        #         self.logger.error("Failed to start streaming client")

        # Start detection monitoring if enabled
        if self.config['detection']['enabled']:
            self.detection_thread = threading.Thread(target=self.detection_worker, daemon=True)
            self.detection_thread.start()
            services_started.append("detection monitoring")
            self.logger.info("Detection monitoring started")

        return services_started

    def run(self):
        """Main run loop"""
        self.logger.info(f"Integrated camera client starting...")
        self.logger.info(f"Camera ID: {self.camera_id}")
        self.logger.info(f"Camera Role: {self.config.get('camera_role', 'unknown')}")
        self.logger.info(f"Camera Type: {self.camera_type}")
        self.logger.info(f"Server: {self.server_url}")

        self.running = True

        # Start services
        services = self.start_services()
        if services:
            self.logger.info(f"Started services: {', '.join(services)}")
        else:
            self.logger.warning("No services started")

        # Main status loop
        last_status = time.time()
        heartbeat_interval = self.config['heartbeat']['interval']

        try:
            while self.running:
                current_time = time.time()

                # Send status heartbeat
                if current_time - last_status > heartbeat_interval:
                    if self.send_status():
                        self.logger.debug("Status sent successfully")
                    else:
                        self.logger.warning("Failed to send status")
                    last_status = current_time

                # Send preview capture every 10 seconds
                if not hasattr(self, 'last_preview_time'):
                    self.last_preview_time = 0

                if current_time - self.last_preview_time > 10:
                    if self.send_capture_for_preview():
                        self.logger.debug("Preview capture sent")
                    self.last_preview_time = current_time

                time.sleep(5)  # Main loop sleep

        except KeyboardInterrupt:
            self.logger.info("Stopping camera client...")
        finally:
            self.cleanup()

    def cleanup(self):
        """Cleanup resources"""
        self.running = False

        # Stop streaming
        if self.streaming_client:
            self.streaming_client.cleanup()

        # Wait for detection thread to finish
        if self.detection_thread:
            self.detection_thread.join(timeout=5)

        # Cleanup camera
        if self.camera:
            if self.camera_type == "pi":
                self.camera.stop()
                self.camera.close()
            else:
                self.camera.release()

        self.logger.info("Camera client stopped")

def main():
    parser = argparse.ArgumentParser(description="Integrated Camera Client with Streaming")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config file"
    )
    parser.add_argument(
        "--test-camera",
        action="store_true",
        help="Test camera capture only"
    )
    parser.add_argument(
        "--streaming-only",
        action="store_true",
        help="Start streaming only (no detection)"
    )

    args = parser.parse_args()

    if args.test_camera:
        # Test camera capture
        client = IntegratedCameraClient(args.config)
        image = client.capture_image()
        if image is not None:
            cv2.imwrite("test_capture.jpg", image)
            print("Test capture saved as test_capture.jpg")
        else:
            print("Camera test failed")
        client.cleanup()
        return

    if args.streaming_only:
        # Streaming only mode
        with open(args.config, 'r') as f:
            config = json.load(f)

        streaming_client = StreamingClient(config)
        try:
            streaming_client.run()
        finally:
            streaming_client.cleanup()
        return

    # Full integrated client
    client = IntegratedCameraClient(args.config)
    client.run()

if __name__ == "__main__":
    main()
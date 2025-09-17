#!/usr/bin/env python3
"""
Raspberry Pi Camera Client
Basic client for capturing images and communicating with Flask server
"""

import json
import logging
import threading
import time
import argparse
import sys
import base64
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import cv2
import numpy as np
from gpio_control import GpioController
from parking_monitor import ParkingMonitor
from web_dashboard import WebDashboard
from camera_manager import CameraManager
from exit_detector import ExitDetector
from command_handler import CommandHandler

try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False
    print("Warning: picamera2 not available. Camera functionality disabled.")

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    print("Warning: opencv not available. Motion detection disabled.")


class EntranceDetector:
    def __init__(self, config, camera, session, logger):
        self.config = config
        self.camera = camera
        self.session = session
        self.logger = logger
        self.background_subtractor = None
        self.last_detection_time = 0
        self.detection_cooldown = config.get('detection', {}).get('cooldown', 5)
        self.motion_threshold = config.get('detection', {}).get('motion_threshold', 1000)
        self.gpio_controller = GpioController(config)
        self.storage_dir = Path(config.get('storage', {}).get('directory', 'captures'))
        self.max_storage_days = config.get('storage', {}).get('max_days', 7)
        self.setup_storage()

    def setup_storage(self):
        """setup local image storage directory"""
        self.storage_dir.mkdir(exist_ok=True)
        self.logger.info(f"storage directory: {self.storage_dir}")

    def initialize(self):
        """initialize motion detection and gpio"""
        if not OPENCV_AVAILABLE:
            self.logger.error("opencv not available for motion detection")
            return False

        try:
            self.background_subtractor = cv2.createBackgroundSubtractorMOG2(
                detectShadows=True,
                varThreshold=16
            )
            self.gpio_controller.initialize()
            self.logger.info("entrance detector initialized")
            return True
        except Exception as e:
            self.logger.error(f"failed to initialize entrance detector: {e}")
            return False

    def detect_motion(self, frame):
        """detect motion using background subtraction"""
        if self.background_subtractor is None:
            return False

        try:
            # apply background subtraction
            fg_mask = self.background_subtractor.apply(frame)

            # count non-zero pixels
            motion_pixels = cv2.countNonZero(fg_mask)

            # check if motion exceeds threshold
            motion_detected = motion_pixels > self.motion_threshold

            if motion_detected:
                self.logger.debug(f"motion detected: {motion_pixels} pixels")

            return motion_detected

        except Exception as e:
            self.logger.error(f"motion detection error: {e}")
            return False

    def capture_for_detection(self):
        """capture high resolution image for license plate detection"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = self.storage_dir / f"detection_{timestamp}.jpg"

        try:
            # capture high resolution image
            self.camera.capture_file(str(filename))
            self.logger.info(f"detection image captured: {filename}")
            return filename
        except Exception as e:
            self.logger.error(f"failed to capture detection image: {e}")
            return None

    def encode_image_base64(self, image_path):
        """encode image to base64 string"""
        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()
            return base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            self.logger.error(f"failed to encode image: {e}")
            return None

    def send_detection_request(self, image_path, retries=3):
        """send detection request to server with retry logic"""
        url = f"{self.config['server']['url']}/api/detection/result"

        # encode image
        image_data = self.encode_image_base64(image_path)
        if not image_data:
            return None

        payload = {
            "camera_id": self.config['camera']['id'],
            "image_data": image_data,
            "timestamp": datetime.now().isoformat()
        }

        for attempt in range(retries):
            try:
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.config['server']['timeout']
                )
                response.raise_for_status()
                result = response.json()
                self.logger.info(f"detection request successful: {result}")
                return result

            except requests.exceptions.RequestException as e:
                self.logger.warning(f"detection request attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)  # exponential backoff

        self.logger.error("all detection request attempts failed")
        return None

    def process_detection_response(self, response):
        """process server response and control gate"""
        if not response:
            self.logger.warning("no response from server, denying entry")
            self.gpio_controller.blink_led(count=2)  # indicate error
            return False

        try:
            access_granted = response.get('access_granted', False)
            confidence = response.get('confidence', 0)
            license_plate = response.get('license_plate', 'unknown')

            self.logger.info(f"detection result: plate={license_plate}, confidence={confidence}, access={access_granted}")

            if access_granted:
                self.logger.info("access granted, opening gate")
                self.gpio_controller.open_gate(duration=self.config.get('gpio', {}).get('gate_duration', 5))
                return True
            else:
                self.logger.info("access denied")
                self.gpio_controller.blink_led(count=3)  # indicate denied
                return False

        except Exception as e:
            self.logger.error(f"failed to process detection response: {e}")
            return False

    def cleanup_old_images(self):
        """cleanup old stored images"""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.max_storage_days)

            for image_file in self.storage_dir.glob('*.jpg'):
                if image_file.stat().st_mtime < cutoff_date.timestamp():
                    image_file.unlink()
                    self.logger.debug(f"deleted old image: {image_file}")

        except Exception as e:
            self.logger.error(f"failed to cleanup old images: {e}")

    def process_frame(self, frame):
        """process camera frame for motion detection"""
        current_time = time.time()

        # check cooldown period
        if current_time - self.last_detection_time < self.detection_cooldown:
            return

        # detect motion
        if self.detect_motion(frame):
            self.logger.info("motion detected, starting detection process")
            self.last_detection_time = current_time

            # capture high resolution image
            image_path = self.capture_for_detection()
            if image_path:
                # send to server for detection
                response = self.send_detection_request(image_path)

                # process response
                self.process_detection_response(response)

                # cleanup old images periodically
                if current_time % 3600 < 1:  # once per hour
                    self.cleanup_old_images()


class CameraClient:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.config = self.load_config()
        self.setup_logging()
        self.camera = None
        self.camera_manager = None
        self.session = self.setup_http_session()
        self.heartbeat_thread = None
        self.detection_thread = None
        self.running = False
        self.entrance_detector = None
        self.exit_detector = None
        self.parking_monitor = None
        self.web_dashboard = None
        self.command_handler = None

    def load_config(self):
        """load configuration from json file"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.error(f"config file {self.config_path} not found")
            sys.exit(1)
        except json.JSONDecodeError as e:
            self.logger.error(f"invalid json in config file: {e}")
            sys.exit(1)

    def setup_logging(self):
        """setup logging system"""
        log_level = self.config.get('logging', {}).get('level', 'INFO')
        log_file = self.config.get('logging', {}).get('file', 'camera_client.log')

        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def setup_http_session(self):
        """setup http session with retry strategy"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def initialize_camera(self):
        """initialize camera manager and cameras"""
        if not PICAMERA_AVAILABLE:
            self.logger.error("picamera2 not available")
            return False

        try:
            # initialize camera manager for dual-camera support
            self.camera_manager = CameraManager(self.config)
            if not self.camera_manager.initialize_cameras():
                self.logger.error("failed to initialize cameras")
                return False

            # keep backward compatibility
            self.camera = self.camera_manager.get_current_camera()

            # initialize entrance detector
            if self.config.get('entrance_detection', {}).get('enabled', False):
                self.entrance_detector = EntranceDetector(
                    self.config, self.camera, self.session, self.logger
                )
                if not self.entrance_detector.initialize():
                    self.logger.warning("entrance detection initialization failed")
                    self.entrance_detector = None

            # initialize exit detector
            if self.config.get('exit_detection', {}).get('enabled', False):
                self.exit_detector = ExitDetector(
                    self.config, self.camera_manager, self.session, self.logger
                )
                if not self.exit_detector.initialize():
                    self.logger.warning("exit detection initialization failed")
                    self.exit_detector = None

            # initialize parking monitor
            if self.config.get('parking_monitor', {}).get('enabled', False):
                self.parking_monitor = ParkingMonitor(
                    self.config, self.camera_manager, self.session, self.logger
                )
                self.logger.info("parking monitor initialized")

            # initialize web dashboard
            if self.config.get('web_dashboard', {}).get('enabled', False):
                self.web_dashboard = WebDashboard(self.config, self.parking_monitor)
                self.logger.info("web dashboard initialized")

            # initialize command handler
            if self.config.get('command_handler', {}).get('enabled', True):
                self.command_handler = CommandHandler(
                    self.config, self.camera_manager, self.parking_monitor,
                    self.entrance_detector, self.exit_detector
                )
                self.logger.info("command handler initialized")

            self.logger.info("camera system initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"failed to initialize camera system: {e}")
            return False

    def capture_image(self, filename=None):
        """capture image from camera"""
        if not self.camera:
            self.logger.error("camera not initialized")
            return None

        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"capture_{timestamp}.jpg"

        try:
            self.camera.capture_file(filename)
            self.logger.info(f"image captured: {filename}")
            return filename
        except Exception as e:
            self.logger.error(f"failed to capture image: {e}")
            return None

    def send_heartbeat(self):
        """send heartbeat to server"""
        url = f"{self.config['server']['url']}/api/camera/status"
        data = {
            "camera_id": self.config['camera']['id'],
            "status": "online",
            "timestamp": datetime.now().isoformat()
        }

        try:
            response = self.session.post(
                url,
                json=data,
                timeout=self.config['server']['timeout']
            )
            response.raise_for_status()
            self.logger.debug("heartbeat sent successfully")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"failed to send heartbeat: {e}")

    def heartbeat_worker(self):
        """background thread for sending heartbeats"""
        while self.running:
            self.send_heartbeat()
            time.sleep(self.config['heartbeat']['interval'])

    def start_heartbeat(self):
        """start heartbeat thread"""
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return

        self.running = True
        self.heartbeat_thread = threading.Thread(target=self.heartbeat_worker)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        self.logger.info("heartbeat started")

    def stop_heartbeat(self):
        """stop heartbeat thread"""
        self.running = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=5)
            self.logger.info("heartbeat stopped")

    def test_connectivity(self):
        """test connection to server"""
        url = f"{self.config['server']['url']}/api/camera/status"
        try:
            response = self.session.get(
                url,
                timeout=self.config['server']['timeout']
            )
            response.raise_for_status()
            self.logger.info("server connectivity test passed")
            return True
        except requests.exceptions.RequestException as e:
            self.logger.error(f"server connectivity test failed: {e}")
            return False

    def detection_worker(self):
        """background thread for entrance detection"""
        if not self.entrance_detector:
            return

        self.logger.info("entrance detection started")

        while self.running:
            try:
                # capture frame for motion detection
                frame = self.camera.capture_array("lores")

                # process frame
                self.entrance_detector.process_frame(frame)

                # small delay to prevent excessive cpu usage
                time.sleep(0.1)

            except Exception as e:
                self.logger.error(f"detection worker error: {e}")
                time.sleep(1)

    def start_detection(self):
        """start entrance detection thread"""
        if not self.entrance_detector:
            self.logger.warning("entrance detector not available")
            return

        if self.detection_thread and self.detection_thread.is_alive():
            return

        self.detection_thread = threading.Thread(target=self.detection_worker)
        self.detection_thread.daemon = True
        self.detection_thread.start()
        self.logger.info("entrance detection thread started")

    def start_exit_detection(self):
        """start exit detection"""
        if self.exit_detector:
            self.exit_detector.start_detection()
        else:
            self.logger.warning("exit detector not available")

    def stop_exit_detection(self):
        """stop exit detection"""
        if self.exit_detector:
            self.exit_detector.stop_detection()

    def stop_detection(self):
        """stop entrance detection thread"""
        if self.detection_thread:
            self.detection_thread.join(timeout=5)
            self.logger.info("entrance detection stopped")

    def start_parking_monitor(self):
        """start parking monitoring"""
        if self.parking_monitor:
            self.parking_monitor.start_monitoring()
        else:
            self.logger.warning("parking monitor not available")

    def stop_parking_monitor(self):
        """stop parking monitoring"""
        if self.parking_monitor:
            self.parking_monitor.stop_monitoring()

    def start_web_dashboard(self):
        """start web dashboard"""
        if self.web_dashboard:
            self.web_dashboard.start_server()
        else:
            self.logger.warning("web dashboard not available")

    def stop_web_dashboard(self):
        """stop web dashboard"""
        if self.web_dashboard:
            self.web_dashboard.stop_server()

    def start_command_handler(self):
        """start command handler"""
        if self.command_handler:
            self.command_handler.start_polling()
        else:
            self.logger.warning("command handler not available")

    def stop_command_handler(self):
        """stop command handler"""
        if self.command_handler:
            self.command_handler.stop_polling()

    def cleanup(self):
        """cleanup resources"""
        self.stop_heartbeat()
        self.stop_detection()
        self.stop_exit_detection()
        self.stop_parking_monitor()
        self.stop_web_dashboard()
        self.stop_command_handler()
        if self.entrance_detector:
            self.entrance_detector.cleanup()
        if self.exit_detector:
            self.exit_detector.cleanup()
        if self.parking_monitor:
            self.parking_monitor.cleanup_old_images()
        if self.camera_manager:
            self.camera_manager.cleanup()
        elif self.camera:
            self.camera.stop()
            self.camera.close()
        self.logger.info("camera system cleaned up")


def main():
    parser = argparse.ArgumentParser(description="Raspberry Pi Camera Client")
    parser.add_argument(
        "--config",
        default="config.json",
        help="path to config file"
    )
    parser.add_argument(
        "--test-camera",
        action="store_true",
        help="test camera capture"
    )
    parser.add_argument(
        "--test-server",
        action="store_true",
        help="test server connectivity"
    )
    parser.add_argument(
        "--capture",
        metavar="FILENAME",
        help="capture image with specified filename"
    )
    parser.add_argument(
        "--heartbeat",
        action="store_true",
        help="start heartbeat service"
    )
    parser.add_argument(
        "--entrance-detection",
        action="store_true",
        help="start entrance detection service"
    )
    parser.add_argument(
        "--test-gpio",
        action="store_true",
        help="test gpio control"
    )
    parser.add_argument(
        "--parking-monitor",
        action="store_true",
        help="start parking monitoring service"
    )
    parser.add_argument(
        "--web-dashboard",
        action="store_true",
        help="start web dashboard only"
    )
    parser.add_argument(
        "--exit-detection",
        action="store_true",
        help="start exit detection service"
    )
    parser.add_argument(
        "--command-handler",
        action="store_true",
        help="start command handler only"
    )

    args = parser.parse_args()

    client = CameraClient(args.config)

    try:
        if args.test_camera:
            if client.initialize_camera():
                filename = client.capture_image()
                if filename:
                    print(f"test capture saved as: {filename}")
                else:
                    print("test capture failed")
            else:
                print("camera initialization failed")

        elif args.test_server:
            if client.test_connectivity():
                print("server connectivity test passed")
            else:
                print("server connectivity test failed")

        elif args.capture:
            if client.initialize_camera():
                filename = client.capture_image(args.capture)
                if filename:
                    print(f"image captured: {filename}")
                else:
                    print("capture failed")
            else:
                print("camera initialization failed")

        elif args.heartbeat:
            client.start_heartbeat()
            print("heartbeat started. press ctrl+c to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping heartbeat...")

        elif args.entrance_detection:
            if not client.initialize_camera():
                print("camera initialization failed")
                return

            client.start_detection()
            print("entrance detection started. press ctrl+c to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping entrance detection...")

        elif args.test_gpio:
            from gpio_control import GpioController
            gpio = GpioController(client.config)
            if gpio.initialize():
                print("testing gpio control...")
                gpio.blink_led(count=3)
                time.sleep(1)
                gpio.open_gate(duration=3)
                gpio.cleanup()
                print("gpio test completed")
            else:
                print("gpio initialization failed")

        elif args.parking_monitor:
            if not client.initialize_camera():
                print("camera initialization failed")
                return

            client.start_parking_monitor()
            client.start_web_dashboard()
            print("parking monitor started. press ctrl+c to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping parking monitor...")

        elif args.web_dashboard:
            client.start_web_dashboard()
            port = client.config.get('web_dashboard', {}).get('port', 8080)
            print(f"web dashboard started on port {port}. press ctrl+c to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping web dashboard...")

        elif args.exit_detection:
            if not client.initialize_camera():
                print("camera initialization failed")
                return

            client.start_exit_detection()
            print("exit detection started. press ctrl+c to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping exit detection...")

        elif args.command_handler:
            client.start_command_handler()
            print("command handler started. press ctrl+c to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping command handler...")

        else:
            # run full service
            if not client.initialize_camera():
                print("camera initialization failed")
                return

            if not client.test_connectivity():
                print("server connectivity test failed")
                return

            client.start_heartbeat()

            # start enabled services
            services = []
            if client.config.get('entrance_detection', {}).get('enabled', False):
                client.start_detection()
                services.append("entrance detection")

            if client.config.get('exit_detection', {}).get('enabled', False):
                client.start_exit_detection()
                services.append("exit detection")

            if client.config.get('parking_monitor', {}).get('enabled', False):
                client.start_parking_monitor()
                services.append("parking monitor")

            if client.config.get('web_dashboard', {}).get('enabled', False):
                client.start_web_dashboard()
                services.append("web dashboard")
                port = client.config.get('web_dashboard', {}).get('port', 8080)
                print(f"web dashboard available at http://localhost:{port}")

            if client.config.get('command_handler', {}).get('enabled', True):
                client.start_command_handler()
                services.append("command handler")

            if services:
                print(f"camera client started with: {', '.join(services)}. press ctrl+c to stop.")
            else:
                print("camera client started. press ctrl+c to stop.")

            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nstopping camera client...")

    finally:
        client.cleanup()


if __name__ == "__main__":
    main()
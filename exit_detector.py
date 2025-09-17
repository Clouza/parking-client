#!/usr/bin/env python3
"""
Exit Detection Module
Handles vehicle exit detection with exit-specific endpoints and barrier control
"""

import logging
import threading
import time
import base64
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
import requests
from gpio_control import GpioController

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False


class ExitDetector:
    def __init__(self, config, camera_manager, session, logger):
        self.config = config
        self.camera_manager = camera_manager
        self.session = session
        self.logger = logger
        self.background_subtractor = None
        self.last_detection_time = 0
        self.detection_cooldown = config.get('exit_detection', {}).get('cooldown', 5)
        self.motion_threshold = config.get('exit_detection', {}).get('motion_threshold', 1000)
        self.gpio_controller = GpioController(config, gpio_type='exit')
        self.storage_dir = Path(config.get('exit_detection', {}).get('storage_dir', 'exit_captures'))
        self.max_storage_days = config.get('exit_detection', {}).get('max_storage_days', 7)
        self.running = False
        self.detection_thread = None
        self.setup_storage()

    def setup_storage(self):
        """setup local exit image storage directory"""
        self.storage_dir.mkdir(exist_ok=True)
        self.logger.info(f"exit storage directory: {self.storage_dir}")

    def initialize(self):
        """initialize motion detection and gpio for exit"""
        if not OPENCV_AVAILABLE:
            self.logger.error("opencv not available for exit motion detection")
            return False

        try:
            self.background_subtractor = cv2.createBackgroundSubtractorMOG2(
                detectShadows=True,
                varThreshold=16
            )
            self.gpio_controller.initialize()
            self.logger.info("exit detector initialized")
            return True
        except Exception as e:
            self.logger.error(f"failed to initialize exit detector: {e}")
            return False

    def detect_motion(self, frame):
        """detect motion using background subtraction for exit"""
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
                self.logger.debug(f"exit motion detected: {motion_pixels} pixels")

            return motion_detected

        except Exception as e:
            self.logger.error(f"exit motion detection error: {e}")
            return False

    def capture_for_detection(self):
        """capture high resolution image for exit license plate detection"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = self.storage_dir / f"exit_detection_{timestamp}.jpg"

        try:
            # switch to exit camera and capture
            if self.camera_manager.capture_image(str(filename), 'exit'):
                self.logger.info(f"exit detection image captured: {filename}")
                return filename
            else:
                self.logger.error("failed to capture exit detection image")
                return None
        except Exception as e:
            self.logger.error(f"failed to capture exit detection image: {e}")
            return None

    def encode_image_base64(self, image_path):
        """encode image to base64 string"""
        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()
            return base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            self.logger.error(f"failed to encode exit image: {e}")
            return None

    def send_exit_detection_request(self, image_path, retries=3):
        """send exit detection request to server with retry logic"""
        url = f"{self.config['server']['url']}/api/exit-detection/result"

        # encode image
        image_data = self.encode_image_base64(image_path)
        if not image_data:
            return None

        payload = {
            "camera_id": self.config['camera']['id'],
            "image_data": image_data,
            "timestamp": datetime.now().isoformat(),
            "detection_type": "exit"
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
                self.logger.info(f"exit detection request successful: {result}")
                return result

            except requests.exceptions.RequestException as e:
                self.logger.warning(f"exit detection request attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)  # exponential backoff

        self.logger.error("all exit detection request attempts failed")
        return None

    def process_exit_detection_response(self, response):
        """process server response and control exit gate"""
        if not response:
            self.logger.warning("no response from server for exit, denying exit")
            self.gpio_controller.blink_led(count=2)  # indicate error
            return False

        try:
            exit_granted = response.get('exit_granted', False)
            confidence = response.get('confidence', 0)
            license_plate = response.get('license_plate', 'unknown')
            reason = response.get('reason', 'unknown')

            self.logger.info(f"exit detection result: plate={license_plate}, "
                           f"confidence={confidence}, exit={exit_granted}, reason={reason}")

            if exit_granted:
                self.logger.info("exit granted, opening exit gate")
                # use different timing for exit gate
                gate_duration = self.config.get('exit_detection', {}).get('gate_duration', 8)
                self.gpio_controller.open_gate(duration=gate_duration)
                return True
            else:
                self.logger.info(f"exit denied: {reason}")
                self.gpio_controller.blink_led(count=3)  # indicate denied
                return False

        except Exception as e:
            self.logger.error(f"failed to process exit detection response: {e}")
            return False

    def cleanup_old_images(self):
        """cleanup old stored exit images"""
        try:
            from datetime import timedelta
            cutoff_date = datetime.now() - timedelta(days=self.max_storage_days)

            for image_file in self.storage_dir.glob('*.jpg'):
                if image_file.stat().st_mtime < cutoff_date.timestamp():
                    image_file.unlink()
                    self.logger.debug(f"deleted old exit image: {image_file}")

        except Exception as e:
            self.logger.error(f"failed to cleanup old exit images: {e}")

    def process_frame(self, frame):
        """process camera frame for exit motion detection"""
        current_time = time.time()

        # check cooldown period
        if current_time - self.last_detection_time < self.detection_cooldown:
            return

        # detect motion
        if self.detect_motion(frame):
            self.logger.info("exit motion detected, starting exit detection process")
            self.last_detection_time = current_time

            # capture high resolution image
            image_path = self.capture_for_detection()
            if image_path:
                # send to server for detection
                response = self.send_exit_detection_request(image_path)

                # process response
                self.process_exit_detection_response(response)

                # cleanup old images periodically
                if current_time % 3600 < 1:  # once per hour
                    self.cleanup_old_images()

    def detection_worker(self):
        """background thread for exit detection"""
        self.logger.info("exit detection started")

        while self.running:
            try:
                # capture frame for motion detection using exit camera
                frame = self.camera_manager.capture_array("lores", "exit")
                if frame is not None:
                    # process frame
                    self.process_frame(frame)

                # small delay to prevent excessive cpu usage
                time.sleep(0.1)

            except Exception as e:
                self.logger.error(f"exit detection worker error: {e}")
                time.sleep(1)

        self.logger.info("exit detection stopped")

    def start_detection(self):
        """start exit detection thread"""
        if self.detection_thread and self.detection_thread.is_alive():
            return

        self.running = True
        self.detection_thread = threading.Thread(target=self.detection_worker)
        self.detection_thread.daemon = True
        self.detection_thread.start()
        self.logger.info("exit detection thread started")

    def stop_detection(self):
        """stop exit detection thread"""
        self.running = False
        if self.detection_thread:
            self.detection_thread.join(timeout=5)
            self.logger.info("exit detection stopped")

    def cleanup(self):
        """cleanup exit detector resources"""
        self.stop_detection()
        if self.gpio_controller:
            self.gpio_controller.cleanup()
        self.cleanup_old_images()
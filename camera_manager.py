#!/usr/bin/env python3
"""
Dual Camera Manager
Handles entrance and exit cameras with proper switching
"""

import logging
import threading
import time
from pathlib import Path

try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False


class CameraManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.cameras = {}
        self.current_camera = None
        self.camera_lock = threading.Lock()
        self.camera_configs = {
            'entrance': config.get('entrance_camera', {}),
            'exit': config.get('exit_camera', {})
        }

    def initialize_cameras(self):
        """initialize both entrance and exit cameras"""
        if not PICAMERA_AVAILABLE:
            self.logger.error("picamera2 not available")
            return False

        success = True

        try:
            # initialize entrance camera
            if self.camera_configs['entrance'].get('enabled', True):
                entrance_camera = self.create_camera('entrance')
                if entrance_camera:
                    self.cameras['entrance'] = entrance_camera
                    self.logger.info("entrance camera initialized")
                else:
                    self.logger.warning("failed to initialize entrance camera")
                    success = False

            # initialize exit camera (if configured differently)
            if self.camera_configs['exit'].get('enabled', False):
                if self.camera_configs['exit'].get('device_id') != self.camera_configs['entrance'].get('device_id', 0):
                    exit_camera = self.create_camera('exit')
                    if exit_camera:
                        self.cameras['exit'] = exit_camera
                        self.logger.info("exit camera initialized")
                    else:
                        self.logger.warning("failed to initialize exit camera")
                        success = False
                else:
                    # same physical camera, will switch configurations
                    self.cameras['exit'] = self.cameras.get('entrance')
                    self.logger.info("exit camera shares entrance camera device")

            # set default active camera
            if self.cameras:
                self.current_camera = list(self.cameras.keys())[0]
                self.logger.info(f"default camera set to: {self.current_camera}")

            return success and len(self.cameras) > 0

        except Exception as e:
            self.logger.error(f"failed to initialize cameras: {e}")
            return False

    def create_camera(self, camera_type):
        """create and configure a camera instance"""
        try:
            camera_config = self.camera_configs[camera_type]
            device_id = camera_config.get('device_id', 0)

            # create camera instance
            camera = Picamera2(camera_num=device_id)

            # configure camera
            resolution = camera_config.get('resolution', [1920, 1080])
            format_type = camera_config.get('format', 'RGB888')

            config = camera.create_video_configuration(
                main={
                    "size": tuple(resolution),
                    "format": format_type
                },
                lores={
                    "size": (640, 480),
                    "format": format_type
                }
            )

            camera.configure(config)

            # apply camera-specific settings
            controls = camera_config.get('controls', {})
            if controls:
                camera.set_controls(controls)

            camera.start()
            return camera

        except Exception as e:
            self.logger.error(f"failed to create {camera_type} camera: {e}")
            return None

    def switch_camera(self, camera_type):
        """switch to specified camera"""
        with self.camera_lock:
            try:
                if camera_type not in self.cameras:
                    self.logger.error(f"camera {camera_type} not available")
                    return False

                if self.current_camera == camera_type:
                    return True  # already using this camera

                # if same physical device, reconfigure
                if (self.cameras['entrance'] == self.cameras.get('exit') and
                    camera_type in self.cameras):

                    camera = self.cameras[camera_type]
                    camera_config = self.camera_configs[camera_type]

                    # stop current configuration
                    camera.stop()

                    # apply new configuration
                    resolution = camera_config.get('resolution', [1920, 1080])
                    format_type = camera_config.get('format', 'RGB888')

                    config = camera.create_video_configuration(
                        main={
                            "size": tuple(resolution),
                            "format": format_type
                        },
                        lores={
                            "size": (640, 480),
                            "format": format_type
                        }
                    )

                    camera.configure(config)

                    # apply camera-specific controls
                    controls = camera_config.get('controls', {})
                    if controls:
                        camera.set_controls(controls)

                    camera.start()

                self.current_camera = camera_type
                self.logger.info(f"switched to {camera_type} camera")
                return True

            except Exception as e:
                self.logger.error(f"failed to switch to {camera_type} camera: {e}")
                return False

    def get_current_camera(self):
        """get current active camera instance"""
        with self.camera_lock:
            if self.current_camera and self.current_camera in self.cameras:
                return self.cameras[self.current_camera]
            return None

    def capture_image(self, filename, camera_type=None):
        """capture image with specified or current camera"""
        try:
            if camera_type and camera_type != self.current_camera:
                if not self.switch_camera(camera_type):
                    return False

            camera = self.get_current_camera()
            if not camera:
                self.logger.error("no active camera available")
                return False

            camera.capture_file(filename)
            self.logger.info(f"image captured with {self.current_camera} camera: {filename}")
            return True

        except Exception as e:
            self.logger.error(f"failed to capture image: {e}")
            return False

    def capture_array(self, stream="main", camera_type=None):
        """capture image array with specified or current camera"""
        try:
            if camera_type and camera_type != self.current_camera:
                if not self.switch_camera(camera_type):
                    return None

            camera = self.get_current_camera()
            if not camera:
                self.logger.error("no active camera available")
                return None

            return camera.capture_array(stream)

        except Exception as e:
            self.logger.error(f"failed to capture array: {e}")
            return None

    def is_camera_healthy(self, camera_type):
        """check if camera is healthy and responsive"""
        try:
            if camera_type not in self.cameras:
                return False

            # try to capture a test frame
            original_camera = self.current_camera
            if self.switch_camera(camera_type):
                test_frame = self.capture_array("lores", camera_type)
                # switch back to original camera
                if original_camera and original_camera != camera_type:
                    self.switch_camera(original_camera)
                return test_frame is not None
            return False

        except Exception as e:
            self.logger.error(f"camera health check failed for {camera_type}: {e}")
            return False

    def restart_cameras(self, camera_type="both"):
        """restart specified cameras"""
        try:
            if camera_type == "both":
                cameras_to_restart = list(self.cameras.keys())
            elif camera_type in self.cameras:
                cameras_to_restart = [camera_type]
            else:
                self.logger.error(f"unknown camera type: {camera_type}")
                return False

            success = True
            for cam_type in cameras_to_restart:
                if not self.restart_single_camera(cam_type):
                    success = False

            return success

        except Exception as e:
            self.logger.error(f"failed to restart cameras: {e}")
            return False

    def restart_single_camera(self, camera_type):
        """restart a single camera"""
        try:
            with self.camera_lock:
                if camera_type not in self.cameras:
                    return False

                # stop and close current camera
                camera = self.cameras[camera_type]
                camera.stop()
                camera.close()

                # recreate camera
                new_camera = self.create_camera(camera_type)
                if new_camera:
                    self.cameras[camera_type] = new_camera

                    # update other cameras if they share the same device
                    for other_type, other_camera in self.cameras.items():
                        if other_type != camera_type and other_camera == camera:
                            self.cameras[other_type] = new_camera

                    self.logger.info(f"{camera_type} camera restarted successfully")
                    return True
                else:
                    self.logger.error(f"failed to recreate {camera_type} camera")
                    return False

        except Exception as e:
            self.logger.error(f"failed to restart {camera_type} camera: {e}")
            return False

    def get_camera_info(self):
        """get information about available cameras"""
        info = {
            'available_cameras': list(self.cameras.keys()),
            'current_camera': self.current_camera,
            'camera_configs': {}
        }

        for camera_type, config in self.camera_configs.items():
            if camera_type in self.cameras:
                info['camera_configs'][camera_type] = {
                    'device_id': config.get('device_id', 0),
                    'resolution': config.get('resolution', [1920, 1080]),
                    'format': config.get('format', 'RGB888'),
                    'healthy': self.is_camera_healthy(camera_type)
                }

        return info

    def cleanup(self):
        """cleanup camera resources"""
        with self.camera_lock:
            for camera_type, camera in self.cameras.items():
                try:
                    camera.stop()
                    camera.close()
                    self.logger.info(f"{camera_type} camera closed")
                except Exception as e:
                    self.logger.error(f"error closing {camera_type} camera: {e}")

            self.cameras.clear()
            self.current_camera = None
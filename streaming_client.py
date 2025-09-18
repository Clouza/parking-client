#!/usr/bin/env python3
"""
Real-time Video Streaming Client
Streams camera feed to parking-module via WebSocket
"""

import json
import time
import base64
import threading
import logging
from datetime import datetime
import cv2
import socketio
import numpy as np

# Disable picamera2 to avoid resource conflicts with libcamera
PICAMERA_AVAILABLE = False

# libcamera fallback
try:
    from libcamera_wrapper import LibCameraWrapper
    LIBCAMERA_AVAILABLE = True
except ImportError:
    LIBCAMERA_AVAILABLE = False

class StreamingClient:
    def __init__(self, config, shared_camera=None, shared_camera_type=None):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.camera = shared_camera  # use shared camera instance
        self.camera_type = shared_camera_type
        self._shared_camera = shared_camera is not None  # flag for cleanup
        self.streaming_active = False
        self.sio = None
        self.stream_thread = None
        self.setup_socketio()

    def setup_socketio(self):
        """Setup SocketIO connection to parking-module"""
        self.sio = socketio.Client(logger=False, engineio_logger=False)

        @self.sio.event
        def connect():
            self.logger.info("Connected to streaming server")
            # Send camera registration
            self.sio.emit('camera_register', {
                'camera_id': self.config['camera_id'],
                'camera_role': self.config['camera_role'],
                'capabilities': {
                    'streaming': True,
                    'detection': self.config['features']['entrance_detection'] or self.config['features']['exit_detection'],
                    'resolution': self.config['streaming']['resolution']
                }
            })

        @self.sio.event
        def disconnect():
            self.logger.info("Disconnected from streaming server")

        @self.sio.event
        def stream_control(data):
            """Handle stream control commands from server"""
            command = data.get('command')
            if command == 'start_stream':
                self.start_streaming()
            elif command == 'stop_stream':
                self.stop_streaming()
            elif command == 'capture_frame':
                self.capture_and_send_frame()

        @self.sio.event
        def connect_error(data):
            self.logger.error(f"Connection failed: {data}")

    def setup_camera(self):
        """Initialize camera based on configuration"""
        # if shared camera provided, skip camera setup
        if self.camera is not None:
            self.logger.info(f"Using shared camera instance (type: {self.camera_type})")
            return True

        camera_type = self.config.get('camera_type', 'auto')

        # Try Pi camera first if available
        if camera_type in ['auto', 'pi', 'picamera'] and PICAMERA_AVAILABLE:
            try:
                self.camera = Picamera2()

                # Configure based on streaming settings
                stream_config = self.camera.create_video_configuration(
                    main={
                        "size": (
                            self.config['streaming']['resolution']['width'],
                            self.config['streaming']['resolution']['height']
                        ),
                        "format": "RGB888"
                    }
                )

                self.camera.configure(stream_config)
                self.camera.start()
                self.camera_type = "pi"
                self.logger.info("Pi camera initialized for streaming")
                return True

            except Exception as e:
                self.logger.warning(f"Pi camera failed: {e}")

        # Try libcamera fallback for Pi
        if camera_type in ['auto', 'pi', 'picamera'] and LIBCAMERA_AVAILABLE:
            try:
                width = self.config['streaming']['resolution']['width']
                height = self.config['streaming']['resolution']['height']
                self.camera = LibCameraWrapper(width=width, height=height)
                self.camera.start()
                self.camera_type = "pi_libcamera"
                self.logger.info("Pi camera (libcamera) initialized for streaming")
                return True

            except Exception as e:
                self.logger.warning(f"Pi camera libcamera failed: {e}")

        # Fallback to USB camera
        if camera_type in ['auto', 'usb']:
            try:
                camera_device = self.config.get('camera_device', 0)
                self.camera = cv2.VideoCapture(camera_device)
                if not self.camera.isOpened():
                    raise Exception("Cannot open USB camera")

                # Set resolution
                width = self.config['streaming']['resolution']['width']
                height = self.config['streaming']['resolution']['height']
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                self.camera.set(cv2.CAP_PROP_FPS, self.config['streaming']['fps'])

                self.camera_type = "usb"
                self.logger.info("USB camera initialized for streaming")
                return True

            except Exception as e:
                self.logger.error(f"USB camera failed: {e}")

        return False

    def connect_to_server(self):
        """Connect to streaming server"""
        try:
            server_url = self.config['server_url'].replace('http://', '').replace('https://', '')
            if ':' not in server_url:
                server_url += ':5000'

            socketio_url = f"http://{server_url}"
            self.sio.connect(socketio_url, namespaces=['/'])
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect to server: {e}")
            return False

    def capture_frame(self):
        """Capture single frame from camera"""
        if not self.camera:
            return None

        try:
            if self.camera_type == "pi":
                # Capture from Pi camera
                frame = self.camera.capture_array()
                # Convert RGB to BGR for OpenCV compatibility
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            elif self.camera_type == "pi_libcamera":
                # Capture from libcamera wrapper
                frame = self.camera.capture_array()
                # Convert RGB to BGR for OpenCV compatibility
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            else:  # USB camera
                ret, frame = self.camera.read()
                if not ret:
                    return None

            return frame

        except Exception as e:
            self.logger.error(f"Frame capture failed: {e}")
            return None

    def encode_frame(self, frame):
        """Encode frame for transmission"""
        try:
            # Resize if needed
            height, width = frame.shape[:2]
            target_width = self.config['streaming']['resolution']['width']
            target_height = self.config['streaming']['resolution']['height']

            if width != target_width or height != target_height:
                frame = cv2.resize(frame, (target_width, target_height))

            # Encode to JPEG with quality setting
            quality = self.config['streaming']['quality']
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            _, buffer = cv2.imencode('.jpg', frame, encode_param)

            # Convert to base64
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
            return frame_base64

        except Exception as e:
            self.logger.error(f"Frame encoding failed: {e}")
            return None

    def capture_and_send_frame(self):
        """Capture and send single frame"""
        frame = self.capture_frame()
        if frame is not None:
            encoded_frame = self.encode_frame(frame)
            if encoded_frame:
                self.send_frame(encoded_frame)

    def send_frame(self, encoded_frame):
        """Send encoded frame to server"""
        try:
            frame_data = {
                'camera_id': self.config['camera_id'],
                'camera_role': self.config['camera_role'],
                'frame_data': encoded_frame,
                'timestamp': datetime.now().isoformat(),
                'frame_info': {
                    'width': self.config['streaming']['resolution']['width'],
                    'height': self.config['streaming']['resolution']['height'],
                    'quality': self.config['streaming']['quality']
                }
            }

            self.sio.emit('video_frame', frame_data)

        except Exception as e:
            self.logger.error(f"Failed to send frame: {e}")

    def streaming_worker(self):
        """Background thread for continuous streaming"""
        fps = self.config['streaming']['fps']
        frame_interval = 1.0 / fps

        self.logger.info(f"Starting streaming at {fps} FPS")

        while self.streaming_active:
            start_time = time.time()

            # Capture and send frame
            self.capture_and_send_frame()

            # Maintain frame rate
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_interval - elapsed)
            time.sleep(sleep_time)

        self.logger.info("Streaming stopped")

    def start_streaming(self):
        """Start continuous video streaming"""
        if not self.config['streaming']['enabled']:
            self.logger.warning("Streaming disabled in config")
            return False

        if self.streaming_active:
            self.logger.warning("Streaming already active")
            return True

        if not self.camera:
            self.logger.error("Camera not initialized")
            return False

        self.streaming_active = True
        self.stream_thread = threading.Thread(target=self.streaming_worker, daemon=True)
        self.stream_thread.start()

        self.logger.info("Video streaming started")
        return True

    def stop_streaming(self):
        """Stop video streaming"""
        if not self.streaming_active:
            return

        self.streaming_active = False
        if self.stream_thread:
            self.stream_thread.join(timeout=5)

        self.logger.info("Video streaming stopped")

    def send_heartbeat(self):
        """Send heartbeat with streaming status"""
        try:
            heartbeat_data = {
                'camera_id': self.config['camera_id'],
                'camera_role': self.config['camera_role'],
                'status': 'online',
                'streaming_active': self.streaming_active,
                'timestamp': datetime.now().isoformat(),
                'camera_info': {
                    'type': self.camera_type,
                    'resolution': self.config['streaming']['resolution'],
                    'fps': self.config['streaming']['fps']
                }
            }

            self.sio.emit('camera_heartbeat', heartbeat_data)

        except Exception as e:
            self.logger.error(f"Heartbeat failed: {e}")

    def cleanup(self):
        """Cleanup resources"""
        self.stop_streaming()

        if self.sio and self.sio.connected:
            self.sio.disconnect()

        # don't cleanup shared camera - let parent handle it
        if self.camera and not self._shared_camera:
            if self.camera_type == "pi":
                self.camera.stop()
                self.camera.close()
            else:
                self.camera.release()

        self.logger.info("Streaming client cleaned up")

    def run(self):
        """Run streaming client"""
        if not self.setup_camera():
            self.logger.error("Camera setup failed")
            return False

        if not self.connect_to_server():
            self.logger.error("Server connection failed")
            return False

        # Start streaming if enabled
        if self.config['features']['real_time_streaming']:
            self.start_streaming()

        # Heartbeat loop
        heartbeat_interval = self.config['heartbeat']['interval']

        try:
            while True:
                self.send_heartbeat()
                time.sleep(heartbeat_interval)

        except KeyboardInterrupt:
            self.logger.info("Stopping streaming client...")
        finally:
            self.cleanup()

        return True
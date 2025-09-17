#!/usr/bin/env python3
"""
Error Recovery Module
Comprehensive error recovery for camera reconnection, network retry, service restart
"""

import logging
import threading
import time
import signal
import subprocess
import sys
import psutil
from datetime import datetime, timedelta
import requests
from pathlib import Path


class ErrorRecoveryManager:
    def __init__(self, config, camera_manager=None):
        self.config = config
        self.camera_manager = camera_manager
        self.logger = logging.getLogger(__name__)
        self.recovery_config = config.get('error_recovery', {})

        # recovery state tracking
        self.camera_failures = {}
        self.network_failures = 0
        self.service_restarts = 0
        self.last_recovery_attempt = {}

        # recovery limits
        self.max_camera_retries = self.recovery_config.get('max_camera_retries', 5)
        self.max_network_retries = self.recovery_config.get('max_network_retries', 10)
        self.max_service_restarts = self.recovery_config.get('max_service_restarts', 3)
        self.recovery_interval = self.recovery_config.get('recovery_interval', 30)

        # monitoring thread
        self.monitoring_thread = None
        self.running = False

    def start_monitoring(self):
        """start error recovery monitoring"""
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            return

        self.running = True
        self.monitoring_thread = threading.Thread(target=self.monitoring_worker)
        self.monitoring_thread.daemon = True
        self.monitoring_thread.start()
        self.logger.info("error recovery monitoring started")

    def stop_monitoring(self):
        """stop error recovery monitoring"""
        self.running = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=10)
            self.logger.info("error recovery monitoring stopped")

    def monitoring_worker(self):
        """background thread for system monitoring and recovery"""
        check_interval = self.recovery_config.get('check_interval', 60)

        while self.running:
            try:
                # check camera health
                self.check_camera_health()

                # check network connectivity
                self.check_network_health()

                # check memory usage
                self.check_memory_usage()

                # check disk space
                self.check_disk_space()

                # cleanup recovery state
                self.cleanup_recovery_state()

                time.sleep(check_interval)

            except Exception as e:
                self.logger.error(f"error in recovery monitoring: {e}")
                time.sleep(10)

    def check_camera_health(self):
        """check and recover camera health"""
        if not self.camera_manager:
            return

        try:
            camera_info = self.camera_manager.get_camera_info()
            available_cameras = camera_info.get('available_cameras', [])

            for camera_type in available_cameras:
                if not self.camera_manager.is_camera_healthy(camera_type):
                    self.handle_camera_failure(camera_type)
                else:
                    # reset failure count on successful health check
                    if camera_type in self.camera_failures:
                        self.camera_failures[camera_type] = 0

        except Exception as e:
            self.logger.error(f"error checking camera health: {e}")

    def handle_camera_failure(self, camera_type):
        """handle camera failure with progressive recovery"""
        current_time = time.time()

        # initialize failure tracking
        if camera_type not in self.camera_failures:
            self.camera_failures[camera_type] = 0

        # check recovery interval
        last_attempt_key = f"camera_{camera_type}"
        if (last_attempt_key in self.last_recovery_attempt and
            current_time - self.last_recovery_attempt[last_attempt_key] < self.recovery_interval):
            return

        self.camera_failures[camera_type] += 1
        self.last_recovery_attempt[last_attempt_key] = current_time

        failure_count = self.camera_failures[camera_type]

        self.logger.warning(f"camera {camera_type} failure detected (attempt {failure_count}/{self.max_camera_retries})")

        if failure_count <= self.max_camera_retries:
            if self.recover_camera(camera_type, failure_count):
                self.camera_failures[camera_type] = 0
                self.logger.info(f"camera {camera_type} recovery successful")
            else:
                self.logger.error(f"camera {camera_type} recovery failed")
        else:
            self.logger.critical(f"camera {camera_type} exceeded maximum retry attempts")
            self.handle_critical_camera_failure(camera_type)

    def recover_camera(self, camera_type, attempt):
        """attempt camera recovery with progressive strategies"""
        try:
            # strategy 1: simple restart
            if attempt == 1:
                return self.camera_manager.restart_single_camera(camera_type)

            # strategy 2: restart all cameras
            elif attempt == 2:
                return self.camera_manager.restart_cameras("both")

            # strategy 3: reinitialize camera manager
            elif attempt == 3:
                self.camera_manager.cleanup()
                time.sleep(5)
                return self.camera_manager.initialize_cameras()

            # strategy 4: system-level camera reset
            elif attempt == 4:
                self.reset_camera_system()
                time.sleep(10)
                return self.camera_manager.initialize_cameras()

            # strategy 5: service restart
            else:
                return self.restart_service()

        except Exception as e:
            self.logger.error(f"camera recovery attempt {attempt} failed: {e}")
            return False

    def reset_camera_system(self):
        """reset camera system at OS level"""
        try:
            # unload and reload camera modules
            subprocess.run(['sudo', 'modprobe', '-r', 'bcm2835_v4l2'], check=False)
            time.sleep(2)
            subprocess.run(['sudo', 'modprobe', 'bcm2835_v4l2'], check=False)
            time.sleep(3)
            self.logger.info("camera modules reset")
            return True
        except Exception as e:
            self.logger.error(f"failed to reset camera system: {e}")
            return False

    def handle_critical_camera_failure(self, camera_type):
        """handle critical camera failure that requires intervention"""
        self.logger.critical(f"critical camera failure: {camera_type}")

        # disable failed camera in config
        if camera_type == 'entrance':
            self.config['entrance_detection']['enabled'] = False
        elif camera_type == 'exit':
            self.config['exit_detection']['enabled'] = False

        # send alert to server
        self.send_critical_alert('camera_failure', {
            'camera_type': camera_type,
            'failure_count': self.camera_failures[camera_type],
            'timestamp': datetime.now().isoformat()
        })

    def check_network_health(self):
        """check network connectivity and recover if needed"""
        try:
            server_url = self.config.get('server', {}).get('url', '')
            if not server_url:
                return

            # test connectivity with short timeout
            response = requests.get(f"{server_url}/health", timeout=5)
            response.raise_for_status()

            # reset failure count on success
            self.network_failures = 0

        except Exception as e:
            self.handle_network_failure(str(e))

    def handle_network_failure(self, error):
        """handle network failure with progressive recovery"""
        current_time = time.time()

        # check recovery interval
        if ('network' in self.last_recovery_attempt and
            current_time - self.last_recovery_attempt['network'] < self.recovery_interval):
            return

        self.network_failures += 1
        self.last_recovery_attempt['network'] = current_time

        self.logger.warning(f"network failure detected (attempt {self.network_failures}/{self.max_network_retries}): {error}")

        if self.network_failures <= self.max_network_retries:
            if self.recover_network(self.network_failures):
                self.network_failures = 0
                self.logger.info("network recovery successful")
        else:
            self.logger.critical("network exceeded maximum retry attempts")
            self.handle_critical_network_failure()

    def recover_network(self, attempt):
        """attempt network recovery"""
        try:
            # strategy 1: wait and retry
            if attempt <= 3:
                time.sleep(attempt * 5)
                return True

            # strategy 2: restart network interface
            elif attempt == 4:
                subprocess.run(['sudo', 'ip', 'link', 'set', 'wlan0', 'down'], check=False)
                time.sleep(2)
                subprocess.run(['sudo', 'ip', 'link', 'set', 'wlan0', 'up'], check=False)
                time.sleep(10)
                return True

            # strategy 3: restart networking service
            elif attempt == 5:
                subprocess.run(['sudo', 'systemctl', 'restart', 'networking'], check=False)
                time.sleep(15)
                return True

            return False

        except Exception as e:
            self.logger.error(f"network recovery attempt {attempt} failed: {e}")
            return False

    def handle_critical_network_failure(self):
        """handle critical network failure"""
        self.logger.critical("critical network failure detected")

        # attempt system restart as last resort
        if self.service_restarts < self.max_service_restarts:
            self.restart_service()
        else:
            self.logger.critical("maximum service restarts exceeded, manual intervention required")

    def check_memory_usage(self):
        """check memory usage and handle high usage"""
        try:
            memory = psutil.virtual_memory()
            memory_threshold = self.recovery_config.get('memory_threshold', 85)

            if memory.percent > memory_threshold:
                self.logger.warning(f"high memory usage detected: {memory.percent}%")
                self.handle_high_memory_usage()

        except Exception as e:
            self.logger.error(f"error checking memory usage: {e}")

    def handle_high_memory_usage(self):
        """handle high memory usage"""
        try:
            # force garbage collection
            import gc
            gc.collect()

            # restart service if memory is still high
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                self.logger.warning("critical memory usage, restarting service")
                self.restart_service()

        except Exception as e:
            self.logger.error(f"error handling high memory usage: {e}")

    def check_disk_space(self):
        """check disk space and cleanup if needed"""
        try:
            disk_usage = psutil.disk_usage('/')
            disk_threshold = self.recovery_config.get('disk_threshold', 90)

            if (disk_usage.used / disk_usage.total) * 100 > disk_threshold:
                self.logger.warning(f"low disk space detected: {disk_usage.free // (1024**3)}GB free")
                self.handle_low_disk_space()

        except Exception as e:
            self.logger.error(f"error checking disk space: {e}")

    def handle_low_disk_space(self):
        """handle low disk space by cleaning up old files"""
        try:
            # cleanup old images
            self.cleanup_old_files("captures", days=3)
            self.cleanup_old_files("parking_captures", days=2)
            self.cleanup_old_files("exit_captures", days=2)

            # cleanup old logs
            self.cleanup_old_logs()

        except Exception as e:
            self.logger.error(f"error handling low disk space: {e}")

    def cleanup_old_files(self, directory, days=7):
        """cleanup old files from directory"""
        try:
            dir_path = Path(directory)
            if not dir_path.exists():
                return

            cutoff_date = datetime.now() - timedelta(days=days)
            removed_count = 0

            for file_path in dir_path.rglob('*'):
                if file_path.is_file():
                    file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_time < cutoff_date:
                        file_path.unlink()
                        removed_count += 1

            if removed_count > 0:
                self.logger.info(f"cleaned up {removed_count} old files from {directory}")

        except Exception as e:
            self.logger.error(f"error cleaning up {directory}: {e}")

    def cleanup_old_logs(self):
        """cleanup old log files"""
        try:
            log_dir = Path("/var/log/parking-client")
            if log_dir.exists():
                subprocess.run(['sudo', 'journalctl', '--vacuum-time=7d'], check=False)
                self.cleanup_old_files(str(log_dir), days=7)
        except Exception as e:
            self.logger.error(f"error cleaning up logs: {e}")

    def restart_service(self):
        """restart the entire service"""
        try:
            if self.service_restarts >= self.max_service_restarts:
                self.logger.critical("maximum service restarts exceeded")
                return False

            self.service_restarts += 1
            self.logger.warning(f"restarting service (attempt {self.service_restarts})")

            # graceful restart using systemctl
            subprocess.run(['sudo', 'systemctl', 'restart', 'parking-camera'], check=False)
            return True

        except Exception as e:
            self.logger.error(f"failed to restart service: {e}")
            return False

    def send_critical_alert(self, alert_type, data):
        """send critical alert to server"""
        try:
            server_url = self.config.get('server', {}).get('url', '')
            if not server_url:
                return

            alert_payload = {
                'alert_type': alert_type,
                'camera_id': self.config.get('camera', {}).get('id', 'unknown'),
                'timestamp': datetime.now().isoformat(),
                'data': data
            }

            response = requests.post(
                f"{server_url}/api/camera/alert",
                json=alert_payload,
                timeout=10
            )
            response.raise_for_status()
            self.logger.info(f"critical alert sent: {alert_type}")

        except Exception as e:
            self.logger.error(f"failed to send critical alert: {e}")

    def cleanup_recovery_state(self):
        """cleanup old recovery state entries"""
        current_time = time.time()
        cleanup_age = 3600  # 1 hour

        # cleanup old recovery attempts
        to_remove = []
        for key, timestamp in self.last_recovery_attempt.items():
            if current_time - timestamp > cleanup_age:
                to_remove.append(key)

        for key in to_remove:
            del self.last_recovery_attempt[key]

    def get_recovery_status(self):
        """get current recovery status"""
        return {
            'camera_failures': dict(self.camera_failures),
            'network_failures': self.network_failures,
            'service_restarts': self.service_restarts,
            'last_recovery_attempts': dict(self.last_recovery_attempt)
        }
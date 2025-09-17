#!/usr/bin/env python3
"""
Command Handler and Status Reporting Module
Handles server commands and reports system status
"""

import json
import logging
import threading
import time
import shutil
import os
import psutil
from datetime import datetime
from pathlib import Path
import requests


class SystemMonitor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def get_disk_usage(self):
        """get disk usage statistics"""
        try:
            usage = shutil.disk_usage('/')
            return {
                'total': usage.total,
                'used': usage.used,
                'free': usage.free,
                'percent': (usage.used / usage.total) * 100
            }
        except Exception as e:
            self.logger.error(f"failed to get disk usage: {e}")
            return {'total': 0, 'used': 0, 'free': 0, 'percent': 0}

    def get_memory_usage(self):
        """get memory usage statistics"""
        try:
            memory = psutil.virtual_memory()
            return {
                'total': memory.total,
                'used': memory.used,
                'free': memory.available,
                'percent': memory.percent
            }
        except Exception as e:
            self.logger.error(f"failed to get memory usage: {e}")
            return {'total': 0, 'used': 0, 'free': 0, 'percent': 0}

    def get_cpu_usage(self):
        """get cpu usage percentage"""
        try:
            return psutil.cpu_percent(interval=1)
        except Exception as e:
            self.logger.error(f"failed to get cpu usage: {e}")
            return 0

    def get_temperature(self):
        """get system temperature (raspberry pi specific)"""
        try:
            # try raspberry pi temperature file
            temp_file = Path('/sys/class/thermal/thermal_zone0/temp')
            if temp_file.exists():
                with open(temp_file, 'r') as f:
                    temp_millidegrees = int(f.read().strip())
                    return temp_millidegrees / 1000.0
            else:
                # fallback to psutil if available
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            return entries[0].current
                return None
        except Exception as e:
            self.logger.error(f"failed to get temperature: {e}")
            return None

    def get_camera_health(self, camera_manager):
        """get camera health status"""
        try:
            health = {}
            if camera_manager:
                health['entrance_camera'] = camera_manager.is_camera_healthy('entrance')
                health['exit_camera'] = camera_manager.is_camera_healthy('exit')
            return health
        except Exception as e:
            self.logger.error(f"failed to get camera health: {e}")
            return {}


class CommandHandler:
    def __init__(self, config, camera_manager, parking_monitor, entrance_detector, exit_detector):
        self.config = config
        self.camera_manager = camera_manager
        self.parking_monitor = parking_monitor
        self.entrance_detector = entrance_detector
        self.exit_detector = exit_detector
        self.logger = logging.getLogger(__name__)
        self.system_monitor = SystemMonitor()
        self.session = self.setup_http_session()
        self.polling_thread = None
        self.running = False

    def setup_http_session(self):
        """setup http session for command polling"""
        session = requests.Session()
        session.timeout = self.config.get('server', {}).get('timeout', 10)
        return session

    def poll_commands(self):
        """poll server for commands"""
        url = f"{self.config['server']['url']}/api/camera/status"

        try:
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()

            # check for commands in response
            commands = data.get('commands', [])
            for command in commands:
                self.handle_command(command)

            return True
        except requests.exceptions.RequestException as e:
            self.logger.error(f"failed to poll commands: {e}")
            return False
        except Exception as e:
            self.logger.error(f"error processing commands: {e}")
            return False

    def handle_command(self, command):
        """handle individual server command"""
        try:
            cmd_type = command.get('command')
            cmd_id = command.get('id', 'unknown')

            self.logger.info(f"handling command: {cmd_type} (id: {cmd_id})")

            result = {'command_id': cmd_id, 'status': 'success', 'message': ''}

            if cmd_type == 'capture_now':
                result = self.handle_capture_now(command)
            elif cmd_type == 'restart_camera':
                result = self.handle_restart_camera(command)
            elif cmd_type == 'update_config':
                result = self.handle_update_config(command)
            elif cmd_type == 'get_status':
                result = self.handle_get_status(command)
            elif cmd_type == 'open_barrier':
                result = self.handle_open_barrier(command)
            elif cmd_type == 'close_barrier':
                result = self.handle_close_barrier(command)
            else:
                result = {
                    'command_id': cmd_id,
                    'status': 'error',
                    'message': f'unknown command: {cmd_type}'
                }

            # send command result back to server
            self.send_command_result(result)

        except Exception as e:
            self.logger.error(f"error handling command: {e}")
            self.send_command_result({
                'command_id': command.get('id', 'unknown'),
                'status': 'error',
                'message': str(e)
            })

    def handle_capture_now(self, command):
        """handle capture_now command"""
        try:
            area_id = command.get('area_id', 'area1')
            camera_type = command.get('camera_type', 'entrance')

            if self.camera_manager:
                # switch to requested camera
                if self.camera_manager.switch_camera(camera_type):
                    if self.parking_monitor:
                        # capture parking image
                        image_path = self.parking_monitor.capture_parking_image(area_id)
                        if image_path:
                            return {
                                'command_id': command.get('id'),
                                'status': 'success',
                                'message': f'image captured: {image_path.name}',
                                'image_path': str(image_path)
                            }
                        else:
                            return {
                                'command_id': command.get('id'),
                                'status': 'error',
                                'message': 'failed to capture image'
                            }
                    else:
                        return {
                            'command_id': command.get('id'),
                            'status': 'error',
                            'message': 'parking monitor not available'
                        }
                else:
                    return {
                        'command_id': command.get('id'),
                        'status': 'error',
                        'message': f'failed to switch to {camera_type} camera'
                    }
            else:
                return {
                    'command_id': command.get('id'),
                    'status': 'error',
                    'message': 'camera manager not available'
                }

        except Exception as e:
            return {
                'command_id': command.get('id'),
                'status': 'error',
                'message': f'capture failed: {str(e)}'
            }

    def handle_restart_camera(self, command):
        """handle restart_camera command"""
        try:
            camera_type = command.get('camera_type', 'both')

            if self.camera_manager:
                success = self.camera_manager.restart_cameras(camera_type)
                if success:
                    return {
                        'command_id': command.get('id'),
                        'status': 'success',
                        'message': f'{camera_type} camera(s) restarted'
                    }
                else:
                    return {
                        'command_id': command.get('id'),
                        'status': 'error',
                        'message': f'failed to restart {camera_type} camera(s)'
                    }
            else:
                return {
                    'command_id': command.get('id'),
                    'status': 'error',
                    'message': 'camera manager not available'
                }

        except Exception as e:
            return {
                'command_id': command.get('id'),
                'status': 'error',
                'message': f'restart failed: {str(e)}'
            }

    def handle_update_config(self, command):
        """handle update_config command"""
        try:
            new_config = command.get('config', {})

            if not new_config:
                return {
                    'command_id': command.get('id'),
                    'status': 'error',
                    'message': 'no configuration provided'
                }

            # update configuration without restart
            self.update_runtime_config(new_config)

            # save to file
            config_file = Path('config.json')
            backup_file = Path('config.json.backup')

            # create backup
            if config_file.exists():
                shutil.copy2(config_file, backup_file)

            # save new config
            with open(config_file, 'w') as f:
                json.dump(new_config, f, indent=2)

            return {
                'command_id': command.get('id'),
                'status': 'success',
                'message': 'configuration updated successfully'
            }

        except Exception as e:
            return {
                'command_id': command.get('id'),
                'status': 'error',
                'message': f'config update failed: {str(e)}'
            }

    def handle_get_status(self, command):
        """handle get_status command"""
        try:
            status = self.get_system_status()
            return {
                'command_id': command.get('id'),
                'status': 'success',
                'message': 'status retrieved',
                'data': status
            }
        except Exception as e:
            return {
                'command_id': command.get('id'),
                'status': 'error',
                'message': f'status retrieval failed: {str(e)}'
            }

    def handle_open_barrier(self, command):
        """handle open_barrier command"""
        try:
            barrier_type = command.get('barrier_type', 'entrance')
            duration = command.get('duration', 5)

            if barrier_type == 'entrance' and self.entrance_detector:
                self.entrance_detector.gpio_controller.open_gate(duration)
            elif barrier_type == 'exit' and self.exit_detector:
                self.exit_detector.gpio_controller.open_gate(duration)
            else:
                return {
                    'command_id': command.get('id'),
                    'status': 'error',
                    'message': f'{barrier_type} detector not available'
                }

            return {
                'command_id': command.get('id'),
                'status': 'success',
                'message': f'{barrier_type} barrier opened for {duration}s'
            }

        except Exception as e:
            return {
                'command_id': command.get('id'),
                'status': 'error',
                'message': f'barrier operation failed: {str(e)}'
            }

    def handle_close_barrier(self, command):
        """handle close_barrier command"""
        try:
            barrier_type = command.get('barrier_type', 'entrance')

            if barrier_type == 'entrance' and self.entrance_detector:
                self.entrance_detector.gpio_controller.close_gate()
            elif barrier_type == 'exit' and self.exit_detector:
                self.exit_detector.gpio_controller.close_gate()
            else:
                return {
                    'command_id': command.get('id'),
                    'status': 'error',
                    'message': f'{barrier_type} detector not available'
                }

            return {
                'command_id': command.get('id'),
                'status': 'success',
                'message': f'{barrier_type} barrier closed'
            }

        except Exception as e:
            return {
                'command_id': command.get('id'),
                'status': 'error',
                'message': f'barrier operation failed: {str(e)}'
            }

    def update_runtime_config(self, new_config):
        """update runtime configuration without restart"""
        try:
            # update main config
            self.config.update(new_config)

            # notify components of config changes
            if self.parking_monitor and 'parking_monitor' in new_config:
                self.parking_monitor.config.update(new_config)

            if self.entrance_detector and 'entrance_detection' in new_config:
                self.entrance_detector.config.update(new_config)

            if self.exit_detector and 'exit_detection' in new_config:
                self.exit_detector.config.update(new_config)

            self.logger.info("runtime configuration updated")

        except Exception as e:
            self.logger.error(f"failed to update runtime config: {e}")

    def get_system_status(self):
        """get comprehensive system status"""
        try:
            disk = self.system_monitor.get_disk_usage()
            memory = self.system_monitor.get_memory_usage()
            cpu = self.system_monitor.get_cpu_usage()
            temperature = self.system_monitor.get_temperature()
            camera_health = self.system_monitor.get_camera_health(self.camera_manager)

            status = {
                'timestamp': datetime.now().isoformat(),
                'camera_id': self.config.get('camera', {}).get('id', 'unknown'),
                'system': {
                    'disk': disk,
                    'memory': memory,
                    'cpu_percent': cpu,
                    'temperature': temperature
                },
                'cameras': camera_health,
                'services': {
                    'entrance_detection': self.entrance_detector is not None,
                    'exit_detection': self.exit_detector is not None,
                    'parking_monitor': self.parking_monitor is not None
                },
                'uptime': time.time() - getattr(self, 'start_time', time.time())
            }

            # add parking status if available
            if self.parking_monitor:
                parking_status = self.parking_monitor.get_status()
                status['parking_areas'] = parking_status

            return status

        except Exception as e:
            self.logger.error(f"failed to get system status: {e}")
            return {'error': str(e)}

    def send_command_result(self, result):
        """send command execution result back to server"""
        try:
            url = f"{self.config['server']['url']}/api/camera/command-result"
            response = self.session.post(url, json=result)
            response.raise_for_status()
            self.logger.debug(f"command result sent: {result['command_id']}")
        except Exception as e:
            self.logger.error(f"failed to send command result: {e}")

    def send_status_report(self):
        """send periodic status report to server"""
        try:
            status = self.get_system_status()
            url = f"{self.config['server']['url']}/api/camera/status-report"
            response = self.session.post(url, json=status)
            response.raise_for_status()
            self.logger.debug("status report sent successfully")
        except Exception as e:
            self.logger.error(f"failed to send status report: {e}")

    def polling_worker(self):
        """background thread for command polling and status reporting"""
        self.logger.info("command polling started")
        last_status_report = 0
        status_interval = self.config.get('command_handler', {}).get('status_interval', 300)  # 5 minutes
        polling_interval = self.config.get('command_handler', {}).get('polling_interval', 10)  # 10 seconds

        while self.running:
            try:
                # poll for commands
                self.poll_commands()

                # send status report periodically
                current_time = time.time()
                if current_time - last_status_report > status_interval:
                    self.send_status_report()
                    last_status_report = current_time

                time.sleep(polling_interval)

            except Exception as e:
                self.logger.error(f"polling worker error: {e}")
                time.sleep(polling_interval)

    def start_polling(self):
        """start command polling thread"""
        if self.polling_thread and self.polling_thread.is_alive():
            return

        self.running = True
        self.start_time = time.time()
        self.polling_thread = threading.Thread(target=self.polling_worker)
        self.polling_thread.daemon = True
        self.polling_thread.start()
        self.logger.info("command polling thread started")

    def stop_polling(self):
        """stop command polling thread"""
        self.running = False
        if self.polling_thread:
            self.polling_thread.join(timeout=10)
            self.logger.info("command polling stopped")
#!/usr/bin/env python3
"""
System Health Monitor
Comprehensive health monitoring with alerts and automated recovery
"""

import logging
import threading
import time
import subprocess
import json
from datetime import datetime, timedelta
from pathlib import Path
import psutil
import requests


class HealthMonitor:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.health_config = config.get('health_monitoring', {})

        # monitoring intervals
        self.check_interval = self.health_config.get('check_interval', 60)
        self.alert_interval = self.health_config.get('alert_interval', 300)

        # health thresholds
        self.cpu_threshold = self.health_config.get('cpu_threshold', 80)
        self.memory_threshold = self.health_config.get('memory_threshold', 85)
        self.disk_threshold = self.health_config.get('disk_threshold', 90)
        self.temperature_threshold = self.health_config.get('temperature_threshold', 75)

        # service monitoring
        self.services_to_monitor = self.health_config.get('services', ['parking-camera'])

        # monitoring thread
        self.monitor_thread = None
        self.running = False

        # health status
        self.health_status = {
            'overall_status': 'unknown',
            'last_check': None,
            'issues': [],
            'alerts_sent': 0
        }

        # alert tracking
        self.last_alert_time = {}

    def start_monitoring(self):
        """start health monitoring"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitoring_worker)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        self.logger.info("health monitoring started")

    def stop_monitoring(self):
        """stop health monitoring"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=10)
            self.logger.info("health monitoring stopped")

    def monitoring_worker(self):
        """background worker for health monitoring"""
        while self.running:
            try:
                self.perform_health_check()
                time.sleep(self.check_interval)
            except Exception as e:
                self.logger.error(f"health monitoring error: {e}")
                time.sleep(60)

    def perform_health_check(self):
        """perform comprehensive health check"""
        try:
            issues = []
            current_time = datetime.now()

            # check system resources
            resource_issues = self.check_system_resources()
            issues.extend(resource_issues)

            # check services
            service_issues = self.check_services()
            issues.extend(service_issues)

            # check disk space
            disk_issues = self.check_disk_space()
            issues.extend(disk_issues)

            # check network connectivity
            network_issues = self.check_network_connectivity()
            issues.extend(network_issues)

            # check log files
            log_issues = self.check_log_files()
            issues.extend(log_issues)

            # check camera health
            camera_issues = self.check_camera_health()
            issues.extend(camera_issues)

            # update health status
            self.health_status['last_check'] = current_time.isoformat()
            self.health_status['issues'] = issues

            if issues:
                critical_issues = [issue for issue in issues if issue.get('severity') == 'critical']
                if critical_issues:
                    self.health_status['overall_status'] = 'critical'
                else:
                    self.health_status['overall_status'] = 'warning'

                # send alerts if needed
                self.handle_health_alerts(issues)
            else:
                self.health_status['overall_status'] = 'healthy'

            self.log_health_status()

        except Exception as e:
            self.logger.error(f"health check failed: {e}")
            self.health_status['overall_status'] = 'error'

    def check_system_resources(self):
        """check system resource usage"""
        issues = []

        try:
            # check CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.cpu_threshold:
                issues.append({
                    'type': 'high_cpu',
                    'severity': 'critical' if cpu_percent > 95 else 'warning',
                    'message': f"high cpu usage: {cpu_percent}%",
                    'value': cpu_percent,
                    'threshold': self.cpu_threshold
                })

            # check memory usage
            memory = psutil.virtual_memory()
            if memory.percent > self.memory_threshold:
                issues.append({
                    'type': 'high_memory',
                    'severity': 'critical' if memory.percent > 95 else 'warning',
                    'message': f"high memory usage: {memory.percent}%",
                    'value': memory.percent,
                    'threshold': self.memory_threshold
                })

            # check temperature
            temperature = self.get_cpu_temperature()
            if temperature and temperature > self.temperature_threshold:
                issues.append({
                    'type': 'high_temperature',
                    'severity': 'critical' if temperature > 85 else 'warning',
                    'message': f"high temperature: {temperature}°C",
                    'value': temperature,
                    'threshold': self.temperature_threshold
                })

        except Exception as e:
            issues.append({
                'type': 'resource_check_error',
                'severity': 'warning',
                'message': f"failed to check system resources: {e}"
            })

        return issues

    def check_services(self):
        """check status of monitored services"""
        issues = []

        for service_name in self.services_to_monitor:
            try:
                result = subprocess.run(
                    ['systemctl', 'is-active', service_name],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode != 0:
                    issues.append({
                        'type': 'service_down',
                        'severity': 'critical',
                        'message': f"service {service_name} is not running",
                        'service': service_name
                    })

            except Exception as e:
                issues.append({
                    'type': 'service_check_error',
                    'severity': 'warning',
                    'message': f"failed to check service {service_name}: {e}",
                    'service': service_name
                })

        return issues

    def check_disk_space(self):
        """check disk space usage"""
        issues = []

        try:
            # check root filesystem
            disk_usage = psutil.disk_usage('/')
            used_percent = (disk_usage.used / disk_usage.total) * 100

            if used_percent > self.disk_threshold:
                issues.append({
                    'type': 'low_disk_space',
                    'severity': 'critical' if used_percent > 95 else 'warning',
                    'message': f"low disk space: {used_percent:.1f}% used",
                    'value': used_percent,
                    'threshold': self.disk_threshold,
                    'free_gb': disk_usage.free / (1024**3)
                })

            # check specific directories
            directories_to_check = [
                '/var/log/parking-client',
                '/opt/parking-client/captures',
                '/opt/parking-client/parking_captures'
            ]

            for directory in directories_to_check:
                dir_path = Path(directory)
                if dir_path.exists():
                    dir_size = sum(f.stat().st_size for f in dir_path.rglob('*') if f.is_file())
                    dir_size_gb = dir_size / (1024**3)

                    if dir_size_gb > 5:  # warn if directory > 5GB
                        issues.append({
                            'type': 'large_directory',
                            'severity': 'warning',
                            'message': f"large directory: {directory} ({dir_size_gb:.1f}GB)",
                            'directory': directory,
                            'size_gb': dir_size_gb
                        })

        except Exception as e:
            issues.append({
                'type': 'disk_check_error',
                'severity': 'warning',
                'message': f"failed to check disk space: {e}"
            })

        return issues

    def check_network_connectivity(self):
        """check network connectivity"""
        issues = []

        try:
            # check internet connectivity
            response = requests.get('http://8.8.8.8', timeout=5)
            if response.status_code != 200:
                issues.append({
                    'type': 'no_internet',
                    'severity': 'warning',
                    'message': "no internet connectivity"
                })

            # check server connectivity
            server_url = self.config.get('server', {}).get('url', '')
            if server_url:
                try:
                    response = requests.get(f"{server_url}/health", timeout=10)
                    response.raise_for_status()
                except Exception as e:
                    issues.append({
                        'type': 'server_unreachable',
                        'severity': 'critical',
                        'message': f"server unreachable: {e}",
                        'server_url': server_url
                    })

        except Exception as e:
            issues.append({
                'type': 'network_check_error',
                'severity': 'warning',
                'message': f"failed to check network: {e}"
            })

        return issues

    def check_log_files(self):
        """check log file health"""
        issues = []

        try:
            log_dir = Path('/var/log/parking-client')
            if log_dir.exists():
                # check for error patterns in recent logs
                recent_errors = self.scan_recent_logs_for_errors()
                if recent_errors > 10:  # threshold for error count
                    issues.append({
                        'type': 'high_error_rate',
                        'severity': 'warning',
                        'message': f"high error rate in logs: {recent_errors} errors in last hour",
                        'error_count': recent_errors
                    })

                # check log file sizes
                for log_file in log_dir.glob('*.log'):
                    size_mb = log_file.stat().st_size / (1024**2)
                    if size_mb > 100:  # warn if log file > 100MB
                        issues.append({
                            'type': 'large_log_file',
                            'severity': 'warning',
                            'message': f"large log file: {log_file.name} ({size_mb:.1f}MB)",
                            'file': str(log_file),
                            'size_mb': size_mb
                        })

        except Exception as e:
            issues.append({
                'type': 'log_check_error',
                'severity': 'warning',
                'message': f"failed to check logs: {e}"
            })

        return issues

    def check_camera_health(self):
        """check camera hardware health"""
        issues = []

        try:
            # check if camera devices exist
            camera_devices = list(Path('/dev').glob('video*'))
            if not camera_devices:
                issues.append({
                    'type': 'no_camera_devices',
                    'severity': 'critical',
                    'message': "no camera devices found"
                })

            # check camera module loading
            result = subprocess.run(
                ['lsmod'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if 'bcm2835_v4l2' not in result.stdout:
                issues.append({
                    'type': 'camera_module_not_loaded',
                    'severity': 'critical',
                    'message': "camera module not loaded"
                })

        except Exception as e:
            issues.append({
                'type': 'camera_check_error',
                'severity': 'warning',
                'message': f"failed to check camera: {e}"
            })

        return issues

    def get_cpu_temperature(self):
        """get CPU temperature"""
        try:
            temp_file = Path('/sys/class/thermal/thermal_zone0/temp')
            if temp_file.exists():
                with open(temp_file, 'r') as f:
                    temp_millidegrees = int(f.read().strip())
                    return temp_millidegrees / 1000.0
            return None
        except Exception:
            return None

    def scan_recent_logs_for_errors(self):
        """scan recent logs for error patterns"""
        try:
            error_count = 0
            cutoff_time = datetime.now() - timedelta(hours=1)

            log_file = Path('/var/log/parking-client/camera_client.log')
            if log_file.exists():
                with open(log_file, 'r') as f:
                    for line in f:
                        if 'ERROR' in line or 'CRITICAL' in line:
                            error_count += 1

            return error_count
        except Exception:
            return 0

    def handle_health_alerts(self, issues):
        """handle health alerts"""
        try:
            current_time = time.time()
            critical_issues = [issue for issue in issues if issue.get('severity') == 'critical']

            if critical_issues:
                # check if we should send an alert
                last_critical_alert = self.last_alert_time.get('critical', 0)
                if current_time - last_critical_alert > self.alert_interval:
                    self.send_health_alert('critical', critical_issues)
                    self.last_alert_time['critical'] = current_time

            # send periodic status update
            last_status_update = self.last_alert_time.get('status', 0)
            if current_time - last_status_update > 3600:  # hourly status
                self.send_status_update(issues)
                self.last_alert_time['status'] = current_time

        except Exception as e:
            self.logger.error(f"failed to handle alerts: {e}")

    def send_health_alert(self, severity, issues):
        """send health alert to server"""
        try:
            server_url = self.config.get('server', {}).get('url', '')
            if not server_url:
                return

            alert_data = {
                'camera_id': self.config.get('camera', {}).get('id', 'unknown'),
                'alert_type': 'health_alert',
                'severity': severity,
                'timestamp': datetime.now().isoformat(),
                'issues': issues
            }

            response = requests.post(
                f"{server_url}/api/camera/alert",
                json=alert_data,
                timeout=10
            )
            response.raise_for_status()

            self.health_status['alerts_sent'] += 1
            self.logger.info(f"health alert sent: {severity}")

        except Exception as e:
            self.logger.error(f"failed to send health alert: {e}")

    def send_status_update(self, issues):
        """send periodic status update"""
        try:
            server_url = self.config.get('server', {}).get('url', '')
            if not server_url:
                return

            status_data = {
                'camera_id': self.config.get('camera', {}).get('id', 'unknown'),
                'health_status': self.health_status['overall_status'],
                'timestamp': datetime.now().isoformat(),
                'issue_count': len(issues),
                'system_info': {
                    'cpu_percent': psutil.cpu_percent(),
                    'memory_percent': psutil.virtual_memory().percent,
                    'disk_percent': (lambda d: (d.used / d.total) * 100)(psutil.disk_usage('/')),
                    'temperature': self.get_cpu_temperature()
                }
            }

            response = requests.post(
                f"{server_url}/api/camera/health-status",
                json=status_data,
                timeout=10
            )
            response.raise_for_status()

            self.logger.debug("status update sent")

        except Exception as e:
            self.logger.error(f"failed to send status update: {e}")

    def log_health_status(self):
        """log current health status"""
        try:
            status = self.health_status['overall_status']
            issue_count = len(self.health_status['issues'])

            if status == 'healthy':
                self.logger.info("system health check: all systems healthy")
            elif status == 'warning':
                self.logger.warning(f"system health check: {issue_count} warnings detected")
            elif status == 'critical':
                self.logger.critical(f"system health check: {issue_count} issues, including critical problems")
            else:
                self.logger.error("system health check: status unknown")

            # log individual issues
            for issue in self.health_status['issues']:
                if issue.get('severity') == 'critical':
                    self.logger.critical(f"health issue: {issue['message']}")
                else:
                    self.logger.warning(f"health issue: {issue['message']}")

        except Exception as e:
            self.logger.error(f"failed to log health status: {e}")

    def get_health_report(self):
        """get comprehensive health report"""
        try:
            return {
                'status': self.health_status['overall_status'],
                'last_check': self.health_status['last_check'],
                'issues': self.health_status['issues'],
                'alerts_sent': self.health_status['alerts_sent'],
                'system_info': {
                    'cpu_percent': psutil.cpu_percent(),
                    'memory_percent': psutil.virtual_memory().percent,
                    'disk_usage': psutil.disk_usage('/'),
                    'temperature': self.get_cpu_temperature(),
                    'uptime': time.time() - psutil.boot_time()
                }
            }
        except Exception as e:
            self.logger.error(f"failed to generate health report: {e}")
            return {'status': 'error', 'message': str(e)}
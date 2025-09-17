#!/usr/bin/env python3
"""
OTA (Over-The-Air) Update System
Secure automatic updates for parking camera client software
"""

import json
import logging
import threading
import time
import hashlib
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
import requests
import zipfile
import tarfile


class OTAUpdater:
    def __init__(self, config, security_manager=None):
        self.config = config
        self.security_manager = security_manager
        self.logger = logging.getLogger(__name__)
        self.ota_config = config.get('ota_updates', {})

        # update configuration
        self.update_server = self.ota_config.get('server_url', '')
        self.check_interval = self.ota_config.get('check_interval', 3600)  # 1 hour
        self.auto_update = self.ota_config.get('auto_update', False)
        self.backup_before_update = self.ota_config.get('backup_before_update', True)

        # paths
        self.install_dir = Path(self.ota_config.get('install_dir', '/opt/parking-client'))
        self.backup_dir = self.install_dir / 'backups'
        self.temp_dir = Path(tempfile.gettempdir()) / 'parking-client-update'

        # version tracking
        self.current_version = self.get_current_version()

        # update thread
        self.update_thread = None
        self.running = False

        # update status
        self.update_status = {
            'last_check': None,
            'available_version': None,
            'update_in_progress': False,
            'last_update': None,
            'update_result': None
        }

    def get_current_version(self):
        """get current software version"""
        try:
            version_file = self.install_dir / 'VERSION'
            if version_file.exists():
                return version_file.read_text().strip()
            return '1.0.0'
        except Exception as e:
            self.logger.error(f"failed to get current version: {e}")
            return '1.0.0'

    def start_update_service(self):
        """start OTA update service"""
        if not self.update_server:
            self.logger.warning("OTA update server not configured")
            return

        if self.update_thread and self.update_thread.is_alive():
            return

        self.running = True
        self.update_thread = threading.Thread(target=self.update_worker)
        self.update_thread.daemon = True
        self.update_thread.start()
        self.logger.info("OTA update service started")

    def stop_update_service(self):
        """stop OTA update service"""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=10)
            self.logger.info("OTA update service stopped")

    def update_worker(self):
        """background thread for checking updates"""
        while self.running:
            try:
                self.check_for_updates()
                time.sleep(self.check_interval)
            except Exception as e:
                self.logger.error(f"error in update worker: {e}")
                time.sleep(300)  # wait 5 minutes on error

    def check_for_updates(self):
        """check for available updates"""
        try:
            self.logger.debug("checking for updates...")

            # prepare request
            update_check_url = f"{self.update_server}/api/client/updates/check"
            payload = {
                'camera_id': self.config.get('camera', {}).get('id', 'unknown'),
                'current_version': self.current_version,
                'platform': 'raspberry_pi',
                'timestamp': datetime.now().isoformat()
            }

            # make secure request
            if self.security_manager:
                response = self.security_manager.secure_request('POST', update_check_url, json=payload, timeout=30)
            else:
                response = requests.post(update_check_url, json=payload, timeout=30)
                response.raise_for_status()

            update_info = response.json()
            self.update_status['last_check'] = datetime.now().isoformat()

            if update_info.get('update_available', False):
                available_version = update_info.get('version')
                self.update_status['available_version'] = available_version

                self.logger.info(f"update available: {available_version} (current: {self.current_version})")

                if self.auto_update:
                    self.perform_update(update_info)
                else:
                    self.logger.info("auto-update disabled, manual update required")
            else:
                self.logger.debug("no updates available")
                self.update_status['available_version'] = None

        except Exception as e:
            self.logger.error(f"failed to check for updates: {e}")

    def perform_update(self, update_info):
        """perform software update"""
        if self.update_status['update_in_progress']:
            self.logger.warning("update already in progress")
            return False

        try:
            self.update_status['update_in_progress'] = True
            self.logger.info(f"starting update to version {update_info['version']}")

            # create backup if enabled
            if self.backup_before_update:
                backup_path = self.create_backup()
                if not backup_path:
                    raise Exception("failed to create backup")
                self.logger.info(f"backup created: {backup_path}")

            # download update package
            package_path = self.download_update_package(update_info)
            if not package_path:
                raise Exception("failed to download update package")

            # verify package integrity
            if not self.verify_package_integrity(package_path, update_info):
                raise Exception("package integrity verification failed")

            # extract update package
            extracted_path = self.extract_update_package(package_path)
            if not extracted_path:
                raise Exception("failed to extract update package")

            # apply update
            if not self.apply_update(extracted_path, update_info):
                raise Exception("failed to apply update")

            # verify update
            if not self.verify_update(update_info['version']):
                raise Exception("update verification failed")

            # restart service
            self.restart_service()

            self.update_status['update_result'] = 'success'
            self.update_status['last_update'] = datetime.now().isoformat()
            self.logger.info(f"update to version {update_info['version']} completed successfully")

            return True

        except Exception as e:
            self.logger.error(f"update failed: {e}")
            self.update_status['update_result'] = f'failed: {str(e)}'

            # attempt rollback if backup exists
            if self.backup_before_update:
                self.rollback_update()

            return False

        finally:
            self.update_status['update_in_progress'] = False
            self.cleanup_temp_files()

    def download_update_package(self, update_info):
        """download update package from server"""
        try:
            download_url = update_info.get('download_url')
            if not download_url:
                raise Exception("no download URL provided")

            # create temp directory
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            package_path = self.temp_dir / f"update_{update_info['version']}.tar.gz"

            self.logger.info(f"downloading update package from {download_url}")

            # download with progress tracking
            if self.security_manager:
                response = self.security_manager.secure_request('GET', download_url, stream=True, timeout=300)
            else:
                response = requests.get(download_url, stream=True, timeout=300)
                response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0

            with open(package_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)

                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            if downloaded_size % (1024 * 1024) == 0:  # log every MB
                                self.logger.info(f"download progress: {progress:.1f}%")

            self.logger.info("update package downloaded successfully")
            return package_path

        except Exception as e:
            self.logger.error(f"failed to download update package: {e}")
            return None

    def verify_package_integrity(self, package_path, update_info):
        """verify package integrity using checksum"""
        try:
            expected_checksum = update_info.get('checksum')
            if not expected_checksum:
                self.logger.warning("no checksum provided, skipping integrity check")
                return True

            # calculate file checksum
            sha256_hash = hashlib.sha256()
            with open(package_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)

            calculated_checksum = sha256_hash.hexdigest()

            if calculated_checksum != expected_checksum:
                self.logger.error(f"checksum mismatch: expected {expected_checksum}, got {calculated_checksum}")
                return False

            self.logger.info("package integrity verified")
            return True

        except Exception as e:
            self.logger.error(f"failed to verify package integrity: {e}")
            return False

    def extract_update_package(self, package_path):
        """extract update package to temporary directory"""
        try:
            extract_path = self.temp_dir / 'extracted'
            extract_path.mkdir(parents=True, exist_ok=True)

            self.logger.info("extracting update package")

            if package_path.suffix == '.zip':
                with zipfile.ZipFile(package_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_path)
            elif package_path.suffix in ['.tar.gz', '.tgz']:
                with tarfile.open(package_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(extract_path)
            else:
                raise Exception(f"unsupported package format: {package_path.suffix}")

            self.logger.info("package extracted successfully")
            return extract_path

        except Exception as e:
            self.logger.error(f"failed to extract package: {e}")
            return None

    def apply_update(self, extracted_path, update_info):
        """apply the extracted update to the installation directory"""
        try:
            self.logger.info("applying update")

            # stop service before update
            self.stop_service()

            # copy new files
            for item in extracted_path.rglob('*'):
                if item.is_file():
                    # calculate relative path
                    rel_path = item.relative_to(extracted_path)
                    dest_path = self.install_dir / rel_path

                    # create destination directory
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

                    # copy file
                    shutil.copy2(item, dest_path)

                    # set executable permissions for python files
                    if dest_path.suffix == '.py':
                        dest_path.chmod(0o755)

            # update version file
            version_file = self.install_dir / 'VERSION'
            version_file.write_text(update_info['version'])

            # run post-update script if exists
            post_update_script = extracted_path / 'post_update.sh'
            if post_update_script.exists():
                self.logger.info("running post-update script")
                subprocess.run(['bash', str(post_update_script)],
                             cwd=self.install_dir, check=True)

            self.logger.info("update applied successfully")
            return True

        except Exception as e:
            self.logger.error(f"failed to apply update: {e}")
            return False

    def verify_update(self, expected_version):
        """verify that the update was applied correctly"""
        try:
            # check version
            new_version = self.get_current_version()
            if new_version != expected_version:
                self.logger.error(f"version mismatch after update: expected {expected_version}, got {new_version}")
                return False

            # basic syntax check for main python file
            main_script = self.install_dir / 'pi_camera_client.py'
            if main_script.exists():
                result = subprocess.run(['python3', '-m', 'py_compile', str(main_script)],
                                      capture_output=True, text=True)
                if result.returncode != 0:
                    self.logger.error(f"syntax error in updated code: {result.stderr}")
                    return False

            self.logger.info("update verification passed")
            return True

        except Exception as e:
            self.logger.error(f"update verification failed: {e}")
            return False

    def create_backup(self):
        """create backup of current installation"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_v{self.current_version}_{timestamp}.tar.gz"
            backup_path = self.backup_dir / backup_filename

            # create backup directory
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"creating backup: {backup_filename}")

            # create tar.gz backup
            with tarfile.open(backup_path, 'w:gz') as tar:
                for item in self.install_dir.rglob('*'):
                    if (item.is_file() and
                        not item.is_relative_to(self.backup_dir) and
                        not item.is_relative_to(self.temp_dir) and
                        not str(item).endswith('.log')):

                        arcname = item.relative_to(self.install_dir.parent)
                        tar.add(item, arcname=arcname)

            # cleanup old backups (keep last 5)
            backups = sorted(self.backup_dir.glob('backup_*.tar.gz'),
                           key=lambda x: x.stat().st_mtime, reverse=True)
            for old_backup in backups[5:]:
                old_backup.unlink()
                self.logger.info(f"removed old backup: {old_backup.name}")

            return backup_path

        except Exception as e:
            self.logger.error(f"failed to create backup: {e}")
            return None

    def rollback_update(self):
        """rollback to previous version using latest backup"""
        try:
            self.logger.warning("attempting rollback to previous version")

            # find latest backup
            backups = sorted(self.backup_dir.glob('backup_*.tar.gz'),
                           key=lambda x: x.stat().st_mtime, reverse=True)

            if not backups:
                self.logger.error("no backups available for rollback")
                return False

            latest_backup = backups[0]
            self.logger.info(f"rolling back using backup: {latest_backup.name}")

            # stop service
            self.stop_service()

            # extract backup
            with tarfile.open(latest_backup, 'r:gz') as tar:
                tar.extractall(self.install_dir.parent)

            # restart service
            self.restart_service()

            self.logger.info("rollback completed successfully")
            return True

        except Exception as e:
            self.logger.error(f"rollback failed: {e}")
            return False

    def stop_service(self):
        """stop parking camera service"""
        try:
            subprocess.run(['sudo', 'systemctl', 'stop', 'parking-camera'],
                         check=True, timeout=30)
            self.logger.info("service stopped")
        except Exception as e:
            self.logger.error(f"failed to stop service: {e}")

    def restart_service(self):
        """restart parking camera service"""
        try:
            subprocess.run(['sudo', 'systemctl', 'restart', 'parking-camera'],
                         check=True, timeout=30)
            self.logger.info("service restarted")
        except Exception as e:
            self.logger.error(f"failed to restart service: {e}")

    def cleanup_temp_files(self):
        """cleanup temporary files"""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
                self.logger.debug("temporary files cleaned up")
        except Exception as e:
            self.logger.error(f"failed to cleanup temp files: {e}")

    def manual_update_check(self):
        """manually check for updates (non-blocking)"""
        try:
            threading.Thread(target=self.check_for_updates, daemon=True).start()
            return True
        except Exception as e:
            self.logger.error(f"failed to start manual update check: {e}")
            return False

    def manual_update(self, force=False):
        """manually trigger update"""
        try:
            if self.update_status['update_in_progress']:
                return False, "update already in progress"

            if not self.update_status['available_version'] and not force:
                return False, "no update available"

            # check for updates first
            self.check_for_updates()

            if self.update_status['available_version']:
                # get update info from server
                update_info = {
                    'version': self.update_status['available_version'],
                    'download_url': f"{self.update_server}/api/client/updates/download/{self.update_status['available_version']}",
                    'checksum': None  # will be provided by server
                }

                # perform update in background thread
                update_thread = threading.Thread(target=self.perform_update, args=(update_info,), daemon=True)
                update_thread.start()

                return True, "update started"
            else:
                return False, "no update available"

        except Exception as e:
            self.logger.error(f"manual update failed: {e}")
            return False, str(e)

    def get_update_status(self):
        """get current update status"""
        status = dict(self.update_status)
        status['current_version'] = self.current_version
        status['auto_update_enabled'] = self.auto_update
        status['update_server'] = self.update_server
        return status

    def set_auto_update(self, enabled):
        """enable or disable auto-update"""
        self.auto_update = enabled
        self.ota_config['auto_update'] = enabled

        # save to config file
        try:
            config_file = self.install_dir / 'config.json'
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)

                if 'ota_updates' not in config:
                    config['ota_updates'] = {}

                config['ota_updates']['auto_update'] = enabled

                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=2)

                self.logger.info(f"auto-update {'enabled' if enabled else 'disabled'}")

        except Exception as e:
            self.logger.error(f"failed to save auto-update setting: {e}")
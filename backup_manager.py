#!/usr/bin/env python3
"""
Backup and Restore Manager
Comprehensive backup/restore system for configuration and critical images
"""

import json
import logging
import threading
import time
import shutil
import tarfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import schedule


class BackupManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.backup_config = config.get('backup', {})

        # backup configuration
        self.backup_dir = Path(self.backup_config.get('backup_dir', '/opt/parking-client/backups'))
        self.remote_backup_enabled = self.backup_config.get('remote_backup_enabled', False)
        self.remote_backup_url = self.backup_config.get('remote_backup_url', '')

        # retention policies
        self.retention_days = self.backup_config.get('retention_days', 30)
        self.max_local_backups = self.backup_config.get('max_local_backups', 10)

        # backup schedules
        self.daily_backup_time = self.backup_config.get('daily_backup_time', '02:00')
        self.weekly_backup_day = self.backup_config.get('weekly_backup_day', 'sunday')

        # paths to backup
        self.backup_paths = {
            'config': Path('/opt/parking-client/config.json'),
            'security': Path('/opt/parking-client/api.key'),
            'certificates': Path('/opt/parking-client/certs'),
            'critical_images': Path('/opt/parking-client/captures'),
            'parking_images': Path('/opt/parking-client/parking_captures'),
            'exit_images': Path('/opt/parking-client/exit_captures'),
            'database': Path('/opt/parking-client/monitoring.db'),
            'logs': Path('/var/log/parking-client')
        }

        # scheduler thread
        self.scheduler_thread = None
        self.running = False

        # backup database
        self.backup_db_path = self.backup_dir / 'backup_metadata.db'
        self.initialize_backup_database()

    def initialize_backup_database(self):
        """initialize backup metadata database"""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            with sqlite3.connect(self.backup_db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS backups (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        backup_type TEXT NOT NULL,
                        backup_name TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        checksum TEXT,
                        status TEXT NOT NULL,
                        description TEXT
                    )
                ''')

                conn.execute('''
                    CREATE TABLE IF NOT EXISTS restore_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        backup_id INTEGER NOT NULL,
                        restored_at INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        notes TEXT,
                        FOREIGN KEY (backup_id) REFERENCES backups (id)
                    )
                ''')

                conn.execute('CREATE INDEX IF NOT EXISTS idx_backups_created_at ON backups(created_at)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_backups_type ON backups(backup_type)')

                self.logger.info("backup database initialized")

        except Exception as e:
            self.logger.error(f"failed to initialize backup database: {e}")

    def start_scheduler(self):
        """start backup scheduler"""
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            return

        # schedule backups
        schedule.clear()
        schedule.every().day.at(self.daily_backup_time).do(self.create_daily_backup)
        schedule.every().week.at(self.daily_backup_time).do(self.create_weekly_backup)

        self.running = True
        self.scheduler_thread = threading.Thread(target=self.scheduler_worker)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        self.logger.info("backup scheduler started")

    def stop_scheduler(self):
        """stop backup scheduler"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=10)
            self.logger.info("backup scheduler stopped")

    def scheduler_worker(self):
        """background thread for backup scheduling"""
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(60)  # check every minute
            except Exception as e:
                self.logger.error(f"error in backup scheduler: {e}")
                time.sleep(300)  # wait 5 minutes on error

    def create_daily_backup(self):
        """create daily backup (configuration and recent images)"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"daily_backup_{timestamp}"

            # create lightweight daily backup
            backup_items = ['config', 'security', 'database']

            # include recent critical images (last 24 hours)
            recent_cutoff = datetime.now() - timedelta(days=1)
            backup_items.extend(self.get_recent_image_paths(recent_cutoff))

            backup_path = self.create_backup(backup_name, backup_items, 'daily')

            if backup_path:
                self.logger.info(f"daily backup created: {backup_path}")
                return backup_path
            else:
                self.logger.error("daily backup failed")
                return None

        except Exception as e:
            self.logger.error(f"daily backup error: {e}")
            return None

    def create_weekly_backup(self):
        """create weekly backup (full system backup)"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"weekly_backup_{timestamp}"

            # create full backup
            backup_items = list(self.backup_paths.keys())
            backup_path = self.create_backup(backup_name, backup_items, 'weekly')

            if backup_path:
                self.logger.info(f"weekly backup created: {backup_path}")

                # upload to remote if enabled
                if self.remote_backup_enabled:
                    self.upload_backup_to_remote(backup_path)

                return backup_path
            else:
                self.logger.error("weekly backup failed")
                return None

        except Exception as e:
            self.logger.error(f"weekly backup error: {e}")
            return None

    def create_manual_backup(self, backup_name=None, items=None, description=""):
        """create manual backup"""
        try:
            if not backup_name:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"manual_backup_{timestamp}"

            if not items:
                items = ['config', 'security', 'database', 'critical_images']

            backup_path = self.create_backup(backup_name, items, 'manual', description)

            if backup_path:
                self.logger.info(f"manual backup created: {backup_path}")
                return backup_path, "backup created successfully"
            else:
                return None, "backup creation failed"

        except Exception as e:
            self.logger.error(f"manual backup error: {e}")
            return None, str(e)

    def create_backup(self, backup_name, items, backup_type, description=""):
        """create backup archive"""
        try:
            backup_file = self.backup_dir / f"{backup_name}.tar.gz"
            temp_dir = self.backup_dir / f"temp_{backup_name}"

            # create temporary directory for staging
            temp_dir.mkdir(parents=True, exist_ok=True)

            try:
                # copy items to temp directory
                for item in items:
                    if item in self.backup_paths:
                        source_path = self.backup_paths[item]
                        if source_path.exists():
                            dest_path = temp_dir / item

                            if source_path.is_file():
                                dest_path.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(source_path, dest_path)
                            elif source_path.is_dir():
                                shutil.copytree(source_path, dest_path, dirs_exist_ok=True)

                    elif isinstance(item, Path):
                        # direct path provided
                        if item.exists():
                            dest_path = temp_dir / item.name
                            if item.is_file():
                                shutil.copy2(item, dest_path)
                            elif item.is_dir():
                                shutil.copytree(item, dest_path, dirs_exist_ok=True)

                # create backup metadata
                metadata = {
                    'backup_name': backup_name,
                    'backup_type': backup_type,
                    'created_at': datetime.now().isoformat(),
                    'description': description,
                    'items': items,
                    'version': self.get_system_version()
                }

                metadata_file = temp_dir / 'backup_metadata.json'
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)

                # create tar.gz archive
                with tarfile.open(backup_file, 'w:gz') as tar:
                    for item in temp_dir.rglob('*'):
                        if item.is_file():
                            arcname = item.relative_to(temp_dir)
                            tar.add(item, arcname=arcname)

                # calculate checksum
                import hashlib
                checksum = self.calculate_file_checksum(backup_file)

                # record backup in database
                backup_id = self.record_backup(
                    backup_type=backup_type,
                    backup_name=backup_name,
                    file_path=str(backup_file),
                    size_bytes=backup_file.stat().st_size,
                    checksum=checksum,
                    description=description
                )

                self.logger.info(f"backup created: {backup_file} (ID: {backup_id})")

                # cleanup old backups
                self.cleanup_old_backups()

                return backup_file

            finally:
                # cleanup temp directory
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)

        except Exception as e:
            self.logger.error(f"backup creation failed: {e}")
            return None

    def restore_backup(self, backup_id=None, backup_file=None, restore_items=None):
        """restore from backup"""
        try:
            if backup_id:
                # get backup info from database
                backup_info = self.get_backup_info(backup_id)
                if not backup_info:
                    return False, "backup not found"
                backup_file = Path(backup_info['file_path'])

            if not backup_file or not backup_file.exists():
                return False, "backup file not found"

            # verify backup integrity
            if not self.verify_backup_integrity(backup_file):
                return False, "backup integrity check failed"

            # extract backup to temp directory
            temp_dir = self.backup_dir / f"restore_{int(time.time())}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            try:
                with tarfile.open(backup_file, 'r:gz') as tar:
                    tar.extractall(temp_dir)

                # read backup metadata
                metadata_file = temp_dir / 'backup_metadata.json'
                if metadata_file.exists():
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                else:
                    metadata = {'items': restore_items or []}

                # stop services before restore
                self.stop_services()

                # restore items
                restored_items = []
                for item in (restore_items or metadata.get('items', [])):
                    if item in self.backup_paths:
                        source_path = temp_dir / item
                        dest_path = self.backup_paths[item]

                        if source_path.exists():
                            # backup current version
                            if dest_path.exists():
                                backup_current = dest_path.with_suffix(dest_path.suffix + '.backup')
                                if dest_path.is_file():
                                    shutil.copy2(dest_path, backup_current)
                                elif dest_path.is_dir():
                                    if backup_current.exists():
                                        shutil.rmtree(backup_current)
                                    shutil.copytree(dest_path, backup_current)

                            # restore from backup
                            if source_path.is_file():
                                dest_path.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(source_path, dest_path)
                            elif source_path.is_dir():
                                if dest_path.exists():
                                    shutil.rmtree(dest_path)
                                shutil.copytree(source_path, dest_path)

                            restored_items.append(item)
                            self.logger.info(f"restored: {item}")

                # record restore in database
                if backup_id:
                    self.record_restore(backup_id, restored_items)

                # restart services
                self.start_services()

                self.logger.info(f"restore completed: {len(restored_items)} items restored")
                return True, f"restored {len(restored_items)} items successfully"

            finally:
                # cleanup temp directory
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)

        except Exception as e:
            self.logger.error(f"restore failed: {e}")
            return False, str(e)

    def get_recent_image_paths(self, cutoff_date):
        """get paths of recent critical images"""
        recent_paths = []
        try:
            for image_dir in ['critical_images', 'parking_images', 'exit_images']:
                if image_dir in self.backup_paths:
                    dir_path = self.backup_paths[image_dir]
                    if dir_path.exists():
                        for image_file in dir_path.glob('*.jpg'):
                            file_time = datetime.fromtimestamp(image_file.stat().st_mtime)
                            if file_time > cutoff_date:
                                recent_paths.append(image_file)
        except Exception as e:
            self.logger.error(f"error getting recent images: {e}")

        return recent_paths

    def calculate_file_checksum(self, file_path):
        """calculate SHA256 checksum of file"""
        try:
            import hashlib
            sha256_hash = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            self.logger.error(f"checksum calculation failed: {e}")
            return None

    def verify_backup_integrity(self, backup_file):
        """verify backup file integrity"""
        try:
            # check if file can be opened as tar.gz
            with tarfile.open(backup_file, 'r:gz') as tar:
                # try to list contents
                members = tar.getmembers()
                if not members:
                    return False

            # verify against stored checksum if available
            with sqlite3.connect(self.backup_db_path) as conn:
                result = conn.execute(
                    'SELECT checksum FROM backups WHERE file_path = ?',
                    (str(backup_file),)
                ).fetchone()

                if result and result[0]:
                    stored_checksum = result[0]
                    current_checksum = self.calculate_file_checksum(backup_file)
                    if stored_checksum != current_checksum:
                        self.logger.error("backup checksum mismatch")
                        return False

            return True

        except Exception as e:
            self.logger.error(f"backup integrity check failed: {e}")
            return False

    def record_backup(self, backup_type, backup_name, file_path, size_bytes, checksum, description):
        """record backup in database"""
        try:
            with sqlite3.connect(self.backup_db_path) as conn:
                cursor = conn.execute('''
                    INSERT INTO backups
                    (backup_type, backup_name, file_path, created_at, size_bytes, checksum, status, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (backup_type, backup_name, file_path, int(time.time()),
                     size_bytes, checksum, 'completed', description))

                return cursor.lastrowid

        except Exception as e:
            self.logger.error(f"failed to record backup: {e}")
            return None

    def record_restore(self, backup_id, restored_items):
        """record restore operation in database"""
        try:
            with sqlite3.connect(self.backup_db_path) as conn:
                conn.execute('''
                    INSERT INTO restore_history
                    (backup_id, restored_at, status, notes)
                    VALUES (?, ?, ?, ?)
                ''', (backup_id, int(time.time()), 'completed', f"restored: {', '.join(restored_items)}"))

        except Exception as e:
            self.logger.error(f"failed to record restore: {e}")

    def get_backup_info(self, backup_id):
        """get backup information from database"""
        try:
            with sqlite3.connect(self.backup_db_path) as conn:
                result = conn.execute('''
                    SELECT backup_type, backup_name, file_path, created_at, size_bytes, checksum, status, description
                    FROM backups WHERE id = ?
                ''', (backup_id,)).fetchone()

                if result:
                    return {
                        'backup_type': result[0],
                        'backup_name': result[1],
                        'file_path': result[2],
                        'created_at': result[3],
                        'size_bytes': result[4],
                        'checksum': result[5],
                        'status': result[6],
                        'description': result[7]
                    }
                return None

        except Exception as e:
            self.logger.error(f"failed to get backup info: {e}")
            return None

    def list_backups(self, backup_type=None, limit=20):
        """list available backups"""
        try:
            with sqlite3.connect(self.backup_db_path) as conn:
                if backup_type:
                    results = conn.execute('''
                        SELECT id, backup_type, backup_name, file_path, created_at, size_bytes, status
                        FROM backups WHERE backup_type = ?
                        ORDER BY created_at DESC LIMIT ?
                    ''', (backup_type, limit)).fetchall()
                else:
                    results = conn.execute('''
                        SELECT id, backup_type, backup_name, file_path, created_at, size_bytes, status
                        FROM backups ORDER BY created_at DESC LIMIT ?
                    ''', (limit,)).fetchall()

                backups = []
                for row in results:
                    backup_file = Path(row[3])
                    backups.append({
                        'id': row[0],
                        'backup_type': row[1],
                        'backup_name': row[2],
                        'file_path': row[3],
                        'created_at': datetime.fromtimestamp(row[4]).isoformat(),
                        'size_bytes': row[5],
                        'status': row[6],
                        'exists': backup_file.exists()
                    })

                return backups

        except Exception as e:
            self.logger.error(f"failed to list backups: {e}")
            return []

    def cleanup_old_backups(self):
        """cleanup old backups based on retention policy"""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            cutoff_timestamp = int(cutoff_date.timestamp())

            with sqlite3.connect(self.backup_db_path) as conn:
                # get old backups
                old_backups = conn.execute('''
                    SELECT id, file_path FROM backups
                    WHERE created_at < ? AND backup_type != 'weekly'
                    ORDER BY created_at ASC
                ''', (cutoff_timestamp,)).fetchall()

                # also enforce max backup limit
                total_backups = conn.execute('SELECT COUNT(*) FROM backups').fetchone()[0]
                if total_backups > self.max_local_backups:
                    excess_backups = conn.execute('''
                        SELECT id, file_path FROM backups
                        ORDER BY created_at ASC LIMIT ?
                    ''', (total_backups - self.max_local_backups,)).fetchall()
                    old_backups.extend(excess_backups)

                # remove old backups
                removed_count = 0
                for backup_id, file_path in old_backups:
                    try:
                        backup_file = Path(file_path)
                        if backup_file.exists():
                            backup_file.unlink()

                        conn.execute('DELETE FROM backups WHERE id = ?', (backup_id,))
                        removed_count += 1

                    except Exception as e:
                        self.logger.error(f"failed to remove backup {backup_id}: {e}")

                if removed_count > 0:
                    self.logger.info(f"cleaned up {removed_count} old backups")

        except Exception as e:
            self.logger.error(f"backup cleanup failed: {e}")

    def upload_backup_to_remote(self, backup_file):
        """upload backup to remote storage"""
        try:
            if not self.remote_backup_url:
                return False

            # implementation would depend on remote storage type (S3, FTP, etc.)
            self.logger.info(f"uploading backup to remote: {backup_file}")
            # TODO: implement remote upload based on configuration
            return True

        except Exception as e:
            self.logger.error(f"remote backup upload failed: {e}")
            return False

    def stop_services(self):
        """stop services before restore"""
        try:
            import subprocess
            subprocess.run(['sudo', 'systemctl', 'stop', 'parking-camera'], check=False)
            time.sleep(2)
        except Exception as e:
            self.logger.error(f"failed to stop services: {e}")

    def start_services(self):
        """start services after restore"""
        try:
            import subprocess
            subprocess.run(['sudo', 'systemctl', 'start', 'parking-camera'], check=False)
            time.sleep(2)
        except Exception as e:
            self.logger.error(f"failed to start services: {e}")

    def get_system_version(self):
        """get current system version"""
        try:
            version_file = Path('/opt/parking-client/VERSION')
            if version_file.exists():
                return version_file.read_text().strip()
            return '1.0.0'
        except Exception:
            return '1.0.0'

    def get_backup_statistics(self):
        """get backup statistics"""
        try:
            with sqlite3.connect(self.backup_db_path) as conn:
                stats = {}

                # total backups by type
                type_counts = conn.execute('''
                    SELECT backup_type, COUNT(*) FROM backups
                    GROUP BY backup_type
                ''').fetchall()
                stats['by_type'] = dict(type_counts)

                # total storage used
                total_size = conn.execute('SELECT SUM(size_bytes) FROM backups').fetchone()[0] or 0
                stats['total_size_bytes'] = total_size

                # latest backup
                latest = conn.execute('''
                    SELECT backup_name, created_at FROM backups
                    ORDER BY created_at DESC LIMIT 1
                ''').fetchone()

                if latest:
                    stats['latest_backup'] = {
                        'name': latest[0],
                        'created_at': datetime.fromtimestamp(latest[1]).isoformat()
                    }

                # restoration history
                restore_count = conn.execute('SELECT COUNT(*) FROM restore_history').fetchone()[0] or 0
                stats['total_restores'] = restore_count

                return stats

        except Exception as e:
            self.logger.error(f"failed to get backup statistics: {e}")
            return {}
#!/usr/bin/env python3
"""
Parking Area Monitoring Module
Handles periodic parking area surveillance and analysis
"""

import json
import logging
import threading
import time
import base64
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
import cv2
import numpy as np
import requests


class ParkingScheduler:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)

    def get_current_interval(self):
        """get current capture interval based on time"""
        now = datetime.now()
        current_hour = now.hour

        peak_hours = self.config.get('parking_monitor', {}).get('peak_hours', [7, 8, 17, 18, 19])
        peak_interval = self.config.get('parking_monitor', {}).get('peak_interval', 15)
        off_peak_interval = self.config.get('parking_monitor', {}).get('off_peak_interval', 60)

        if current_hour in peak_hours:
            return peak_interval
        else:
            return off_peak_interval


class ImageCache:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.cache_dir = Path(config.get('parking_monitor', {}).get('cache_dir', 'cache'))
        self.cache_dir.mkdir(exist_ok=True)
        self.cache_data = {}
        self.load_cache()

    def load_cache(self):
        """load cache data from file"""
        cache_file = self.cache_dir / 'parking_cache.json'
        try:
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    self.cache_data = json.load(f)
        except Exception as e:
            self.logger.warning(f"failed to load cache: {e}")
            self.cache_data = {}

    def save_cache(self):
        """save cache data to file"""
        cache_file = self.cache_dir / 'parking_cache.json'
        try:
            with open(cache_file, 'w') as f:
                json.dump(self.cache_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"failed to save cache: {e}")

    def get_image_hash(self, image_path):
        """calculate hash of image for comparison"""
        try:
            with open(image_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            self.logger.error(f"failed to calculate image hash: {e}")
            return None

    def has_changed(self, area_id, image_path, threshold=0.1):
        """check if image has changed significantly from last cached version"""
        try:
            current_hash = self.get_image_hash(image_path)
            if not current_hash:
                return True

            # check if we have a cached hash
            cache_key = f"{area_id}_hash"
            if cache_key not in self.cache_data:
                self.cache_data[cache_key] = current_hash
                self.save_cache()
                return True

            # compare with cached hash
            cached_hash = self.cache_data[cache_key]
            if current_hash != cached_hash:
                # perform image comparison for more accurate change detection
                changed = self.compare_images(area_id, image_path, threshold)
                if changed:
                    self.cache_data[cache_key] = current_hash
                    self.save_cache()
                return changed

            return False

        except Exception as e:
            self.logger.error(f"error checking image changes: {e}")
            return True  # assume changed on error

    def compare_images(self, area_id, new_image_path, threshold=0.1):
        """compare new image with cached image using structural similarity"""
        try:
            cache_image_path = self.cache_dir / f"{area_id}_last.jpg"

            if not cache_image_path.exists():
                # save current image as reference
                import shutil
                shutil.copy2(new_image_path, cache_image_path)
                return True

            # load images
            img1 = cv2.imread(str(cache_image_path), cv2.IMREAD_GRAYSCALE)
            img2 = cv2.imread(str(new_image_path), cv2.IMREAD_GRAYSCALE)

            if img1 is None or img2 is None:
                return True

            # resize to same dimensions if needed
            if img1.shape != img2.shape:
                img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

            # calculate structural similarity
            from skimage.metrics import structural_similarity as ssim
            similarity = ssim(img1, img2)

            # if similarity is below threshold, images are significantly different
            changed = (1 - similarity) > threshold

            if changed:
                # update cached reference image
                import shutil
                shutil.copy2(new_image_path, cache_image_path)

            self.logger.debug(f"image similarity: {similarity:.3f}, changed: {changed}")
            return changed

        except ImportError:
            # fallback to pixel difference if scikit-image not available
            return self.compare_images_simple(area_id, new_image_path, threshold)
        except Exception as e:
            self.logger.error(f"error comparing images: {e}")
            return True

    def compare_images_simple(self, area_id, new_image_path, threshold=0.1):
        """simple image comparison using pixel differences"""
        try:
            cache_image_path = self.cache_dir / f"{area_id}_last.jpg"

            if not cache_image_path.exists():
                import shutil
                shutil.copy2(new_image_path, cache_image_path)
                return True

            # load images
            img1 = cv2.imread(str(cache_image_path), cv2.IMREAD_GRAYSCALE)
            img2 = cv2.imread(str(new_image_path), cv2.IMREAD_GRAYSCALE)

            if img1 is None or img2 is None:
                return True

            # resize to same dimensions
            if img1.shape != img2.shape:
                img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))

            # calculate difference
            diff = cv2.absdiff(img1, img2)
            diff_percentage = np.sum(diff > 30) / diff.size

            changed = diff_percentage > threshold

            if changed:
                import shutil
                shutil.copy2(new_image_path, cache_image_path)

            self.logger.debug(f"pixel difference: {diff_percentage:.3f}, changed: {changed}")
            return changed

        except Exception as e:
            self.logger.error(f"error in simple image comparison: {e}")
            return True


class ParkingMonitor:
    def __init__(self, config, camera, session, logger):
        self.config = config
        self.camera = camera
        self.session = session
        self.logger = logger
        self.scheduler = ParkingScheduler(config)
        self.cache = ImageCache(config)
        self.running = False
        self.monitor_thread = None
        self.storage_dir = Path(config.get('parking_monitor', {}).get('storage_dir', 'parking_captures'))
        self.status_data = {}
        self.setup_storage()

    def setup_storage(self):
        """setup parking capture storage directory"""
        self.storage_dir.mkdir(exist_ok=True)
        self.logger.info(f"parking storage directory: {self.storage_dir}")

    def capture_parking_image(self, area_id):
        """capture image for parking analysis"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.storage_dir / f"parking_{area_id}_{timestamp}.jpg"

        try:
            self.camera.capture_file(str(filename))
            self.logger.info(f"parking image captured: {filename}")
            return filename
        except Exception as e:
            self.logger.error(f"failed to capture parking image: {e}")
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

    def send_parking_analysis(self, area_id, image_path, retries=3):
        """send parking analysis request to server"""
        url = f"{self.config['server']['url']}/api/parking-analysis/{area_id}"

        # encode image
        image_data = self.encode_image_base64(image_path)
        if not image_data:
            return None

        payload = {
            "area_id": area_id,
            "image_data": image_data,
            "timestamp": datetime.now().isoformat(),
            "camera_id": self.config['camera']['id']
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
                self.logger.info(f"parking analysis successful: {result}")
                return result

            except requests.exceptions.RequestException as e:
                self.logger.warning(f"parking analysis attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)

        self.logger.error("all parking analysis attempts failed")
        return None

    def process_parking_response(self, area_id, response):
        """process parking analysis response and update status"""
        if not response:
            return

        try:
            vehicle_count = response.get('vehicle_count', 0)
            available_slots = response.get('available_slots', 0)
            total_slots = response.get('total_slots', 0)
            occupancy_rate = response.get('occupancy_rate', 0.0)

            # update status data
            self.status_data[area_id] = {
                'vehicle_count': vehicle_count,
                'available_slots': available_slots,
                'total_slots': total_slots,
                'occupancy_rate': occupancy_rate,
                'last_update': datetime.now().isoformat(),
                'status': 'full' if available_slots == 0 else 'available'
            }

            self.logger.info(f"area {area_id}: vehicles={vehicle_count}, "
                           f"available={available_slots}/{total_slots}, "
                           f"occupancy={occupancy_rate:.1%}")

            # save status to file for web interface
            self.save_status_data()

        except Exception as e:
            self.logger.error(f"failed to process parking response: {e}")

    def save_status_data(self):
        """save current status data to file"""
        try:
            status_file = self.storage_dir / 'current_status.json'
            with open(status_file, 'w') as f:
                json.dump(self.status_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"failed to save status data: {e}")

    def monitor_area(self, area_id):
        """monitor single parking area"""
        try:
            # capture image
            image_path = self.capture_parking_image(area_id)
            if not image_path:
                return

            # check if image has changed significantly
            if not self.cache.has_changed(area_id, image_path):
                self.logger.debug(f"no significant changes in area {area_id}, skipping analysis")
                return

            # send for analysis
            response = self.send_parking_analysis(area_id, image_path)

            # process response
            self.process_parking_response(area_id, response)

        except Exception as e:
            self.logger.error(f"error monitoring area {area_id}: {e}")

    def monitor_worker(self):
        """background thread for parking monitoring"""
        self.logger.info("parking monitoring started")

        while self.running:
            try:
                # get current capture interval
                interval = self.scheduler.get_current_interval()

                # monitor each configured area
                areas = self.config.get('parking_monitor', {}).get('areas', ['area1'])

                for area_id in areas:
                    if not self.running:
                        break
                    self.monitor_area(area_id)

                # wait for next cycle
                time.sleep(interval)

            except Exception as e:
                self.logger.error(f"parking monitor worker error: {e}")
                time.sleep(10)

    def start_monitoring(self):
        """start parking monitoring thread"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_worker)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        self.logger.info("parking monitoring thread started")

    def stop_monitoring(self):
        """stop parking monitoring thread"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=10)
            self.logger.info("parking monitoring stopped")

    def get_status(self):
        """get current parking status for all areas"""
        return self.status_data

    def cleanup_old_images(self):
        """cleanup old parking images"""
        try:
            max_days = self.config.get('parking_monitor', {}).get('max_storage_days', 3)
            cutoff_date = datetime.now() - timedelta(days=max_days)

            for image_file in self.storage_dir.glob('parking_*.jpg'):
                if image_file.stat().st_mtime < cutoff_date.timestamp():
                    image_file.unlink()
                    self.logger.debug(f"deleted old parking image: {image_file}")

        except Exception as e:
            self.logger.error(f"failed to cleanup old parking images: {e}")
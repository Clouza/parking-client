#!/usr/bin/env python3
"""
Performance Optimizer
Image compression, batch processing, memory management, and system optimization
"""

import logging
import threading
import time
import gc
import psutil
import queue
from datetime import datetime, timedelta
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps
import io
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed


class ImageProcessor:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.processing_config = config.get('image_processing', {})

        # compression settings
        self.jpeg_quality = self.processing_config.get('jpeg_quality', 85)
        self.max_resolution = tuple(self.processing_config.get('max_resolution', [1920, 1080]))
        self.enable_compression = self.processing_config.get('enable_compression', True)

        # batch processing
        self.batch_size = self.processing_config.get('batch_size', 10)
        self.max_workers = self.processing_config.get('max_workers', 2)

    def compress_image(self, image_path, output_path=None, quality=None):
        """compress image with optimized settings"""
        try:
            quality = quality or self.jpeg_quality

            if not self.enable_compression:
                return image_path

            with Image.open(image_path) as img:
                # convert to RGB if necessary
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')

                # resize if too large
                if img.size[0] > self.max_resolution[0] or img.size[1] > self.max_resolution[1]:
                    img.thumbnail(self.max_resolution, Image.Resampling.LANCZOS)

                # optimize and save
                if not output_path:
                    output_path = image_path

                img.save(
                    output_path,
                    'JPEG',
                    quality=quality,
                    optimize=True,
                    progressive=True
                )

                self.logger.debug(f"compressed image: {image_path} -> {output_path}")
                return output_path

        except Exception as e:
            self.logger.error(f"image compression failed: {e}")
            return image_path

    def compress_image_to_base64(self, image_path, max_size_kb=1024):
        """compress image and encode to base64 with size limit"""
        try:
            with Image.open(image_path) as img:
                # convert to RGB
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')

                # start with high quality and reduce if needed
                quality = 95
                while quality > 20:
                    # resize if needed
                    current_img = img.copy()
                    if current_img.size[0] > self.max_resolution[0] or current_img.size[1] > self.max_resolution[1]:
                        current_img.thumbnail(self.max_resolution, Image.Resampling.LANCZOS)

                    # compress to memory
                    buffer = io.BytesIO()
                    current_img.save(
                        buffer,
                        'JPEG',
                        quality=quality,
                        optimize=True,
                        progressive=True
                    )

                    # check size
                    size_kb = len(buffer.getvalue()) / 1024
                    if size_kb <= max_size_kb:
                        # encode to base64
                        buffer.seek(0)
                        encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
                        self.logger.debug(f"compressed to {size_kb:.1f}KB with quality {quality}")
                        return encoded

                    quality -= 10

                # if still too large, reduce resolution more aggressively
                while img.size[0] > 640:
                    new_size = (int(img.size[0] * 0.8), int(img.size[1] * 0.8))
                    resized_img = img.resize(new_size, Image.Resampling.LANCZOS)

                    buffer = io.BytesIO()
                    resized_img.save(buffer, 'JPEG', quality=50, optimize=True)

                    size_kb = len(buffer.getvalue()) / 1024
                    if size_kb <= max_size_kb:
                        buffer.seek(0)
                        encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
                        self.logger.debug(f"compressed to {size_kb:.1f}KB with reduced resolution")
                        return encoded

                    img = resized_img

                # fallback: use original with lowest quality
                buffer = io.BytesIO()
                img.save(buffer, 'JPEG', quality=20, optimize=True)
                buffer.seek(0)
                encoded = base64.b64encode(buffer.getvalue()).decode('utf-8')
                self.logger.warning(f"fallback compression used")
                return encoded

        except Exception as e:
            self.logger.error(f"base64 compression failed: {e}")
            return None

    def batch_compress_images(self, image_paths, output_dir=None):
        """compress multiple images in parallel"""
        try:
            if not image_paths:
                return []

            results = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_path = {}

                for image_path in image_paths:
                    if output_dir:
                        output_path = Path(output_dir) / Path(image_path).name
                    else:
                        output_path = None

                    future = executor.submit(self.compress_image, image_path, output_path)
                    future_to_path[future] = image_path

                for future in as_completed(future_to_path):
                    original_path = future_to_path[future]
                    try:
                        compressed_path = future.result()
                        results.append({
                            'original': original_path,
                            'compressed': compressed_path,
                            'success': True
                        })
                    except Exception as e:
                        self.logger.error(f"batch compression failed for {original_path}: {e}")
                        results.append({
                            'original': original_path,
                            'compressed': None,
                            'success': False,
                            'error': str(e)
                        })

            self.logger.info(f"batch compressed {len(results)} images")
            return results

        except Exception as e:
            self.logger.error(f"batch compression error: {e}")
            return []

    def preprocess_for_detection(self, image_array):
        """preprocess image for faster detection"""
        try:
            # resize for detection (smaller = faster)
            detection_size = self.processing_config.get('detection_size', [640, 480])
            resized = cv2.resize(image_array, tuple(detection_size))

            # apply preprocessing if configured
            if self.processing_config.get('enable_preprocessing', True):
                # enhance contrast
                resized = cv2.convertScaleAbs(resized, alpha=1.2, beta=10)

                # reduce noise
                resized = cv2.bilateralFilter(resized, 9, 75, 75)

            return resized

        except Exception as e:
            self.logger.error(f"preprocessing failed: {e}")
            return image_array


class BatchProcessor:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.batch_config = config.get('batch_processing', {})

        # batch settings
        self.batch_size = self.batch_config.get('batch_size', 10)
        self.processing_interval = self.batch_config.get('processing_interval', 60)
        self.max_queue_size = self.batch_config.get('max_queue_size', 100)

        # processing queues
        self.image_queue = queue.Queue(maxsize=self.max_queue_size)
        self.detection_queue = queue.Queue(maxsize=self.max_queue_size)

        # worker threads
        self.processing_thread = None
        self.running = False

    def start_processing(self):
        """start batch processing worker"""
        if self.processing_thread and self.processing_thread.is_alive():
            return

        self.running = True
        self.processing_thread = threading.Thread(target=self.processing_worker)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        self.logger.info("batch processing started")

    def stop_processing(self):
        """stop batch processing worker"""
        self.running = False
        if self.processing_thread:
            self.processing_thread.join(timeout=10)
            self.logger.info("batch processing stopped")

    def processing_worker(self):
        """background worker for batch processing"""
        while self.running:
            try:
                # process image queue
                self.process_image_batch()

                # process detection queue
                self.process_detection_batch()

                time.sleep(self.processing_interval)

            except Exception as e:
                self.logger.error(f"batch processing error: {e}")
                time.sleep(10)

    def add_image_to_queue(self, image_path, metadata=None):
        """add image to processing queue"""
        try:
            if not self.image_queue.full():
                self.image_queue.put({
                    'path': image_path,
                    'metadata': metadata or {},
                    'timestamp': time.time()
                })
                return True
            else:
                self.logger.warning("image queue is full")
                return False
        except Exception as e:
            self.logger.error(f"failed to add image to queue: {e}")
            return False

    def add_detection_to_queue(self, detection_data):
        """add detection data to processing queue"""
        try:
            if not self.detection_queue.full():
                self.detection_queue.put({
                    'data': detection_data,
                    'timestamp': time.time()
                })
                return True
            else:
                self.logger.warning("detection queue is full")
                return False
        except Exception as e:
            self.logger.error(f"failed to add detection to queue: {e}")
            return False

    def process_image_batch(self):
        """process a batch of images"""
        try:
            batch = []
            while len(batch) < self.batch_size and not self.image_queue.empty():
                try:
                    item = self.image_queue.get_nowait()
                    batch.append(item)
                except queue.Empty:
                    break

            if batch:
                self.logger.debug(f"processing image batch of {len(batch)} items")
                # process batch here (compression, cleanup, etc.)
                self.cleanup_old_images(batch)

        except Exception as e:
            self.logger.error(f"image batch processing failed: {e}")

    def process_detection_batch(self):
        """process a batch of detection results"""
        try:
            batch = []
            while len(batch) < self.batch_size and not self.detection_queue.empty():
                try:
                    item = self.detection_queue.get_nowait()
                    batch.append(item)
                except queue.Empty:
                    break

            if batch:
                self.logger.debug(f"processing detection batch of {len(batch)} items")
                # batch send to server or batch process detections

        except Exception as e:
            self.logger.error(f"detection batch processing failed: {e}")

    def cleanup_old_images(self, batch):
        """cleanup old images in batch"""
        try:
            current_time = time.time()
            for item in batch:
                # check if image is old enough to cleanup
                image_path = Path(item['path'])
                if image_path.exists():
                    file_age = current_time - image_path.stat().st_mtime
                    max_age = self.batch_config.get('max_image_age', 3600)  # 1 hour

                    if file_age > max_age:
                        image_path.unlink()
                        self.logger.debug(f"cleaned up old image: {image_path}")

        except Exception as e:
            self.logger.error(f"image cleanup failed: {e}")


class MemoryManager:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.memory_config = config.get('memory_management', {})

        # memory thresholds
        self.warning_threshold = self.memory_config.get('warning_threshold', 80)
        self.critical_threshold = self.memory_config.get('critical_threshold', 90)
        self.cleanup_threshold = self.memory_config.get('cleanup_threshold', 85)

        # monitoring
        self.monitor_thread = None
        self.running = False
        self.check_interval = self.memory_config.get('check_interval', 30)

    def start_monitoring(self):
        """start memory monitoring"""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitoring_worker)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        self.logger.info("memory monitoring started")

    def stop_monitoring(self):
        """stop memory monitoring"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=10)
            self.logger.info("memory monitoring stopped")

    def monitoring_worker(self):
        """background worker for memory monitoring"""
        while self.running:
            try:
                self.check_memory_usage()
                time.sleep(self.check_interval)
            except Exception as e:
                self.logger.error(f"memory monitoring error: {e}")
                time.sleep(60)

    def check_memory_usage(self):
        """check current memory usage and take action if needed"""
        try:
            memory = psutil.virtual_memory()
            usage_percent = memory.percent

            if usage_percent > self.critical_threshold:
                self.logger.critical(f"critical memory usage: {usage_percent}%")
                self.emergency_cleanup()
            elif usage_percent > self.cleanup_threshold:
                self.logger.warning(f"high memory usage: {usage_percent}%, starting cleanup")
                self.cleanup_memory()
            elif usage_percent > self.warning_threshold:
                self.logger.warning(f"memory usage warning: {usage_percent}%")

        except Exception as e:
            self.logger.error(f"memory check failed: {e}")

    def cleanup_memory(self):
        """perform memory cleanup"""
        try:
            # force garbage collection
            collected = gc.collect()
            self.logger.debug(f"garbage collector freed {collected} objects")

            # clear opencv cache if available
            try:
                cv2.setUseOptimized(False)
                cv2.setUseOptimized(True)
            except Exception:
                pass

            # clear image caches
            self.clear_image_caches()

            # log memory after cleanup
            memory = psutil.virtual_memory()
            self.logger.info(f"memory after cleanup: {memory.percent}%")

        except Exception as e:
            self.logger.error(f"memory cleanup failed: {e}")

    def emergency_cleanup(self):
        """emergency memory cleanup for critical situations"""
        try:
            self.logger.critical("performing emergency memory cleanup")

            # aggressive garbage collection
            for _ in range(3):
                gc.collect()

            # clear all caches
            self.clear_image_caches()

            # restart camera if memory is still critical
            memory = psutil.virtual_memory()
            if memory.percent > self.critical_threshold:
                self.logger.critical("memory still critical after cleanup, restarting camera service")
                # signal for service restart
                self.request_service_restart()

        except Exception as e:
            self.logger.error(f"emergency cleanup failed: {e}")

    def clear_image_caches(self):
        """clear image processing caches"""
        try:
            # clear PIL image cache
            try:
                from PIL import Image
                Image.MAX_IMAGE_PIXELS = None
            except Exception:
                pass

            # clear any application-specific caches
            # this would be implemented based on specific cache usage

        except Exception as e:
            self.logger.error(f"cache clearing failed: {e}")

    def request_service_restart(self):
        """request service restart due to memory issues"""
        try:
            # create restart flag file
            restart_flag = Path('/tmp/parking_camera_restart_requested')
            restart_flag.touch()
            self.logger.critical("service restart requested due to memory issues")
        except Exception as e:
            self.logger.error(f"failed to request service restart: {e}")

    def get_memory_stats(self):
        """get current memory statistics"""
        try:
            memory = psutil.virtual_memory()
            return {
                'total_gb': memory.total / (1024**3),
                'available_gb': memory.available / (1024**3),
                'used_gb': memory.used / (1024**3),
                'percent_used': memory.percent,
                'warning_threshold': self.warning_threshold,
                'critical_threshold': self.critical_threshold
            }
        except Exception as e:
            self.logger.error(f"failed to get memory stats: {e}")
            return {}


class PerformanceOptimizer:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # initialize components
        self.image_processor = ImageProcessor(config)
        self.batch_processor = BatchProcessor(config)
        self.memory_manager = MemoryManager(config)

        # performance metrics
        self.performance_metrics = {
            'images_processed': 0,
            'compression_ratio': 0,
            'processing_time_avg': 0,
            'memory_cleanups': 0
        }

    def start_optimization(self):
        """start all optimization components"""
        try:
            self.batch_processor.start_processing()
            self.memory_manager.start_monitoring()
            self.logger.info("performance optimization started")
        except Exception as e:
            self.logger.error(f"failed to start optimization: {e}")

    def stop_optimization(self):
        """stop all optimization components"""
        try:
            self.batch_processor.stop_processing()
            self.memory_manager.stop_monitoring()
            self.logger.info("performance optimization stopped")
        except Exception as e:
            self.logger.error(f"failed to stop optimization: {e}")

    def optimize_image_for_transmission(self, image_path, max_size_kb=1024):
        """optimize image for network transmission"""
        start_time = time.time()
        try:
            optimized_base64 = self.image_processor.compress_image_to_base64(image_path, max_size_kb)

            if optimized_base64:
                processing_time = time.time() - start_time
                self.update_performance_metrics(processing_time, len(optimized_base64))
                return optimized_base64

            return None

        except Exception as e:
            self.logger.error(f"image optimization failed: {e}")
            return None

    def update_performance_metrics(self, processing_time, compressed_size):
        """update performance metrics"""
        try:
            self.performance_metrics['images_processed'] += 1

            # update average processing time
            current_avg = self.performance_metrics['processing_time_avg']
            count = self.performance_metrics['images_processed']
            self.performance_metrics['processing_time_avg'] = (current_avg * (count - 1) + processing_time) / count

        except Exception as e:
            self.logger.error(f"failed to update metrics: {e}")

    def get_performance_stats(self):
        """get current performance statistics"""
        try:
            stats = dict(self.performance_metrics)
            stats.update(self.memory_manager.get_memory_stats())
            return stats
        except Exception as e:
            self.logger.error(f"failed to get performance stats: {e}")
            return {}
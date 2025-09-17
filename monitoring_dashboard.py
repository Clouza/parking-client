#!/usr/bin/env python3
"""
Monitoring Dashboard
Advanced monitoring with uptime, capture statistics, error rates, and system metrics
"""

import json
import logging
import threading
import time
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, deque
import psutil
from flask import Flask, render_template, jsonify, request


class StatisticsCollector:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.db_path = Path(config.get('monitoring', {}).get('database', 'monitoring.db'))
        self.collection_thread = None
        self.running = False

        # in-memory statistics for real-time updates
        self.capture_stats = defaultdict(int)
        self.error_counts = defaultdict(int)
        self.detection_stats = defaultdict(int)
        self.performance_metrics = deque(maxlen=1440)  # 24 hours at 1-minute intervals

        self.start_time = time.time()
        self.initialize_database()

    def initialize_database(self):
        """initialize sqlite database for statistics storage"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS system_metrics (
                        timestamp INTEGER,
                        cpu_percent REAL,
                        memory_percent REAL,
                        disk_percent REAL,
                        temperature REAL,
                        uptime INTEGER
                    )
                ''')

                conn.execute('''
                    CREATE TABLE IF NOT EXISTS capture_events (
                        timestamp INTEGER,
                        camera_type TEXT,
                        event_type TEXT,
                        area_id TEXT,
                        success INTEGER,
                        processing_time REAL
                    )
                ''')

                conn.execute('''
                    CREATE TABLE IF NOT EXISTS error_events (
                        timestamp INTEGER,
                        error_type TEXT,
                        component TEXT,
                        message TEXT,
                        severity INTEGER
                    )
                ''')

                conn.execute('''
                    CREATE TABLE IF NOT EXISTS detection_results (
                        timestamp INTEGER,
                        detection_type TEXT,
                        confidence REAL,
                        license_plate TEXT,
                        access_granted INTEGER,
                        processing_time REAL
                    )
                ''')

                # create indexes for better query performance
                conn.execute('CREATE INDEX IF NOT EXISTS idx_system_timestamp ON system_metrics(timestamp)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_capture_timestamp ON capture_events(timestamp)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_error_timestamp ON error_events(timestamp)')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_detection_timestamp ON detection_results(timestamp)')

                self.logger.info("monitoring database initialized")

        except Exception as e:
            self.logger.error(f"failed to initialize monitoring database: {e}")

    def start_collection(self):
        """start statistics collection thread"""
        if self.collection_thread and self.collection_thread.is_alive():
            return

        self.running = True
        self.collection_thread = threading.Thread(target=self.collection_worker)
        self.collection_thread.daemon = True
        self.collection_thread.start()
        self.logger.info("statistics collection started")

    def stop_collection(self):
        """stop statistics collection thread"""
        self.running = False
        if self.collection_thread:
            self.collection_thread.join(timeout=10)
            self.logger.info("statistics collection stopped")

    def collection_worker(self):
        """background thread for statistics collection"""
        while self.running:
            try:
                self.collect_system_metrics()
                time.sleep(60)  # collect every minute
            except Exception as e:
                self.logger.error(f"error in statistics collection: {e}")
                time.sleep(10)

    def collect_system_metrics(self):
        """collect and store system performance metrics"""
        try:
            timestamp = int(time.time())
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            uptime = int(time.time() - self.start_time)

            # get temperature
            temperature = None
            try:
                temp_file = Path('/sys/class/thermal/thermal_zone0/temp')
                if temp_file.exists():
                    temperature = int(temp_file.read_text()) / 1000.0
            except Exception:
                pass

            # store in database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO system_metrics
                    (timestamp, cpu_percent, memory_percent, disk_percent, temperature, uptime)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (timestamp, cpu_percent, memory.percent,
                     (disk.used / disk.total) * 100, temperature, uptime))

            # update in-memory metrics
            self.performance_metrics.append({
                'timestamp': timestamp,
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'disk_percent': (disk.used / disk.total) * 100,
                'temperature': temperature,
                'uptime': uptime
            })

        except Exception as e:
            self.logger.error(f"error collecting system metrics: {e}")

    def record_capture_event(self, camera_type, event_type, area_id=None, success=True, processing_time=0):
        """record capture event"""
        try:
            timestamp = int(time.time())

            # update in-memory stats
            self.capture_stats[f"{camera_type}_{event_type}"] += 1
            if success:
                self.capture_stats[f"{camera_type}_success"] += 1
            else:
                self.capture_stats[f"{camera_type}_failed"] += 1

            # store in database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO capture_events
                    (timestamp, camera_type, event_type, area_id, success, processing_time)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (timestamp, camera_type, event_type, area_id, 1 if success else 0, processing_time))

        except Exception as e:
            self.logger.error(f"error recording capture event: {e}")

    def record_error_event(self, error_type, component, message, severity=1):
        """record error event"""
        try:
            timestamp = int(time.time())

            # update in-memory stats
            self.error_counts[error_type] += 1
            self.error_counts[f"{component}_errors"] += 1

            # store in database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO error_events
                    (timestamp, error_type, component, message, severity)
                    VALUES (?, ?, ?, ?, ?)
                ''', (timestamp, error_type, component, message, severity))

        except Exception as e:
            self.logger.error(f"error recording error event: {e}")

    def record_detection_result(self, detection_type, confidence, license_plate, access_granted, processing_time):
        """record detection result"""
        try:
            timestamp = int(time.time())

            # update in-memory stats
            self.detection_stats[f"{detection_type}_total"] += 1
            if access_granted:
                self.detection_stats[f"{detection_type}_granted"] += 1
            else:
                self.detection_stats[f"{detection_type}_denied"] += 1

            # store in database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO detection_results
                    (timestamp, detection_type, confidence, license_plate, access_granted, processing_time)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (timestamp, detection_type, confidence, license_plate, 1 if access_granted else 0, processing_time))

        except Exception as e:
            self.logger.error(f"error recording detection result: {e}")

    def get_statistics_summary(self, hours=24):
        """get statistics summary for specified time period"""
        try:
            cutoff_time = int(time.time()) - (hours * 3600)

            with sqlite3.connect(self.db_path) as conn:
                # system metrics
                system_stats = conn.execute('''
                    SELECT
                        AVG(cpu_percent) as avg_cpu,
                        AVG(memory_percent) as avg_memory,
                        AVG(disk_percent) as avg_disk,
                        AVG(temperature) as avg_temp,
                        MAX(uptime) as max_uptime
                    FROM system_metrics
                    WHERE timestamp > ?
                ''', (cutoff_time,)).fetchone()

                # capture statistics
                capture_stats = conn.execute('''
                    SELECT
                        camera_type,
                        event_type,
                        COUNT(*) as count,
                        SUM(success) as success_count,
                        AVG(processing_time) as avg_processing_time
                    FROM capture_events
                    WHERE timestamp > ?
                    GROUP BY camera_type, event_type
                ''', (cutoff_time,)).fetchall()

                # error statistics
                error_stats = conn.execute('''
                    SELECT
                        error_type,
                        component,
                        COUNT(*) as count,
                        MAX(timestamp) as last_occurrence
                    FROM error_events
                    WHERE timestamp > ?
                    GROUP BY error_type, component
                ''', (cutoff_time,)).fetchall()

                # detection statistics
                detection_stats = conn.execute('''
                    SELECT
                        detection_type,
                        COUNT(*) as total,
                        SUM(access_granted) as granted,
                        AVG(confidence) as avg_confidence,
                        AVG(processing_time) as avg_processing_time
                    FROM detection_results
                    WHERE timestamp > ?
                    GROUP BY detection_type
                ''', (cutoff_time,)).fetchall()

                return {
                    'system': dict(zip(['avg_cpu', 'avg_memory', 'avg_disk', 'avg_temp', 'max_uptime'], system_stats or [])),
                    'captures': [dict(zip(['camera_type', 'event_type', 'count', 'success_count', 'avg_processing_time'], row)) for row in capture_stats],
                    'errors': [dict(zip(['error_type', 'component', 'count', 'last_occurrence'], row)) for row in error_stats],
                    'detections': [dict(zip(['detection_type', 'total', 'granted', 'avg_confidence', 'avg_processing_time'], row)) for row in detection_stats]
                }

        except Exception as e:
            self.logger.error(f"error getting statistics summary: {e}")
            return {}

    def get_real_time_metrics(self):
        """get real-time performance metrics"""
        try:
            current_metrics = {
                'timestamp': int(time.time()),
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_percent': (lambda d: (d.used / d.total) * 100)(psutil.disk_usage('/')),
                'uptime': int(time.time() - self.start_time)
            }

            # add temperature if available
            try:
                temp_file = Path('/sys/class/thermal/thermal_zone0/temp')
                if temp_file.exists():
                    current_metrics['temperature'] = int(temp_file.read_text()) / 1000.0
            except Exception:
                current_metrics['temperature'] = None

            return current_metrics

        except Exception as e:
            self.logger.error(f"error getting real-time metrics: {e}")
            return {}

    def cleanup_old_data(self, days=30):
        """cleanup old monitoring data"""
        try:
            cutoff_time = int(time.time()) - (days * 24 * 3600)

            with sqlite3.connect(self.db_path) as conn:
                tables = ['system_metrics', 'capture_events', 'error_events', 'detection_results']
                for table in tables:
                    result = conn.execute(f'DELETE FROM {table} WHERE timestamp < ?', (cutoff_time,))
                    self.logger.info(f"cleaned up {result.rowcount} old records from {table}")

        except Exception as e:
            self.logger.error(f"error cleaning up old data: {e}")


class MonitoringDashboard:
    def __init__(self, config, statistics_collector):
        self.config = config
        self.statistics_collector = statistics_collector
        self.logger = logging.getLogger(__name__)
        self.app = Flask(__name__)
        self.setup_routes()
        self.server_thread = None
        self.running = False

    def setup_routes(self):
        """setup flask routes for monitoring dashboard"""

        @self.app.route('/')
        def monitoring_index():
            return render_template('monitoring.html')

        @self.app.route('/api/metrics/realtime')
        def get_realtime_metrics():
            """get real-time system metrics"""
            try:
                metrics = self.statistics_collector.get_real_time_metrics()
                return jsonify({'status': 'success', 'data': metrics})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/api/metrics/history')
        def get_metrics_history():
            """get historical metrics data"""
            try:
                hours = int(request.args.get('hours', 24))
                data = []

                # get recent performance metrics
                recent_metrics = list(self.statistics_collector.performance_metrics)
                cutoff_time = time.time() - (hours * 3600)

                for metric in recent_metrics:
                    if metric['timestamp'] > cutoff_time:
                        data.append(metric)

                return jsonify({'status': 'success', 'data': data})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/api/statistics/summary')
        def get_statistics_summary():
            """get statistics summary"""
            try:
                hours = int(request.args.get('hours', 24))
                summary = self.statistics_collector.get_statistics_summary(hours)
                return jsonify({'status': 'success', 'data': summary})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/api/statistics/captures')
        def get_capture_statistics():
            """get capture statistics"""
            try:
                stats = dict(self.statistics_collector.capture_stats)
                return jsonify({'status': 'success', 'data': stats})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/api/statistics/errors')
        def get_error_statistics():
            """get error statistics"""
            try:
                stats = dict(self.statistics_collector.error_counts)
                return jsonify({'status': 'success', 'data': stats})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/api/statistics/detections')
        def get_detection_statistics():
            """get detection statistics"""
            try:
                stats = dict(self.statistics_collector.detection_stats)
                return jsonify({'status': 'success', 'data': stats})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/api/health')
        def health_check():
            """health check endpoint"""
            try:
                uptime = int(time.time() - self.statistics_collector.start_time)
                return jsonify({
                    'status': 'healthy',
                    'uptime': uptime,
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500

    def create_monitoring_template(self):
        """create monitoring dashboard html template"""
        template_dir = Path('templates')
        template_dir.mkdir(exist_ok=True)

        template_file = template_dir / 'monitoring.html'
        if not template_file.exists():
            html_content = '''<!DOCTYPE html>
<html>
<head>
    <title>Parking System Monitoring</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }
        .header { text-align: center; margin-bottom: 30px; }
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .metric-card { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .metric-title { font-size: 1.1em; font-weight: bold; margin-bottom: 10px; color: #333; }
        .metric-value { font-size: 2em; font-weight: bold; margin: 10px 0; }
        .metric-value.good { color: #4CAF50; }
        .metric-value.warning { color: #FF9800; }
        .metric-value.critical { color: #f44336; }
        .chart-container { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .statistics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; }
        .stat-item { background: #f8f9fa; padding: 10px; border-radius: 4px; margin: 5px 0; }
        .uptime { font-size: 1.2em; color: #2196F3; }
        .refresh-btn { background: #2196F3; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; margin: 10px; }
        .refresh-btn:hover { background: #1976D2; }
        .status-online { color: #4CAF50; }
        .status-offline { color: #f44336; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Parking System Monitoring Dashboard</h1>
        <div class="uptime" id="uptime">System Uptime: Loading...</div>
        <button class="refresh-btn" onclick="refreshData()">Refresh Data</button>
        <button class="refresh-btn" onclick="toggleAutoRefresh()">Auto Refresh: <span id="autoRefreshStatus">ON</span></button>
    </div>

    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-title">CPU Usage</div>
            <div class="metric-value" id="cpuUsage">--</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Memory Usage</div>
            <div class="metric-value" id="memoryUsage">--</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Disk Usage</div>
            <div class="metric-value" id="diskUsage">--</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Temperature</div>
            <div class="metric-value" id="temperature">--</div>
        </div>
    </div>

    <div class="chart-container">
        <h2>System Performance (Last 24 Hours)</h2>
        <canvas id="metricsChart" width="400" height="200"></canvas>
    </div>

    <div class="statistics-grid">
        <div class="metric-card">
            <div class="metric-title">Capture Statistics</div>
            <div id="captureStats">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Detection Statistics</div>
            <div id="detectionStats">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">Error Statistics</div>
            <div id="errorStats">Loading...</div>
        </div>
        <div class="metric-card">
            <div class="metric-title">System Summary</div>
            <div id="systemSummary">Loading...</div>
        </div>
    </div>

    <script>
        let autoRefresh = true;
        let metricsChart;

        function formatUptime(seconds) {
            const days = Math.floor(seconds / 86400);
            const hours = Math.floor((seconds % 86400) / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            return `${days}d ${hours}h ${minutes}m`;
        }

        function getValueClass(value, type) {
            switch(type) {
                case 'cpu':
                case 'memory':
                case 'disk':
                    if (value > 90) return 'critical';
                    if (value > 75) return 'warning';
                    return 'good';
                case 'temperature':
                    if (value > 80) return 'critical';
                    if (value > 65) return 'warning';
                    return 'good';
                default:
                    return 'good';
            }
        }

        async function loadRealtimeMetrics() {
            try {
                const response = await fetch('/api/metrics/realtime');
                const result = await response.json();

                if (result.status === 'success') {
                    const data = result.data;

                    document.getElementById('cpuUsage').textContent = data.cpu_percent.toFixed(1) + '%';
                    document.getElementById('cpuUsage').className = 'metric-value ' + getValueClass(data.cpu_percent, 'cpu');

                    document.getElementById('memoryUsage').textContent = data.memory_percent.toFixed(1) + '%';
                    document.getElementById('memoryUsage').className = 'metric-value ' + getValueClass(data.memory_percent, 'memory');

                    document.getElementById('diskUsage').textContent = data.disk_percent.toFixed(1) + '%';
                    document.getElementById('diskUsage').className = 'metric-value ' + getValueClass(data.disk_percent, 'disk');

                    const temp = data.temperature ? data.temperature.toFixed(1) + '°C' : 'N/A';
                    document.getElementById('temperature').textContent = temp;
                    if (data.temperature) {
                        document.getElementById('temperature').className = 'metric-value ' + getValueClass(data.temperature, 'temperature');
                    }

                    document.getElementById('uptime').textContent = 'System Uptime: ' + formatUptime(data.uptime);
                }
            } catch (error) {
                console.error('Failed to load realtime metrics:', error);
            }
        }

        async function loadMetricsHistory() {
            try {
                const response = await fetch('/api/metrics/history?hours=24');
                const result = await response.json();

                if (result.status === 'success' && result.data.length > 0) {
                    updateMetricsChart(result.data);
                }
            } catch (error) {
                console.error('Failed to load metrics history:', error);
            }
        }

        function updateMetricsChart(data) {
            const ctx = document.getElementById('metricsChart').getContext('2d');

            if (metricsChart) {
                metricsChart.destroy();
            }

            const labels = data.map(d => new Date(d.timestamp * 1000).toLocaleTimeString());

            metricsChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'CPU %',
                            data: data.map(d => d.cpu_percent),
                            borderColor: 'rgb(255, 99, 132)',
                            tension: 0.1
                        },
                        {
                            label: 'Memory %',
                            data: data.map(d => d.memory_percent),
                            borderColor: 'rgb(54, 162, 235)',
                            tension: 0.1
                        },
                        {
                            label: 'Disk %',
                            data: data.map(d => d.disk_percent),
                            borderColor: 'rgb(255, 205, 86)',
                            tension: 0.1
                        }
                    ]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100
                        }
                    }
                }
            });
        }

        async function loadStatistics() {
            try {
                // Load capture statistics
                const captureResponse = await fetch('/api/statistics/captures');
                const captureResult = await captureResponse.json();
                if (captureResult.status === 'success') {
                    const html = Object.entries(captureResult.data)
                        .map(([key, value]) => `<div class="stat-item">${key}: ${value}</div>`)
                        .join('');
                    document.getElementById('captureStats').innerHTML = html || 'No data available';
                }

                // Load detection statistics
                const detectionResponse = await fetch('/api/statistics/detections');
                const detectionResult = await detectionResponse.json();
                if (detectionResult.status === 'success') {
                    const html = Object.entries(detectionResult.data)
                        .map(([key, value]) => `<div class="stat-item">${key}: ${value}</div>`)
                        .join('');
                    document.getElementById('detectionStats').innerHTML = html || 'No data available';
                }

                // Load error statistics
                const errorResponse = await fetch('/api/statistics/errors');
                const errorResult = await errorResponse.json();
                if (errorResult.status === 'success') {
                    const html = Object.entries(errorResult.data)
                        .map(([key, value]) => `<div class="stat-item">${key}: ${value}</div>`)
                        .join('');
                    document.getElementById('errorStats').innerHTML = html || 'No errors recorded';
                }

                // Load system summary
                const summaryResponse = await fetch('/api/statistics/summary');
                const summaryResult = await summaryResponse.json();
                if (summaryResult.status === 'success') {
                    const system = summaryResult.data.system || {};
                    const html = Object.entries(system)
                        .map(([key, value]) => `<div class="stat-item">${key}: ${typeof value === 'number' ? value.toFixed(2) : value}</div>`)
                        .join('');
                    document.getElementById('systemSummary').innerHTML = html || 'No data available';
                }

            } catch (error) {
                console.error('Failed to load statistics:', error);
            }
        }

        function refreshData() {
            loadRealtimeMetrics();
            loadMetricsHistory();
            loadStatistics();
        }

        function toggleAutoRefresh() {
            autoRefresh = !autoRefresh;
            document.getElementById('autoRefreshStatus').textContent = autoRefresh ? 'ON' : 'OFF';
        }

        // Initial load
        refreshData();

        // Auto refresh every 30 seconds
        setInterval(() => {
            if (autoRefresh) {
                refreshData();
            }
        }, 30000);
    </script>
</body>
</html>'''

            with open(template_file, 'w') as f:
                f.write(html_content)

    def start_server(self):
        """start monitoring dashboard server"""
        if self.server_thread and self.server_thread.is_alive():
            return

        self.create_monitoring_template()

        self.running = True
        port = self.config.get('monitoring', {}).get('port', 8081)
        host = self.config.get('monitoring', {}).get('host', '0.0.0.0')

        def run_server():
            try:
                self.app.run(host=host, port=port, debug=False, use_reloader=False)
            except Exception as e:
                self.logger.error(f"monitoring dashboard server error: {e}")

        self.server_thread = threading.Thread(target=run_server)
        self.server_thread.daemon = True
        self.server_thread.start()

        self.logger.info(f"monitoring dashboard started on http://{host}:{port}")

    def stop_server(self):
        """stop monitoring dashboard server"""
        self.running = False
        self.logger.info("monitoring dashboard stop requested")
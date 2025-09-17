#!/usr/bin/env python3
"""
Web Dashboard for Parking Monitor
Simple Flask web interface showing parking status and recent captures
"""

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, jsonify, send_from_directory


class WebDashboard:
    def __init__(self, config, parking_monitor=None):
        self.config = config
        self.parking_monitor = parking_monitor
        self.logger = logging.getLogger(__name__)
        self.app = Flask(__name__)
        self.setup_routes()
        self.server_thread = None
        self.running = False

    def setup_routes(self):
        """setup flask routes"""

        @self.app.route('/')
        def index():
            return render_template('dashboard.html')

        @self.app.route('/api/status')
        def get_status():
            """get current parking status"""
            try:
                if self.parking_monitor:
                    status = self.parking_monitor.get_status()
                else:
                    # fallback to file-based status
                    status_file = Path(self.config.get('parking_monitor', {}).get('storage_dir', 'parking_captures')) / 'current_status.json'
                    if status_file.exists():
                        with open(status_file, 'r') as f:
                            status = json.load(f)
                    else:
                        status = {}

                return jsonify({
                    'status': 'success',
                    'data': status,
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                self.logger.error(f"error getting status: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/api/images/<area_id>')
        def get_recent_images(area_id):
            """get recent images for area"""
            try:
                storage_dir = Path(self.config.get('parking_monitor', {}).get('storage_dir', 'parking_captures'))
                images = []

                # get recent images for the area
                for image_file in sorted(storage_dir.glob(f'parking_{area_id}_*.jpg'), reverse=True)[:10]:
                    images.append({
                        'filename': image_file.name,
                        'timestamp': datetime.fromtimestamp(image_file.stat().st_mtime).isoformat(),
                        'size': image_file.stat().st_size
                    })

                return jsonify({
                    'status': 'success',
                    'data': images
                })
            except Exception as e:
                self.logger.error(f"error getting images for {area_id}: {e}")
                return jsonify({'status': 'error', 'message': str(e)}), 500

        @self.app.route('/images/<filename>')
        def serve_image(filename):
            """serve parking images"""
            storage_dir = Path(self.config.get('parking_monitor', {}).get('storage_dir', 'parking_captures'))
            return send_from_directory(storage_dir, filename)

        @self.app.route('/api/config')
        def get_config():
            """get current configuration"""
            try:
                return jsonify({
                    'status': 'success',
                    'data': {
                        'areas': self.config.get('parking_monitor', {}).get('areas', []),
                        'peak_hours': self.config.get('parking_monitor', {}).get('peak_hours', []),
                        'peak_interval': self.config.get('parking_monitor', {}).get('peak_interval', 15),
                        'off_peak_interval': self.config.get('parking_monitor', {}).get('off_peak_interval', 60)
                    }
                })
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 500

    def create_template(self):
        """create html template if it doesn't exist"""
        template_dir = Path('templates')
        template_dir.mkdir(exist_ok=True)

        template_file = template_dir / 'dashboard.html'
        if not template_file.exists():
            html_content = '''<!DOCTYPE html>
<html>
<head>
    <title>Parking Monitor Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
        .header { text-align: center; margin-bottom: 30px; }
        .area-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .area-card { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .area-title { font-size: 1.2em; font-weight: bold; margin-bottom: 15px; }
        .status-indicator { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }
        .status-available { background-color: #4CAF50; }
        .status-full { background-color: #f44336; }
        .status-offline { background-color: #9E9E9E; }
        .metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 15px 0; }
        .metric { text-align: center; padding: 10px; background: #f8f9fa; border-radius: 4px; }
        .metric-value { font-size: 1.5em; font-weight: bold; color: #333; }
        .metric-label { font-size: 0.9em; color: #666; }
        .recent-images { margin-top: 20px; }
        .image-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 10px; }
        .image-thumb { width: 100%; height: 80px; object-fit: cover; border-radius: 4px; cursor: pointer; }
        .last-update { font-size: 0.9em; color: #666; margin-top: 10px; }
        .refresh-btn { background: #2196F3; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }
        .refresh-btn:hover { background: #1976D2; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Parking Monitor Dashboard</h1>
        <button class="refresh-btn" onclick="refreshData()">Refresh</button>
    </div>

    <div id="dashboard" class="area-grid">
        <!-- Content will be loaded here -->
    </div>

    <script>
        let config = {};

        async function loadConfig() {
            try {
                const response = await fetch('/api/config');
                const result = await response.json();
                if (result.status === 'success') {
                    config = result.data;
                }
            } catch (error) {
                console.error('Failed to load config:', error);
            }
        }

        async function loadStatus() {
            try {
                const response = await fetch('/api/status');
                const result = await response.json();

                if (result.status === 'success') {
                    renderDashboard(result.data);
                } else {
                    document.getElementById('dashboard').innerHTML =
                        '<div class="area-card"><h3>Error loading status</h3></div>';
                }
            } catch (error) {
                console.error('Failed to load status:', error);
                document.getElementById('dashboard').innerHTML =
                    '<div class="area-card"><h3>Connection error</h3></div>';
            }
        }

        async function loadRecentImages(areaId) {
            try {
                const response = await fetch(`/api/images/${areaId}`);
                const result = await response.json();
                return result.status === 'success' ? result.data : [];
            } catch (error) {
                console.error(`Failed to load images for ${areaId}:`, error);
                return [];
            }
        }

        function renderDashboard(statusData) {
            const dashboard = document.getElementById('dashboard');
            const areas = config.areas || Object.keys(statusData);

            if (areas.length === 0) {
                dashboard.innerHTML = '<div class="area-card"><h3>No parking areas configured</h3></div>';
                return;
            }

            dashboard.innerHTML = '';

            areas.forEach(async (areaId) => {
                const areaData = statusData[areaId] || {};
                const images = await loadRecentImages(areaId);

                const statusClass = areaData.status === 'full' ? 'status-full' :
                                  areaData.status === 'available' ? 'status-available' : 'status-offline';

                const lastUpdate = areaData.last_update ?
                    new Date(areaData.last_update).toLocaleString() : 'Never';

                const imageHtml = images.slice(0, 6).map(img =>
                    `<img src="/images/${img.filename}" class="image-thumb"
                     title="${new Date(img.timestamp).toLocaleString()}"
                     onclick="window.open('/images/${img.filename}', '_blank')">`
                ).join('');

                const cardHtml = `
                    <div class="area-card">
                        <div class="area-title">
                            <span class="status-indicator ${statusClass}"></span>
                            Area ${areaId}
                        </div>

                        <div class="metrics">
                            <div class="metric">
                                <div class="metric-value">${areaData.vehicle_count || 0}</div>
                                <div class="metric-label">Vehicles</div>
                            </div>
                            <div class="metric">
                                <div class="metric-value">${areaData.available_slots || 0}</div>
                                <div class="metric-label">Available</div>
                            </div>
                            <div class="metric">
                                <div class="metric-value">${areaData.total_slots || 0}</div>
                                <div class="metric-label">Total Slots</div>
                            </div>
                            <div class="metric">
                                <div class="metric-value">${((areaData.occupancy_rate || 0) * 100).toFixed(1)}%</div>
                                <div class="metric-label">Occupancy</div>
                            </div>
                        </div>

                        <div class="recent-images">
                            <h4>Recent Captures</h4>
                            <div class="image-grid">
                                ${imageHtml || '<div style="grid-column: 1/-1; text-align: center; color: #666;">No images available</div>'}
                            </div>
                        </div>

                        <div class="last-update">Last updated: ${lastUpdate}</div>
                    </div>
                `;

                dashboard.innerHTML += cardHtml;
            });
        }

        function refreshData() {
            loadStatus();
        }

        // initial load
        loadConfig().then(() => {
            loadStatus();
            // auto refresh every 30 seconds
            setInterval(loadStatus, 30000);
        });
    </script>
</body>
</html>'''

            with open(template_file, 'w') as f:
                f.write(html_content)

    def start_server(self):
        """start web dashboard server"""
        if self.server_thread and self.server_thread.is_alive():
            return

        self.create_template()

        self.running = True
        port = self.config.get('web_dashboard', {}).get('port', 8080)
        host = self.config.get('web_dashboard', {}).get('host', '0.0.0.0')

        def run_server():
            try:
                self.app.run(host=host, port=port, debug=False, use_reloader=False)
            except Exception as e:
                self.logger.error(f"web server error: {e}")

        self.server_thread = threading.Thread(target=run_server)
        self.server_thread.daemon = True
        self.server_thread.start()

        self.logger.info(f"web dashboard started on http://{host}:{port}")

    def stop_server(self):
        """stop web dashboard server"""
        self.running = False
        # note: flask development server doesn't have clean shutdown
        self.logger.info("web dashboard stop requested")
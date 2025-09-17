#!/bin/bash

# Parking Camera Client Deployment Script
# Automatic dependency installation and service setup for Raspberry Pi

set -euo pipefail

# colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # no color

# deployment configuration
INSTALL_DIR="/opt/parking-client"
SERVICE_NAME="parking-camera"
USER="pi"
GROUP="pi"
PYTHON_VERSION="3.9"

# logging
LOG_FILE="/tmp/parking-client-deploy.log"

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}" | tee -a "$LOG_FILE"
    exit 1
}

info() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$LOG_FILE"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "this script must be run as root (use sudo)"
    fi
}

check_platform() {
    if [[ ! -f /proc/device-tree/model ]] || ! grep -q "Raspberry Pi" /proc/device-tree/model; then
        warn "not running on raspberry pi, some features may not work"
    fi
}

update_system() {
    log "updating system packages..."
    apt-get update -y
    apt-get upgrade -y
}

install_system_dependencies() {
    log "installing system dependencies..."

    # essential packages
    apt-get install -y \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        git \
        curl \
        wget \
        build-essential \
        cmake \
        pkg-config \
        libssl-dev \
        libffi-dev \
        libjpeg-dev \
        libpng-dev \
        libopencv-dev \
        python3-opencv \
        libatlas-base-dev \
        libhdf5-dev \
        libhdf5-serial-dev \
        libatlas-base-dev \
        libjasper-dev \
        libqtgui4 \
        libqt4-test

    # raspberry pi specific packages
    if grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
        log "installing raspberry pi specific packages..."
        apt-get install -y \
            raspi-config \
            libraspberrypi-bin \
            libraspberrypi-dev \
            python3-picamera2 \
            python3-rpi.gpio

        # enable camera
        raspi-config nonint do_camera 0
    fi
}

create_user_and_directories() {
    log "creating user and directories..."

    # create user if not exists
    if ! id "$USER" &>/dev/null; then
        useradd -r -s /bin/bash -m "$USER"
        usermod -a -G video,gpio,i2c,spi "$USER"
    fi

    # create install directory
    mkdir -p "$INSTALL_DIR"
    chown -R "$USER:$GROUP" "$INSTALL_DIR"

    # create log directory
    mkdir -p "/var/log/parking-client"
    chown -R "$USER:$GROUP" "/var/log/parking-client"

    # create data directories
    mkdir -p "$INSTALL_DIR"/{captures,parking_captures,exit_captures,cache,backups}
    chown -R "$USER:$GROUP" "$INSTALL_DIR"
}

install_python_dependencies() {
    log "setting up python virtual environment..."

    # create virtual environment
    sudo -u "$USER" python3 -m venv "$INSTALL_DIR/venv"

    # upgrade pip
    sudo -u "$USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip setuptools wheel

    log "installing python dependencies..."

    # install dependencies from requirements.txt
    if [[ -f "requirements.txt" ]]; then
        sudo -u "$USER" "$INSTALL_DIR/venv/bin/pip" install -r requirements.txt
    else
        # install dependencies manually
        sudo -u "$USER" "$INSTALL_DIR/venv/bin/pip" install \
            picamera2 \
            opencv-python \
            numpy \
            scikit-image \
            requests \
            urllib3 \
            flask \
            psutil \
            cryptography \
            RPi.GPIO
    fi
}

copy_application_files() {
    log "copying application files..."

    # copy python files
    for file in *.py; do
        if [[ -f "$file" ]]; then
            cp "$file" "$INSTALL_DIR/"
        fi
    done

    # copy configuration files
    if [[ -f "config.json" ]]; then
        cp "config.json" "$INSTALL_DIR/config.json.example"
        if [[ ! -f "$INSTALL_DIR/config.json" ]]; then
            cp "config.json" "$INSTALL_DIR/"
        fi
    fi

    # copy service file
    if [[ -f "parking-camera.service" ]]; then
        cp "parking-camera.service" "/etc/systemd/system/"
    fi

    # set permissions
    chown -R "$USER:$GROUP" "$INSTALL_DIR"
    chmod +x "$INSTALL_DIR"/*.py
}

setup_log_rotation() {
    log "setting up log rotation..."

    cat > /etc/logrotate.d/parking-client << EOF
/var/log/parking-client/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0644 $USER $GROUP
    postrotate
        /bin/systemctl reload-or-restart $SERVICE_NAME > /dev/null 2>&1 || true
    endscript
}
EOF
}

setup_systemd_service() {
    log "setting up systemd service..."

    # reload systemd
    systemctl daemon-reload

    # enable service
    systemctl enable "$SERVICE_NAME"

    # create override directory for custom configuration
    mkdir -p "/etc/systemd/system/$SERVICE_NAME.service.d"

    info "systemd service installed and enabled"
}

configure_firewall() {
    log "configuring firewall..."

    # install ufw if not present
    if ! command -v ufw &> /dev/null; then
        apt-get install -y ufw
    fi

    # allow ssh
    ufw allow ssh

    # allow web dashboard (if enabled)
    ufw allow 8080/tcp

    # enable firewall
    ufw --force enable
}

setup_monitoring() {
    log "setting up monitoring..."

    # create monitoring script
    cat > "$INSTALL_DIR/health_check.sh" << 'EOF'
#!/bin/bash
# health check script for monitoring

SERVICE_NAME="parking-camera"
LOG_FILE="/var/log/parking-client/health.log"

check_service() {
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "$(date): service is running" >> "$LOG_FILE"
        return 0
    else
        echo "$(date): service is not running" >> "$LOG_FILE"
        return 1
    fi
}

check_disk_space() {
    USAGE=$(df / | awk 'NR==2 {print $5}' | sed 's/%//')
    if [ "$USAGE" -gt 90 ]; then
        echo "$(date): disk usage critical: ${USAGE}%" >> "$LOG_FILE"
        return 1
    fi
    return 0
}

check_memory() {
    USAGE=$(free | awk 'NR==2{printf "%.0f", $3*100/$2}')
    if [ "$USAGE" -gt 90 ]; then
        echo "$(date): memory usage critical: ${USAGE}%" >> "$LOG_FILE"
        return 1
    fi
    return 0
}

# run checks
check_service
check_disk_space
check_memory

# restart service if unhealthy
if ! check_service; then
    echo "$(date): restarting service due to health check failure" >> "$LOG_FILE"
    systemctl restart "$SERVICE_NAME"
fi
EOF

    chmod +x "$INSTALL_DIR/health_check.sh"
    chown "$USER:$GROUP" "$INSTALL_DIR/health_check.sh"

    # add cron job for health check
    echo "*/5 * * * * $INSTALL_DIR/health_check.sh" | crontab -u "$USER" -
}

create_backup_script() {
    log "creating backup script..."

    cat > "$INSTALL_DIR/backup.sh" << 'EOF'
#!/bin/bash
# backup script for parking client

BACKUP_DIR="/opt/parking-client/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/backup_$DATE.tar.gz"

# create backup directory
mkdir -p "$BACKUP_DIR"

# create backup
tar -czf "$BACKUP_FILE" \
    --exclude="$BACKUP_DIR" \
    --exclude="*.log" \
    --exclude="venv" \
    --exclude="__pycache__" \
    /opt/parking-client/

# keep only last 7 backups
find "$BACKUP_DIR" -name "backup_*.tar.gz" -mtime +7 -delete

echo "backup created: $BACKUP_FILE"
EOF

    chmod +x "$INSTALL_DIR/backup.sh"
    chown "$USER:$GROUP" "$INSTALL_DIR/backup.sh"

    # add daily backup cron job
    echo "0 2 * * * $INSTALL_DIR/backup.sh" | crontab -u "$USER" -
}

setup_performance_tuning() {
    log "applying performance tuning..."

    # gpu memory split for camera
    if grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
        echo "gpu_mem=128" >> /boot/config.txt
        echo "camera_auto_detect=1" >> /boot/config.txt
        echo "dtoverlay=vc4-fkms-v3d" >> /boot/config.txt
    fi

    # disable swap for better performance
    dphys-swapfile swapoff || true
    dphys-swapfile uninstall || true
    systemctl disable dphys-swapfile || true

    # optimize networking
    echo "net.core.rmem_max = 16777216" >> /etc/sysctl.conf
    echo "net.core.wmem_max = 16777216" >> /etc/sysctl.conf
}

generate_certificates() {
    log "generating self-signed certificates for development..."

    CERT_DIR="$INSTALL_DIR/certs"
    mkdir -p "$CERT_DIR"

    # generate private key
    openssl genrsa -out "$CERT_DIR/client.key" 2048

    # generate certificate
    openssl req -new -x509 -key "$CERT_DIR/client.key" -out "$CERT_DIR/client.crt" -days 365 -subj "/C=US/ST=State/L=City/O=Organization/CN=parking-client"

    chown -R "$USER:$GROUP" "$CERT_DIR"
    chmod 600 "$CERT_DIR/client.key"
    chmod 644 "$CERT_DIR/client.crt"
}

post_install_configuration() {
    log "performing post-installation configuration..."

    # create version file
    echo "1.0.0" > "$INSTALL_DIR/VERSION"

    # create default api key if not exists
    if [[ ! -f "$INSTALL_DIR/api.key" ]]; then
        openssl rand -hex 32 > "$INSTALL_DIR/api.key"
        chown "$USER:$GROUP" "$INSTALL_DIR/api.key"
        chmod 600 "$INSTALL_DIR/api.key"
    fi

    # update config with installation paths
    if [[ -f "$INSTALL_DIR/config.json" ]]; then
        python3 -c "
import json
with open('$INSTALL_DIR/config.json', 'r') as f:
    config = json.load(f)
config['logging']['file'] = '/var/log/parking-client/camera_client.log'
config['security'] = {
    'api_key_file': '$INSTALL_DIR/api.key',
    'ssl_cert_file': '$INSTALL_DIR/certs/client.crt',
    'use_https': True,
    'ssl_verify': False
}
with open('$INSTALL_DIR/config.json', 'w') as f:
    json.dump(config, f, indent=2)
"
    fi
}

main() {
    log "starting parking camera client deployment..."

    check_root
    check_platform

    update_system
    install_system_dependencies
    create_user_and_directories
    install_python_dependencies
    copy_application_files
    setup_log_rotation
    setup_systemd_service
    configure_firewall
    setup_monitoring
    create_backup_script
    setup_performance_tuning
    generate_certificates
    post_install_configuration

    log "deployment completed successfully!"
    info "to start the service, run: systemctl start $SERVICE_NAME"
    info "to view logs, run: journalctl -u $SERVICE_NAME -f"
    info "to view web dashboard, open: http://$(hostname -I | awk '{print $1}'):8080"

    warn "please reboot the system to apply all changes"
}

# run main function
main "$@"
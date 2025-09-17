# Raspberry Pi Setup Guide - Parking Client

## Masalah yang Diperbaiki

1. **Error: externally-managed-environment** - Python modern tidak mengizinkan pip install di luar virtual environment
2. **Error: libcap development headers missing** - Header development diperlukan untuk build wheel
3. **Error: ModuleNotFoundError for 'requests'** - Module tidak ditemukan setelah instalasi

## Solusi 1: Virtual Environment (Direkomendasikan)

Script `run.sh` telah diperbaiki dengan fitur:

- Instalasi otomatis system dependencies (`libcap-dev`, `pkg-config`)
- Virtual environment dengan `--system-site-packages`
- Flag `--break-system-packages` untuk kompatibilitas
- Verifikasi import sebelum menjalankan

### Cara Menjalankan:

```bash
chmod +x run.sh
./run.sh
```

## Solusi 2: System Packages (Alternatif)

### Setup Awal:

```bash
chmod +x setup_system_packages.sh
./setup_system_packages.sh
```

### Menjalankan:

```bash
chmod +x run_system_packages.sh
./run_system_packages.sh
```

### Manual System Packages Install:

```bash
sudo apt update
sudo apt install -y \
    python3 \
    python3-pip \
    python3-opencv \
    python3-numpy \
    python3-requests \
    python3-picamera2 \
    libcap-dev \
    pkg-config
```

## Testing Setup

Verifikasi instalasi dengan:

```bash
python3 -c "
import requests
import cv2
import numpy
from picamera2 import Picamera2
print('Semua module berhasil diimport!')
"
```

## Troubleshooting

### Jika masih ada error "externally-managed-environment":

```bash
# Hapus file pembatas
sudo rm /usr/lib/python*/EXTERNALLY-MANAGED

# Atau gunakan pipx
sudo apt install pipx
pipx install <package-name>
```

### Jika picamera2 tidak ditemukan:

```bash
# Install dari repository resmi
sudo apt install python3-picamera2

# Atau compile dari source
git clone https://github.com/raspberrypi/picamera2.git
cd picamera2
pip install .
```

### Jika opencv error (libGL.so.1):

```bash
# Install OpenGL dan multimedia dependencies
sudo apt install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgtk-3-dev \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libcanberra-gtk-module \
    libcanberra-gtk3-module
```

## File yang Dimodifikasi

1. **run.sh** - Script utama dengan perbaikan venv
2. **setup_system_packages.sh** - Setup menggunakan system packages
3. **run_system_packages.sh** - Menjalankan dengan system packages

## Rekomendasi

- **Gunakan Solusi 1** (Virtual Environment) jika ingin isolasi dependencies
- **Gunakan Solusi 2** (System Packages) jika ingin setup lebih sederhana
- Pastikan Raspberry Pi OS up-to-date: `sudo apt update && sudo apt upgrade`
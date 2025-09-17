# Parking Camera Client for Pi

Simple camera client that sends detection results to API endpoints.

## Quick Setup

### 1. Edit config.json
```json
{
  "server_url": "http://192.168.1.100:5000",
  "camera_id": "entrance",
  "camera_type": "auto"
}
```

- `server_url`: Your API server address
- `camera_id`: "entrance" or "exit"
- `camera_type`: "auto", "pi", or "usb"

### 2. Run
```bash
chmod +x run.sh
./run.sh
```

## API Endpoints Used

### Client sends to:
- `POST /api/detection/result` - Detection results
- `POST /api/camera/status` - Camera status

### Client checks:
- `GET /api/camera/trigger-entrance` - Entrance trigger
- `GET /api/camera/trigger-exit` - Exit trigger

## Detection Result Format
```json
{
  "camera_id": "entrance",
  "detected_plate": "ABC123",
  "confidence": 0.85,
  "image_data": "base64_image...",
  "timestamp": "2025-01-15T10:30:00"
}
```

## How it works
1. Client polls server for triggers
2. When triggered, captures image
3. Detects plate (mock implementation)
4. Sends result to `/api/detection/result`
5. Server responds with grant/deny action

## Stop
Press `Ctrl+C`
# Parking Client Configuration Guide

## Quick Setup

### Single Configuration File (Recommended)
Use `config-unified.json` and simply change the `camera_id` field for different cameras:

- **Entrance Camera**: Set `"camera_id": "entrance"`
- **Exit Camera**: Set `"camera_id": "exit"`
- **Parking Area Monitor**: Set `"camera_id": "area"`

### Usage Examples

#### 1. For Entrance Camera
```bash
python integrated_camera_client.py --config config-unified.json
```
Make sure `camera_id` is set to `"entrance"` in the config file.

#### 2. For Exit Camera
Change `camera_id` to `"exit"` in `config-unified.json`, then run:
```bash
python integrated_camera_client.py --config config-unified.json
```

#### 3. For Parking Area Monitor
Change `camera_id` to `"area"` in `config-unified.json`, then run:
```bash
python integrated_camera_client.py --config config-unified.json
```

## Configuration Options

### server_url
- Set to your parking-module server URL
- Default: `"http://localhost:5000"`
- For Pi deployment: Use the actual server IP, e.g., `"http://192.168.1.100:5000"`

### camera_id Options
- `"entrance"` - For vehicle entry detection
- `"exit"` - For vehicle exit detection
- `"area"` - For parking area monitoring

### camera_type
- `"auto"` - Automatically detect Pi camera or USB camera
- `"pi"` - Force Pi camera usage
- `"usb"` - Force USB camera usage

## Pre-configured Files (Alternative)

If you prefer separate config files:

- `config-entrance.json` - Pre-configured for entrance camera
- `config-exit.json` - Pre-configured for exit camera
- `config-parking.json` - Pre-configured for parking area monitoring

Use them like:
```bash
python integrated_camera_client.py --config config-entrance.json
```

## Integration Fixed Issues

✅ **HTTP 405 Error**: Fixed trigger endpoints to support both GET and POST
✅ **HTTP 404 Error**: Fixed latest-capture endpoint with proper camera_id parameter
✅ **Multiple Configs**: Created unified config with simple camera_id switching

## Testing the Integration

1. Start parking-module server:
```bash
cd parking-module
python app.py
```

2. Start parking-client (entrance camera):
```bash
cd parking-client
python integrated_camera_client.py --config config-unified.json
```

3. Check the server logs - you should see successful connections and status updates.
#!/usr/bin/env python3
"""
Lightweight MJPEG Video Streaming Server for NVIDIA Jetson
Streams video from a USB webcam (like Logitech BRIO) over HTTP.

Usage:
    python3 camera_stream.py [--port PORT] [--camera CAMERA_INDEX] [--width WIDTH] [--height HEIGHT]

Access the stream at:
    - http://<jetson-ip>:8080/ (web interface)
    - http://<jetson-ip>:8080/video_feed (raw MJPEG stream)
"""

import argparse
import glob
import os
import socket
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import cv2

# Global variables for frame sharing between threads
output_frame = None
lock = threading.Lock()
camera = None


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    allow_reuse_address = True
    daemon_threads = True


class StreamHandler(BaseHTTPRequestHandler):
    """HTTP request handler for video streaming."""

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(self.get_html_page().encode())
        elif self.path == '/video_feed':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            self.stream_video()
        elif self.path == '/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            status = self.get_status()
            self.wfile.write(status.encode())
        else:
            self.send_error(404)

    def stream_video(self):
        """Stream MJPEG video to the client."""
        global output_frame, lock
        while True:
            with lock:
                if output_frame is None:
                    time.sleep(0.01)
                    continue
                frame = output_frame.copy()

            # Encode frame as JPEG
            ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ret:
                continue

            try:
                self.wfile.write(b'--frame\r\n')
                self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                self.wfile.write(jpeg.tobytes())
                self.wfile.write(b'\r\n')
            except (BrokenPipeError, ConnectionResetError):
                break

    def get_status(self):
        """Return camera status as JSON."""
        global camera
        if camera is not None and camera.isOpened():
            width = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = camera.get(cv2.CAP_PROP_FPS)
            return f'{{"status": "running", "width": {width}, "height": {height}, "fps": {fps}}}'
        return '{"status": "no camera"}'

    def get_html_page(self):
        """Return the HTML page for the web interface."""
        return '''<!DOCTYPE html>
<html>
<head>
    <title>Jetson Camera Stream</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
        }
        h1 {
            margin-bottom: 20px;
            font-weight: 300;
            color: #76b900;
        }
        .container {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            max-width: 100%;
        }
        .video-container {
            position: relative;
            background: #000;
            border-radius: 8px;
            overflow: hidden;
        }
        #stream {
            max-width: 100%;
            height: auto;
            display: block;
        }
        .status {
            margin-top: 15px;
            padding: 10px 15px;
            background: #0f3460;
            border-radius: 6px;
            font-size: 14px;
        }
        .status-dot {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 8px;
            background: #76b900;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .info {
            margin-top: 15px;
            font-size: 12px;
            color: #888;
        }
    </style>
</head>
<body>
    <h1>NVIDIA Jetson Camera Stream</h1>
    <div class="container">
        <div class="video-container">
            <img id="stream" src="/video_feed" alt="Camera Stream">
        </div>
        <div class="status">
            <span class="status-dot"></span>
            <span id="status-text">Streaming...</span>
        </div>
        <div class="info" id="info"></div>
    </div>
    <script>
        fetch('/status')
            .then(r => r.json())
            .then(data => {
                if (data.status === 'running') {
                    document.getElementById('info').textContent =
                        `Resolution: ${data.width}x${data.height} @ ${data.fps.toFixed(1)} FPS`;
                }
            })
            .catch(() => {});

        // Reconnect on error
        document.getElementById('stream').onerror = function() {
            setTimeout(() => { this.src = '/video_feed?' + Date.now(); }, 1000);
        };
    </script>
</body>
</html>'''


def get_video_device_info(device_path):
    """Get information about a video device using v4l2-ctl."""
    try:
        result = subprocess.run(
            ['v4l2-ctl', '-d', device_path, '--all'],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout
    except Exception:
        return ""


def find_capture_device():
    """
    Find the correct video capture device.
    Logitech BRIO and similar cameras create multiple /dev/video* devices.
    We need to find the one that actually captures video frames.
    """
    video_devices = sorted(glob.glob('/dev/video*'))

    print("Scanning video devices...")

    for device in video_devices:
        device_num = int(device.replace('/dev/video', ''))
        print(f"  Testing {device}...", end=" ", flush=True)

        # Try to open with V4L2 backend explicitly
        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)

        if not cap.isOpened():
            print("cannot open")
            continue

        # Set to a known working format - MJPEG is well supported by USB cameras
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        # Try to read a frame
        ret, frame = cap.read()
        cap.release()

        if ret and frame is not None and frame.size > 0:
            print(f"OK! (frame: {frame.shape[1]}x{frame.shape[0]})")
            return device
        else:
            print("no frames")

    return None


def open_camera(device, width, height, fps):
    """Open camera with proper settings for Jetson + USB camera."""
    print(f"\nOpening camera: {device}")

    # Use V4L2 backend explicitly (not GStreamer)
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)

    if not cap.isOpened():
        print(f"Error: Could not open {device}")
        return None

    # Set MJPEG format - much better for USB bandwidth
    fourcc = cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')
    cap.set(cv2.CAP_PROP_FOURCC, fourcc)

    # Set resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    # Set FPS
    if fps > 0:
        cap.set(cv2.CAP_PROP_FPS, fps)

    # Set buffer size to 1 for low latency
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Verify settings
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join([chr((actual_fourcc >> 8 * i) & 0xFF) for i in range(4)])

    print(f"Camera settings: {actual_width}x{actual_height} @ {actual_fps:.1f} FPS, format: {fourcc_str}")

    # Test read
    ret, frame = cap.read()
    if not ret or frame is None:
        print("Error: Camera opened but cannot read frames")
        cap.release()
        return None

    print(f"Test frame captured: {frame.shape[1]}x{frame.shape[0]}")
    return cap


def capture_frames(device, width, height, fps):
    """Capture frames from the camera in a background thread."""
    global output_frame, lock, camera

    camera = open_camera(device, width, height, fps)

    if camera is None:
        print("\nFailed to open camera!")
        print("\nTroubleshooting tips:")
        print("1. Check if camera is connected: lsusb | grep -i logitech")
        print("2. Check if video device exists: ls -la /dev/video*")
        print("3. Load camera module: sudo modprobe uvcvideo")
        print("4. Check permissions: ls -la /dev/video0")
        print("5. Try a different device: python3 camera_stream.py --device /dev/video2")
        return

    print("\nCamera ready! Starting capture loop...")

    consecutive_failures = 0
    while True:
        ret, frame = camera.read()

        if not ret or frame is None:
            consecutive_failures += 1
            if consecutive_failures > 30:
                print("Too many consecutive frame failures, trying to reopen camera...")
                camera.release()
                time.sleep(1)
                camera = open_camera(device, width, height, fps)
                if camera is None:
                    print("Failed to reopen camera")
                    return
                consecutive_failures = 0
            time.sleep(0.01)
            continue

        consecutive_failures = 0

        with lock:
            output_frame = frame


def get_local_ip():
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def main():
    parser = argparse.ArgumentParser(description='Lightweight MJPEG Video Streaming Server')
    parser.add_argument('--port', type=int, default=8080, help='Server port (default: 8080)')
    parser.add_argument('--device', type=str, default=None, help='Video device path (e.g., /dev/video0). Auto-detected if not specified.')
    parser.add_argument('--camera', type=int, default=None, help='Camera index (deprecated, use --device)')
    parser.add_argument('--width', type=int, default=1280, help='Frame width (default: 1280)')
    parser.add_argument('--height', type=int, default=720, help='Frame height (default: 720)')
    parser.add_argument('--fps', type=int, default=30, help='Target FPS (default: 30)')
    args = parser.parse_args()

    # Determine device
    if args.device:
        device = args.device
    elif args.camera is not None:
        device = f'/dev/video{args.camera}'
    else:
        # Auto-detect
        device = find_capture_device()
        if device is None:
            print("\nError: Could not find a working video capture device!")
            print("\nMake sure:")
            print("1. Camera is connected (lsusb | grep -i logitech)")
            print("2. Module is loaded (sudo modprobe uvcvideo)")
            print("3. Devices exist (ls -la /dev/video*)")
            return
        print(f"\nAuto-detected capture device: {device}")

    # Start frame capture thread
    capture_thread = threading.Thread(
        target=capture_frames,
        args=(device, args.width, args.height, args.fps),
        daemon=True
    )
    capture_thread.start()

    # Wait for camera to initialize
    time.sleep(3)

    # Check if we got any frames
    with lock:
        if output_frame is None:
            print("\nWarning: No frames captured yet. Check camera output above.")

    # Get local IP for display
    local_ip = get_local_ip()

    # Start HTTP server
    server = ThreadedHTTPServer(('0.0.0.0', args.port), StreamHandler)

    print("\n" + "="*50)
    print("  Jetson Camera Streaming Server")
    print("="*50)
    print(f"\n  Web Interface:")
    print(f"    http://{local_ip}:{args.port}/")
    print(f"\n  Direct Video Feed:")
    print(f"    http://{local_ip}:{args.port}/video_feed")
    print(f"\n  Status API:")
    print(f"    http://{local_ip}:{args.port}/status")
    print("\n  Press Ctrl+C to stop")
    print("="*50 + "\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        if camera is not None:
            camera.release()
        server.shutdown()


if __name__ == '__main__':
    main()

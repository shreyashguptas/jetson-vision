#!/usr/bin/env python3
"""
Lightweight MJPEG Video Streaming Server for NVIDIA Jetson
Streams video from a USB webcam (like Logitech BRIO) over HTTP.
Includes AI vision analysis using Ollama's qwen3-vl model.

Usage:
    python3 camera_stream.py [--port PORT] [--device DEVICE] [--width WIDTH] [--height HEIGHT]

Access the stream at:
    - http://<jetson-ip>:8080/ (web interface with AI analysis)
    - http://<jetson-ip>:8080/video_feed (raw MJPEG stream)
    - http://<jetson-ip>:8080/analysis (AI analysis JSON)
"""

import argparse
import base64
import glob
import json
import os
import re
import socket
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import cv2

# Try to import requests, provide helpful error if missing
try:
    import requests
except ImportError:
    print("Error: 'requests' module not found.")
    print("Install it with: pip3 install requests")
    exit(1)

# AI Analysis Configuration
AI_CONFIG = {
    'model': 'qwen3-vl:2b',
    'ollama_url': 'http://localhost:11434/api/generate',
    'analysis_interval': 5.0,  # seconds between analyses
    'timeout': 60.0,  # request timeout (vision models can be slow)
    'prompt': 'Describe what you see in this image concisely. List the main objects and any notable activity.',
    'jpeg_quality': 70,  # Lower quality for faster encoding
    'enabled_by_default': True,
}

# Global variables for frame sharing between threads
output_frame = None
lock = threading.Lock()
camera = None

# AI Analysis state
analysis_result = {
    'description': 'Waiting for first analysis...',
    'timestamp': None,
    'processing_time': None,
    'error': None,
    'frame_count': 0
}
analysis_lock = threading.Lock()
ai_enabled = True


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
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            status = self.get_status()
            self.wfile.write(status.encode())
        elif self.path == '/analysis':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(self.get_analysis().encode())
        elif self.path == '/toggle_ai':
            self.handle_toggle_ai()
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
            return json.dumps({
                'status': 'running',
                'width': width,
                'height': height,
                'fps': fps
            })
        return json.dumps({'status': 'no camera'})

    def get_analysis(self):
        """Return AI analysis results as JSON."""
        global analysis_result, analysis_lock, ai_enabled
        with analysis_lock:
            return json.dumps({
                'enabled': ai_enabled,
                'description': analysis_result['description'],
                'timestamp': analysis_result['timestamp'],
                'processing_time': analysis_result['processing_time'],
                'error': analysis_result['error'],
                'frame_count': analysis_result['frame_count'],
                'model': AI_CONFIG['model']
            })

    def handle_toggle_ai(self):
        """Toggle AI analysis on/off."""
        global ai_enabled
        ai_enabled = not ai_enabled
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'ai_enabled': ai_enabled}).encode())
        print(f"[AI] Analysis {'enabled' if ai_enabled else 'disabled'}")

    def get_html_page(self):
        """Return the HTML page for the web interface."""
        return '''<!DOCTYPE html>
<html>
<head>
    <title>Jetson Vision Stream</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }
        h1 {
            text-align: center;
            margin-bottom: 20px;
            font-weight: 300;
            color: #76b900;
        }
        .main-content {
            display: flex;
            flex-direction: row;
            gap: 20px;
            justify-content: center;
            flex-wrap: wrap;
            max-width: 1400px;
            margin: 0 auto;
        }
        .video-panel {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            flex: 1;
            min-width: 300px;
            max-width: 900px;
        }
        .video-container {
            position: relative;
            background: #000;
            border-radius: 8px;
            overflow: hidden;
        }
        #stream {
            width: 100%;
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
            margin-top: 10px;
            font-size: 12px;
            color: #888;
        }

        /* AI Panel Styles */
        .ai-panel {
            background: #16213e;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            width: 380px;
            min-width: 300px;
        }
        .ai-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .ai-title {
            color: #76b900;
            font-size: 18px;
            font-weight: 500;
        }
        .ai-toggle {
            background: #0f3460;
            border: 2px solid #76b900;
            color: #76b900;
            padding: 8px 16px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.3s;
        }
        .ai-toggle:hover {
            background: #76b900;
            color: #1a1a2e;
        }
        .ai-toggle.disabled {
            border-color: #ff6b6b;
            color: #ff6b6b;
        }
        .ai-toggle.disabled:hover {
            background: #ff6b6b;
            color: #1a1a2e;
        }
        .ai-status {
            display: flex;
            align-items: center;
            margin-bottom: 15px;
            padding: 10px;
            background: #0f3460;
            border-radius: 6px;
            font-size: 13px;
        }
        .ai-status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 10px;
            background: #76b900;
        }
        .ai-status-dot.processing {
            animation: pulse 0.5s infinite;
            background: #ffc107;
        }
        .ai-status-dot.error {
            background: #ff6b6b;
        }
        .ai-status-dot.disabled {
            background: #666;
        }
        .ai-description {
            background: #0f3460;
            border-radius: 8px;
            padding: 15px;
            min-height: 200px;
            max-height: 400px;
            overflow-y: auto;
            line-height: 1.6;
            font-size: 14px;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        .ai-description.waiting {
            color: #888;
            font-style: italic;
        }
        .ai-error {
            color: #ff6b6b;
            background: rgba(255, 107, 107, 0.1);
            padding: 12px;
            border-radius: 6px;
            margin-top: 12px;
            font-size: 13px;
            border-left: 3px solid #ff6b6b;
        }
        .ai-meta {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #0f3460;
            font-size: 12px;
            color: #666;
        }
        .ai-meta-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 5px;
        }
        .ai-meta-label {
            color: #888;
        }
        .ai-meta-value {
            color: #aaa;
        }
    </style>
</head>
<body>
    <h1>NVIDIA Jetson Vision Stream</h1>
    <div class="main-content">
        <div class="video-panel">
            <div class="video-container">
                <img id="stream" src="/video_feed" alt="Camera Stream">
            </div>
            <div class="status">
                <span class="status-dot"></span>
                <span id="status-text">Streaming...</span>
            </div>
            <div class="info" id="info"></div>
        </div>

        <div class="ai-panel">
            <div class="ai-header">
                <span class="ai-title">AI Vision Analysis</span>
                <button id="ai-toggle" class="ai-toggle" onclick="toggleAI()">Enabled</button>
            </div>
            <div class="ai-status">
                <span id="ai-status-dot" class="ai-status-dot"></span>
                <span id="ai-status-text">Initializing...</span>
            </div>
            <div id="ai-description" class="ai-description waiting">
                Waiting for first analysis...
            </div>
            <div id="ai-error" class="ai-error" style="display:none;"></div>
            <div class="ai-meta">
                <div class="ai-meta-row">
                    <span class="ai-meta-label">Model:</span>
                    <span id="ai-model" class="ai-meta-value">qwen3-vl:2b</span>
                </div>
                <div class="ai-meta-row">
                    <span class="ai-meta-label">Analysis:</span>
                    <span id="ai-count" class="ai-meta-value">#0</span>
                </div>
                <div class="ai-meta-row">
                    <span class="ai-meta-label">Processing:</span>
                    <span id="ai-time" class="ai-meta-value">--</span>
                </div>
                <div class="ai-meta-row">
                    <span class="ai-meta-label">Last Update:</span>
                    <span id="ai-timestamp" class="ai-meta-value">--</span>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Fetch camera status
        fetch('/status')
            .then(r => r.json())
            .then(data => {
                if (data.status === 'running') {
                    document.getElementById('info').textContent =
                        `Resolution: ${data.width}x${data.height} @ ${data.fps.toFixed(1)} FPS`;
                }
            })
            .catch(() => {});

        // Reconnect stream on error
        document.getElementById('stream').onerror = function() {
            setTimeout(() => { this.src = '/video_feed?' + Date.now(); }, 1000);
        };

        // Poll AI analysis results
        let lastFrameCount = 0;

        function updateAnalysis() {
            fetch('/analysis')
                .then(r => r.json())
                .then(data => {
                    const descEl = document.getElementById('ai-description');
                    const errorEl = document.getElementById('ai-error');
                    const toggleBtn = document.getElementById('ai-toggle');
                    const statusDot = document.getElementById('ai-status-dot');
                    const statusText = document.getElementById('ai-status-text');

                    // Update model name
                    document.getElementById('ai-model').textContent = data.model || 'qwen3-vl:2b';

                    // Update toggle button
                    if (data.enabled) {
                        toggleBtn.textContent = 'Enabled';
                        toggleBtn.classList.remove('disabled');
                    } else {
                        toggleBtn.textContent = 'Disabled';
                        toggleBtn.classList.add('disabled');
                    }

                    // Update status indicator
                    statusDot.classList.remove('processing', 'error', 'disabled');
                    if (!data.enabled) {
                        statusDot.classList.add('disabled');
                        statusText.textContent = 'Analysis disabled';
                    } else if (data.error) {
                        statusDot.classList.add('error');
                        statusText.textContent = 'Error occurred';
                    } else if (data.frame_count > lastFrameCount) {
                        statusText.textContent = 'Analysis complete';
                        lastFrameCount = data.frame_count;
                    } else if (data.frame_count === 0) {
                        statusDot.classList.add('processing');
                        statusText.textContent = 'Waiting for first analysis...';
                    } else {
                        statusDot.classList.add('processing');
                        statusText.textContent = 'Processing next frame...';
                    }

                    // Update description
                    if (data.description) {
                        descEl.textContent = data.description;
                        descEl.classList.remove('waiting');
                    }

                    // Update error display
                    if (data.error) {
                        errorEl.textContent = data.error;
                        errorEl.style.display = 'block';
                    } else {
                        errorEl.style.display = 'none';
                    }

                    // Update metadata
                    document.getElementById('ai-count').textContent = '#' + data.frame_count;
                    if (data.processing_time) {
                        document.getElementById('ai-time').textContent = data.processing_time + 's';
                    }
                    if (data.timestamp) {
                        document.getElementById('ai-timestamp').textContent = data.timestamp;
                    }
                })
                .catch(() => {});
        }

        function toggleAI() {
            fetch('/toggle_ai')
                .then(() => updateAnalysis())
                .catch(() => {});
        }

        // Poll every 2 seconds
        setInterval(updateAnalysis, 2000);
        updateAnalysis();
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


def ai_analysis_loop():
    """Run continuous AI analysis on captured frames."""
    global output_frame, lock, analysis_result, analysis_lock, ai_enabled

    frame_count = 0
    consecutive_errors = 0

    print("[AI] Analysis thread started")

    # Wait for camera to be ready
    while True:
        with lock:
            if output_frame is not None:
                break
        time.sleep(0.5)

    print("[AI] Camera ready, starting analysis loop")
    print(f"[AI] Model: {AI_CONFIG['model']}")
    print(f"[AI] Interval: {AI_CONFIG['analysis_interval']}s")

    while True:
        # Check if AI is enabled
        if not ai_enabled:
            time.sleep(1.0)
            continue

        start_time = time.time()

        try:
            # Copy current frame (thread-safe)
            with lock:
                if output_frame is None:
                    time.sleep(0.5)
                    continue
                frame = output_frame.copy()

            # Resize frame for faster processing (optional optimization)
            # Smaller images = faster base64 encoding and API transfer
            h, w = frame.shape[:2]
            if w > 1280:
                scale = 1280 / w
                frame = cv2.resize(frame, (1280, int(h * scale)))

            # Encode frame to JPEG, then base64
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, AI_CONFIG['jpeg_quality']]
            ret, buffer = cv2.imencode('.jpg', frame, encode_params)
            if not ret:
                raise Exception("Failed to encode frame")

            img_base64 = base64.b64encode(buffer).decode('utf-8')

            # Call Ollama API
            response = requests.post(
                AI_CONFIG['ollama_url'],
                json={
                    'model': AI_CONFIG['model'],
                    'prompt': AI_CONFIG['prompt'],
                    'images': [img_base64],
                    'stream': False
                },
                timeout=AI_CONFIG['timeout']
            )

            if response.status_code != 200:
                raise Exception(f"Ollama API error: {response.status_code} - {response.text[:100]}")

            result_data = response.json()
            result_text = result_data.get('response', 'No response from model')

            # Clean up the response (remove thinking tokens if present)
            # qwen3-vl may include <think>...</think> blocks
            result_text = re.sub(r'<think>.*?</think>', '', result_text, flags=re.DOTALL).strip()

            # Remove any leading/trailing whitespace and normalize newlines
            result_text = '\n'.join(line.strip() for line in result_text.split('\n') if line.strip())

            processing_time = time.time() - start_time
            frame_count += 1
            consecutive_errors = 0

            # Update result (thread-safe)
            with analysis_lock:
                analysis_result['description'] = result_text
                analysis_result['timestamp'] = time.strftime('%H:%M:%S')
                analysis_result['processing_time'] = round(processing_time, 2)
                analysis_result['error'] = None
                analysis_result['frame_count'] = frame_count

            print(f"[AI] Analysis #{frame_count} completed in {processing_time:.2f}s")

        except requests.exceptions.Timeout:
            consecutive_errors += 1
            with analysis_lock:
                analysis_result['error'] = 'Analysis timeout - model may be overloaded'
            print(f"[AI] Timeout (consecutive errors: {consecutive_errors})")

        except requests.exceptions.ConnectionError:
            consecutive_errors += 1
            with analysis_lock:
                analysis_result['error'] = 'Cannot connect to Ollama - is it running? (ollama serve)'
            print(f"[AI] Connection error - is Ollama running? (consecutive errors: {consecutive_errors})")

        except Exception as e:
            consecutive_errors += 1
            error_msg = str(e)[:150]
            with analysis_lock:
                analysis_result['error'] = f'Analysis error: {error_msg}'
            print(f"[AI] Error: {e}")

        # Adaptive backoff on errors
        if consecutive_errors > 0:
            backoff = min(AI_CONFIG['analysis_interval'] * consecutive_errors, 30.0)
            time.sleep(backoff)
        else:
            # Wait for the configured interval
            elapsed = time.time() - start_time
            sleep_time = max(0.1, AI_CONFIG['analysis_interval'] - elapsed)
            time.sleep(sleep_time)


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
    global ai_enabled

    parser = argparse.ArgumentParser(description='Jetson Vision Streaming Server with AI Analysis')
    parser.add_argument('--port', type=int, default=8080, help='Server port (default: 8080)')
    parser.add_argument('--device', type=str, default=None, help='Video device path (e.g., /dev/video0)')
    parser.add_argument('--camera', type=int, default=None, help='Camera index (deprecated, use --device)')
    parser.add_argument('--width', type=int, default=1280, help='Frame width (default: 1280)')
    parser.add_argument('--height', type=int, default=720, help='Frame height (default: 720)')
    parser.add_argument('--fps', type=int, default=30, help='Target FPS (default: 30)')

    # AI-specific arguments
    parser.add_argument('--ai-interval', type=float, default=5.0,
                        help='Seconds between AI analyses (default: 5.0)')
    parser.add_argument('--ai-prompt', type=str, default=None,
                        help='Custom prompt for AI analysis')
    parser.add_argument('--ai-model', type=str, default='qwen3-vl:2b',
                        help='Ollama vision model to use (default: qwen3-vl:2b)')
    parser.add_argument('--no-ai', action='store_true',
                        help='Disable AI analysis')
    parser.add_argument('--ollama-url', type=str, default='http://localhost:11434/api/generate',
                        help='Ollama API URL')

    args = parser.parse_args()

    # Apply AI configuration from arguments
    AI_CONFIG['analysis_interval'] = args.ai_interval
    AI_CONFIG['model'] = args.ai_model
    AI_CONFIG['ollama_url'] = args.ollama_url
    if args.ai_prompt:
        AI_CONFIG['prompt'] = args.ai_prompt
    ai_enabled = not args.no_ai

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

    # Start AI analysis thread (if enabled)
    if ai_enabled:
        ai_thread = threading.Thread(
            target=ai_analysis_loop,
            daemon=True
        )
        ai_thread.start()

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

    print("\n" + "="*55)
    print("  Jetson Vision Streaming Server")
    print("="*55)
    print(f"\n  Web Interface (with AI):")
    print(f"    http://{local_ip}:{args.port}/")
    print(f"\n  Direct Video Feed:")
    print(f"    http://{local_ip}:{args.port}/video_feed")
    print(f"\n  AI Analysis API:")
    print(f"    http://{local_ip}:{args.port}/analysis")
    print(f"\n  AI Status: {'Enabled' if ai_enabled else 'Disabled'}")
    if ai_enabled:
        print(f"  AI Model: {AI_CONFIG['model']}")
        print(f"  Analysis Interval: {AI_CONFIG['analysis_interval']}s")
    print("\n  Press Ctrl+C to stop")
    print("="*55 + "\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        if camera is not None:
            camera.release()
        server.shutdown()


if __name__ == '__main__':
    main()

#!/bin/bash
# Setup script for the Logitech camera on NVIDIA Jetson
# This script must be run with sudo

set -e

echo "====================================="
echo "  Jetson Camera Setup"
echo "====================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run this script with sudo:"
    echo "  sudo ./setup_camera.sh"
    exit 1
fi

# Load the UVC video module
echo "[1/4] Loading uvcvideo kernel module..."
modprobe uvcvideo
echo "      Done."

# Wait for device to be recognized
echo "[2/4] Waiting for camera device..."
sleep 2

# Check if video device was created
if ls /dev/video* &>/dev/null; then
    echo "      Camera device found:"
    ls -la /dev/video*
else
    echo "      Warning: No video device created."
    echo "      Trying to reload the module..."
    modprobe -r uvcvideo 2>/dev/null || true
    sleep 1
    modprobe uvcvideo
    sleep 2

    if ls /dev/video* &>/dev/null; then
        echo "      Camera device found after reload:"
        ls -la /dev/video*
    else
        echo ""
        echo "      ERROR: Camera device still not found!"
        echo ""
        echo "      Please check:"
        echo "        1. Camera is properly connected (lsusb)"
        echo "        2. USB port is working"
        echo "        3. Kernel logs (dmesg | tail -30)"
        exit 1
    fi
fi

# Set permissions for video devices
echo "[3/4] Setting permissions..."
chmod 666 /dev/video*
echo "      Permissions set."

# Add current user to video group (for future sessions)
SUDO_USER_NAME="${SUDO_USER:-$USER}"
if [ -n "$SUDO_USER_NAME" ] && [ "$SUDO_USER_NAME" != "root" ]; then
    echo "[4/4] Adding user '$SUDO_USER_NAME' to video group..."
    usermod -aG video "$SUDO_USER_NAME" 2>/dev/null || true
    echo "      Done. (You may need to log out and back in for group changes)"
fi

echo ""
echo "====================================="
echo "  Setup Complete!"
echo "====================================="
echo ""
echo "You can now start the streaming server:"
echo "  python3 camera_stream.py"
echo ""
echo "Or use the start script:"
echo "  ./start_stream.sh"
echo ""

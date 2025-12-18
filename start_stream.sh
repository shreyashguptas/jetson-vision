#!/bin/bash
# Jetson Camera Stream Launcher
# Interactive menu to configure and start the video stream

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if camera module is loaded
check_camera() {
    if ! ls /dev/video* &>/dev/null; then
        echo -e "${YELLOW}No video devices found. Attempting to load camera module...${NC}"
        if command -v sudo &>/dev/null; then
            sudo modprobe uvcvideo 2>/dev/null
            sleep 1
        fi

        if ! ls /dev/video* &>/dev/null; then
            echo -e "${RED}Error: No video devices found!${NC}"
            echo ""
            echo "Please ensure:"
            echo "  1. Camera is connected (lsusb | grep -i logitech)"
            echo "  2. Run: sudo modprobe uvcvideo"
            echo "  3. Check: ls -la /dev/video*"
            exit 1
        fi
    fi
}

# Quick start with defaults
quick_start() {
    echo -e "${GREEN}Quick Start - Using default settings${NC}"
    echo "Resolution: 1280x720 @ 30 FPS"
    echo ""
    python3 "$SCRIPT_DIR/camera_stream.py" "$@"
}

# Show help
show_help() {
    echo "Jetson Camera Stream Launcher"
    echo ""
    echo "Usage: ./start_stream.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  (no args)     Launch interactive configuration menu"
    echo "  --quick       Quick start with default settings (720p @ 30fps)"
    echo "  --help        Show this help message"
    echo ""
    echo "In interactive mode:"
    echo "  ← →           Switch between menus"
    echo "  ↑ ↓           Change selected option"
    echo "  Enter         Confirm / Start stream"
    echo "  Q             Quit"
    echo ""
    echo "Direct camera_stream.py options:"
    echo "  --device      Video device (e.g., /dev/video0)"
    echo "  --width       Frame width (default: 1280)"
    echo "  --height      Frame height (default: 720)"
    echo "  --fps         Frames per second (default: 30)"
    echo "  --port        Server port (default: 8080)"
}

# Main
main() {
    case "${1:-}" in
        --help|-h)
            show_help
            exit 0
            ;;
        --quick|-q)
            shift
            check_camera
            quick_start "$@"
            ;;
        --*)
            # Pass through to camera_stream.py directly
            check_camera
            python3 "$SCRIPT_DIR/camera_stream.py" "$@"
            ;;
        *)
            check_camera
            # Launch interactive menu
            python3 "$SCRIPT_DIR/stream_launcher.py"
            ;;
    esac
}

main "$@"

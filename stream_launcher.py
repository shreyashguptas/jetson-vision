#!/usr/bin/env python3
"""
Interactive Stream Launcher for Jetson Camera
Navigate with arrow keys, Enter to select, and start the stream with your preferred settings.
"""

import curses
import os
import subprocess
import sys

# Available options
RESOLUTIONS = [
    ("4K Ultra HD", 3840, 2160),
    ("1080p Full HD", 1920, 1080),
    ("720p HD", 1280, 720),
    ("480p SD", 640, 480),
    ("360p Low", 480, 360),
]

FRAMERATES = [
    ("60 FPS (Smooth)", 60),
    ("30 FPS (Standard)", 30),
    ("24 FPS (Cinematic)", 24),
    ("15 FPS (Low bandwidth)", 15),
]

QUALITY = [
    ("High (90%)", 90),
    ("Medium (80%)", 80),
    ("Low (60%)", 60),
]

PORTS = [
    ("8080 (Default)", 8080),
    ("8000", 8000),
    ("5000", 5000),
    ("3000", 3000),
]


class StreamLauncher:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.current_menu = 0  # 0=resolution, 1=fps, 2=quality, 3=port, 4=start
        self.selections = {
            'resolution': 2,  # Default: 720p
            'fps': 1,         # Default: 30 FPS
            'quality': 1,     # Default: Medium
            'port': 0,        # Default: 8080
        }
        self.menus = ['resolution', 'fps', 'quality', 'port', 'start']
        self.menu_options = {
            'resolution': RESOLUTIONS,
            'fps': FRAMERATES,
            'quality': QUALITY,
            'port': PORTS,
        }
        self.detected_device = None

        # Colors
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)   # Title/selected
        curses.init_pair(2, curses.COLOR_CYAN, -1)    # Headers
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Highlighted
        curses.init_pair(4, curses.COLOR_WHITE, -1)   # Normal
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_GREEN)  # Button
        curses.init_pair(6, curses.COLOR_RED, -1)     # Warning

        curses.curs_set(0)  # Hide cursor
        self.stdscr.keypad(True)

    def detect_camera(self):
        """Detect camera device."""
        import glob
        import cv2

        video_devices = sorted(glob.glob('/dev/video*'))
        for device in video_devices:
            try:
                cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None:
                        return device
            except:
                pass
        return None

    def draw_box(self, y, x, h, w, title=""):
        """Draw a box with optional title."""
        # Corners
        self.stdscr.addch(y, x, curses.ACS_ULCORNER)
        self.stdscr.addch(y, x + w - 1, curses.ACS_URCORNER)
        self.stdscr.addch(y + h - 1, x, curses.ACS_LLCORNER)
        self.stdscr.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)

        # Horizontal lines
        for i in range(1, w - 1):
            self.stdscr.addch(y, x + i, curses.ACS_HLINE)
            self.stdscr.addch(y + h - 1, x + i, curses.ACS_HLINE)

        # Vertical lines
        for i in range(1, h - 1):
            self.stdscr.addch(y + i, x, curses.ACS_VLINE)
            self.stdscr.addch(y + i, x + w - 1, curses.ACS_VLINE)

        # Title
        if title:
            self.stdscr.addstr(y, x + 2, f" {title} ", curses.color_pair(2) | curses.A_BOLD)

    def draw_menu_section(self, y, x, title, options, selected_idx, is_active):
        """Draw a menu section with options."""
        color = curses.color_pair(3) if is_active else curses.color_pair(4)
        title_color = curses.color_pair(2) | curses.A_BOLD if is_active else curses.color_pair(4)

        self.stdscr.addstr(y, x, title, title_color)

        for i, opt in enumerate(options):
            opt_y = y + 1 + i
            label = opt[0] if isinstance(opt, tuple) else opt

            if i == selected_idx:
                if is_active:
                    self.stdscr.addstr(opt_y, x, "  > ", curses.color_pair(1) | curses.A_BOLD)
                    self.stdscr.addstr(opt_y, x + 4, label, curses.color_pair(1) | curses.A_BOLD)
                else:
                    self.stdscr.addstr(opt_y, x, "  * ", curses.color_pair(1))
                    self.stdscr.addstr(opt_y, x + 4, label, curses.color_pair(1))
            else:
                self.stdscr.addstr(opt_y, x, "    " + label, curses.color_pair(4))

    def draw(self):
        """Draw the entire UI."""
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()

        # Title
        title = "JETSON CAMERA STREAM LAUNCHER"
        self.stdscr.addstr(1, (w - len(title)) // 2, title, curses.color_pair(1) | curses.A_BOLD)

        subtitle = "Use Arrow Keys to navigate, Enter to select"
        self.stdscr.addstr(2, (w - len(subtitle)) // 2, subtitle, curses.color_pair(4))

        # Draw separator
        self.stdscr.addstr(3, 2, "─" * (w - 4), curses.color_pair(4))

        # Calculate column positions
        col_width = (w - 8) // 4
        col1 = 4
        col2 = col1 + col_width
        col3 = col2 + col_width
        col4 = col3 + col_width

        # Draw menu sections
        self.draw_menu_section(5, col1, "RESOLUTION",
                               RESOLUTIONS, self.selections['resolution'],
                               self.current_menu == 0)

        self.draw_menu_section(5, col2, "FRAME RATE",
                               FRAMERATES, self.selections['fps'],
                               self.current_menu == 1)

        self.draw_menu_section(5, col3, "QUALITY",
                               QUALITY, self.selections['quality'],
                               self.current_menu == 2)

        self.draw_menu_section(5, col4, "PORT",
                               PORTS, self.selections['port'],
                               self.current_menu == 3)

        # Separator
        self.stdscr.addstr(13, 2, "─" * (w - 4), curses.color_pair(4))

        # Current configuration summary
        res = RESOLUTIONS[self.selections['resolution']]
        fps = FRAMERATES[self.selections['fps']]
        qual = QUALITY[self.selections['quality']]
        port = PORTS[self.selections['port']]

        self.stdscr.addstr(15, 4, "Current Configuration:", curses.color_pair(2) | curses.A_BOLD)
        config_str = f"{res[1]}x{res[2]} @ {fps[1]} FPS, Quality: {qual[1]}%, Port: {port[1]}"
        self.stdscr.addstr(16, 4, config_str, curses.color_pair(1))

        # Camera status
        if self.detected_device:
            self.stdscr.addstr(17, 4, f"Camera: {self.detected_device}", curses.color_pair(1))
        else:
            self.stdscr.addstr(17, 4, "Camera: Scanning...", curses.color_pair(6))

        # Start button
        button_text = "  [ START STREAM ]  "
        button_x = (w - len(button_text)) // 2
        button_y = 19

        if self.current_menu == 4:
            self.stdscr.addstr(button_y, button_x, button_text, curses.color_pair(5) | curses.A_BOLD)
        else:
            self.stdscr.addstr(button_y, button_x, button_text, curses.color_pair(1))

        # Help text
        help_text = "← → Switch menu | ↑ ↓ Change option | Enter: Start | Q: Quit"
        self.stdscr.addstr(h - 2, (w - len(help_text)) // 2, help_text, curses.color_pair(4))

        self.stdscr.refresh()

    def handle_input(self, key):
        """Handle keyboard input."""
        if key == curses.KEY_LEFT:
            self.current_menu = max(0, self.current_menu - 1)
        elif key == curses.KEY_RIGHT:
            self.current_menu = min(4, self.current_menu + 1)
        elif key == curses.KEY_UP:
            if self.current_menu < 4:
                menu_name = self.menus[self.current_menu]
                options = self.menu_options[menu_name]
                self.selections[menu_name] = max(0, self.selections[menu_name] - 1)
        elif key == curses.KEY_DOWN:
            if self.current_menu < 4:
                menu_name = self.menus[self.current_menu]
                options = self.menu_options[menu_name]
                self.selections[menu_name] = min(len(options) - 1, self.selections[menu_name] + 1)
        elif key == ord('\n') or key == curses.KEY_ENTER or key == 10:
            if self.current_menu == 4:
                return 'start'
            else:
                # Move to next menu on Enter
                self.current_menu = min(4, self.current_menu + 1)
        elif key == ord('q') or key == ord('Q'):
            return 'quit'
        elif key == ord('s') or key == ord('S'):
            return 'start'

        return None

    def get_stream_command(self):
        """Build the command to start the stream."""
        res = RESOLUTIONS[self.selections['resolution']]
        fps = FRAMERATES[self.selections['fps']]
        port = PORTS[self.selections['port']]

        script_dir = os.path.dirname(os.path.abspath(__file__))
        cmd = [
            sys.executable,
            os.path.join(script_dir, 'camera_stream.py'),
            '--width', str(res[1]),
            '--height', str(res[2]),
            '--fps', str(fps[1]),
            '--port', str(port[1]),
        ]

        if self.detected_device:
            cmd.extend(['--device', self.detected_device])

        return cmd

    def run(self):
        """Main loop."""
        # Start camera detection in background
        import threading
        def detect():
            self.detected_device = self.detect_camera()

        detect_thread = threading.Thread(target=detect, daemon=True)
        detect_thread.start()

        while True:
            self.draw()
            key = self.stdscr.getch()
            result = self.handle_input(key)

            if result == 'quit':
                return None
            elif result == 'start':
                return self.get_stream_command()


def show_starting_message(cmd):
    """Show a message before starting the stream."""
    print("\n" + "=" * 50)
    print("  Starting Jetson Camera Stream...")
    print("=" * 50)
    print(f"\n  Command: {' '.join(cmd)}")
    print("\n  Press Ctrl+C to stop the stream")
    print("=" * 50 + "\n")


def main():
    # Check if running in a terminal
    if not sys.stdin.isatty():
        print("Error: This script requires an interactive terminal")
        sys.exit(1)

    try:
        # Run the curses UI
        cmd = curses.wrapper(lambda stdscr: StreamLauncher(stdscr).run())

        if cmd:
            show_starting_message(cmd)
            # Execute the stream command
            subprocess.run(cmd)
        else:
            print("\nStream cancelled.")

    except KeyboardInterrupt:
        print("\nCancelled.")
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()

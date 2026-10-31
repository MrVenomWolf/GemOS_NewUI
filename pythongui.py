#!/usr/bin/env python3
"""
GemOS // CTos v4.2 — Production AI Engineering Workbench
Full-Stack Architecture:
  - Backend: Multi-threaded HTTP + SSE Streaming REST API + SQLite Persistence (`backend/`)
  - Frontend: Modern Reactive SPA with Live Streaming, Code Artifacts, & Telemetry (`frontend/`)
  - Desktop Container: Native GTK/WebKit2 Desktop Window (or PyWebView / App-Mode Browser fallback)
"""

import argparse
import ctypes
import os
import signal
import subprocess
import sys
import time
import webbrowser

from backend.server import start_server

APP_TITLE = "GemOS"
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blume_logo.ico")


def set_windows_app_id():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("gemos.ctos.workbench.v4")
    except Exception:
        pass


def launch_gtk_webkit_window(url: str) -> bool:
    """Launch a native desktop window using GTK3 + WebKit2 in a child process so GL/driver errors fall back cleanly."""
    if not sys.platform.startswith("linux"):
        return False
    helper_code = f"""
import os, signal, sys
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
import gi
gi.require_version("Gtk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gtk, WebKit2, Gdk

if not Gtk.init_check()[0]:
    sys.exit(2)

win = Gtk.Window(title={APP_TITLE!r})
win.set_default_size(1340, 840)
win.set_position(Gtk.WindowPosition.CENTER)

icon_path = {ICON_PATH!r}
if os.path.isfile(icon_path):
    try:
        win.set_icon_from_file(icon_path)
    except Exception:
        pass

webview = WebKit2.WebView()
settings = webview.get_settings()
settings.set_enable_developer_extras(True)
settings.set_enable_javascript(True)
settings.set_javascript_can_access_clipboard(True)

rgba = Gdk.RGBA()
rgba.parse("#000000")
webview.set_background_color(rgba)

webview.load_uri({url!r})
win.add(webview)
win.connect("destroy", Gtk.main_quit)
win.show_all()

signal.signal(signal.SIGINT, signal.SIG_DFL)
Gtk.main()
"""
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", helper_code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait briefly to confirm WebKit2 didn't immediately abort due to missing OpenGL/display context
        time.sleep(1.2)
        if proc.poll() is not None:
            return False
        proc.wait()
        return True
    except Exception:
        return False


def launch_pywebview_window(url: str) -> bool:
    """Launch a native window via pywebview if installed (Windows / macOS / Linux)."""
    try:
        import webview  # type: ignore

        webview.create_window(
            APP_TITLE,
            url,
            width=1340,
            height=840,
            min_size=(900, 600),
            background_color="#0a0e14",
        )
        webview.start()
        return True
    except Exception:
        return False


def launch_app_mode_browser(url: str) -> bool:
    """Try launching Edge/Chrome/Chromium in frameless desktop `--app` mode, or standard browser."""
    candidates = [
        "google-chrome",
        "chromium",
        "chromium-browser",
        "microsoft-edge",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for bin_name in candidates:
        try:
            subprocess.Popen(
                [bin_name, f"--app={url}", "--window-size=1340,840"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            continue

    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--port", type=int, default=0, help="Port for the GemOS backend server (default: auto)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--browser", action="store_true", help="Open in external web browser instead of native window")
    parser.add_argument("--server-only", action="store_true", help="Run the backend/frontend server headlessly")
    args = parser.parse_args()

    set_windows_app_id()

    server, port = start_server(host=args.host, port=args.port if args.port > 0 else None)
    url = f"http://{args.host}:{port}"

    print("============================================================")
    print(f"  GemOS // CTos v4.2 — Production AI Workbench")
    print(f"  Local Server : {url}")
    print(f"  Database     : backend/gemos.db")
    print("============================================================")

    try:
        if args.server_only:
            print("Running in server-only mode. Press Ctrl+C to stop.")
            while True:
                time.sleep(1)
        elif args.browser:
            launch_app_mode_browser(url)
            print("Opened in browser. Press Ctrl+C to stop the GemOS server.")
            while True:
                time.sleep(1)
        else:
            # Try PyWebView first, then GTK/WebKit2 native window, then browser fallback
            if launch_pywebview_window(url):
                return
            if launch_gtk_webkit_window(url):
                return
            print("Native WebView not active; opening in browser...")
            launch_app_mode_browser(url)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down GemOS server...")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()

"""
PAIA Engine -- Standalone Launcher
Starts the Streamlit server in-process and opens the browser automatically.
"""

import sys
import os

# Ensure console output doesn't crash on non-UTF-8 locales (e.g. cp932)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import threading
import time
import webbrowser
import argparse

PORT = 8501
URL = f"http://localhost:{PORT}"


def get_app_dir():
    """Return the directory containing the application files."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    else:
        return os.path.dirname(os.path.abspath(__file__))


def open_browser_delayed(delay=3, url=URL):
    """Open the browser after a short delay to let the server start."""
    time.sleep(delay)
    webbrowser.open(url)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start PAIA Engine")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    url = f"http://localhost:{args.port}"
    app_dir = get_app_dir()
    app_py = os.path.join(app_dir, "app.py")

    if not os.path.exists(app_py):
        print(f"ERROR: Cannot find app.py at {app_py}")
        input("Press Enter to exit...")
        sys.exit(1)

    print("=" * 60)
    print("  PAIA Engine -- Protein-Attribute Insights & Annotation")
    print("=" * 60)
    print()
    print(f"  Starting server on {url} ...")
    if not args.no_browser:
        print("  The app will open in your default browser shortly.")
    print()
    print("  To stop the server, close this window or press Ctrl+C.")
    print()

    # Open browser in a background thread after a short delay
    if not args.no_browser:
        browser_thread = threading.Thread(target=open_browser_delayed, args=(4, url), daemon=True)
        browser_thread.start()

    # Configure Streamlit options before importing bootstrap
    from streamlit import config

    config.set_option("server.headless", True)
    config.set_option("server.port", args.port)
    config.set_option("server.address", "localhost")
    config.set_option("browser.gatherUsageStats", False)
    config.set_option("global.developmentMode", False)

    # Launch Streamlit in-process via its bootstrap API
    from streamlit.web import bootstrap

    flag_options = {
        "server.headless": True,
        "server.port": args.port,
        "server.address": "localhost",
        "browser.gatherUsageStats": False,
        "global.developmentMode": False,
    }

    bootstrap.run(app_py, False, [], flag_options)


if __name__ == "__main__":
    main()

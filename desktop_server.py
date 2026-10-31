"""
ProofDeck Enterprise Desktop Edition — Local Offline Engine & Native Window Launcher
------------------------------------------------------------------------------------
Runs 100% locally on the user's PC using a local SQLite database vault
(backend/instance/proofdeck_desktop.db) with zero cloud database or Redis required.
"""
import os
import sys
import time
import socket
import threading
import subprocess
from flask import send_from_directory, make_response

# 1. Configure Desktop Environment Variables BEFORE importing create_app
is_frozen = getattr(sys, "frozen", False)
if is_frozen:
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    # Persistent user data directory in Windows Local AppData
    app_data_root = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ProofDeckEnterprise")
    INSTANCE_DIR = os.path.join(app_data_root, "instance")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    INSTANCE_DIR = os.path.join(BASE_DIR, "instance")

os.makedirs(INSTANCE_DIR, exist_ok=True)
upload_dir = os.path.join(INSTANCE_DIR, "uploads")
os.makedirs(upload_dir, exist_ok=True)

DEFAULT_SQLITE_PATH = os.path.join(INSTANCE_DIR, "proofdeck_desktop.db").replace("\\", "/")

os.environ["PROOFDECK_DESKTOP"] = "1"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")
os.environ.setdefault("UPLOAD_FOLDER", upload_dir)
os.environ.setdefault("FRONTEND_URL", "http://127.0.0.1:5000")

from pkg import create_app
from pkg.extensions import db
from pkg.routes.desktop import ensure_desktop_default_data

# Look for compiled React frontend
candidate_dists = [
    os.path.join(BASE_DIR, "frontend_dist"),
    os.path.join(BASE_DIR, "frontend", "dist"),
    os.path.abspath(os.path.join(BASE_DIR, "..", "frontend", "dist")),
]
FRONTEND_DIST = next((d for d in candidate_dists if os.path.exists(d)), candidate_dists[0])


def create_desktop_app():
    app = create_app()

    # Initialize local SQLite tables and default Enterprise Desktop workspace
    with app.app_context():
        db.create_all()
        ensure_desktop_default_data()

    # Serve compiled React frontend (frontend/dist) directly so the Desktop App
    # runs as a single self-contained process on 127.0.0.1:5000
    if os.path.exists(FRONTEND_DIST):
        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_spa(path):
            if path.startswith("api/") or path.startswith("uploads/"):
                return {"msg": "Not Found"}, 404
            full_path = os.path.join(FRONTEND_DIST, path)
            if path and os.path.exists(full_path) and os.path.isfile(full_path):
                resp = send_from_directory(FRONTEND_DIST, path)
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
                return resp
            index_path = os.path.join(FRONTEND_DIST, "index.html")
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    html = f.read()
                html = html.replace(
                    "<title>ProofDeck — #1 Certificate Maker Software & Online Certificate Verifier</title>",
                    "<title>ProofDeck Enterprise</title>"
                )
                resp = make_response(html, 200)
                resp.headers["Content-Type"] = "text/html; charset=utf-8"
                resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
                return resp
            resp = send_from_directory(FRONTEND_DIST, "index.html")
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            return resp

    return app


def _find_native_app_browser():
    """
    Finds Microsoft Edge (WebView2/Chromium built into Windows 10/11) or Chrome
    to render the frameless native desktop window (--app mode) with zero extra disk usage.
    """
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _wait_for_port(host, port, timeout=15.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def launch_desktop_window(url):
    print(f"[ProofDeck Desktop] Waiting for engine on port 5000...")
    _wait_for_port("127.0.0.1", 5000, timeout=12.0)

    print(f"[ProofDeck Desktop] Opening window: {url}")
    browser_exe = _find_native_app_browser()

    if browser_exe:
        # 1. First attempt: Edge/Chrome native app mode without locking profile
        try:
            proc = subprocess.Popen([
                browser_exe,
                f"--app={url}",
                "--window-size=1440,900",
                "--disable-features=TranslateUI",
                "--disable-cache",
                "--disk-cache-size=1",
                "--media-cache-size=1",
                "--no-first-run",
                "--no-default-browser-check",
            ])
            time.sleep(1.0)
            if proc.poll() is None or proc.returncode == 0:
                print("[ProofDeck Desktop] Native app window launched successfully.")
                return
        except Exception as e:
            print(f"[ProofDeck Desktop] App mode direct launch: {e}")

        # 2. Second attempt: dedicated profile (with stale lock cleanup)
        try:
            profile_dir = os.path.join(INSTANCE_DIR, "desktop_window_profile")
            lockfile_path = os.path.join(profile_dir, "lockfile")
            if os.path.exists(lockfile_path):
                try:
                    os.remove(lockfile_path)
                except Exception:
                    pass
            proc = subprocess.Popen([
                browser_exe,
                f"--app={url}",
                f"--user-data-dir={profile_dir}",
                "--window-size=1440,900",
                "--disable-features=TranslateUI",
                "--disable-cache",
                "--disk-cache-size=1",
                "--media-cache-size=1",
                "--no-first-run",
                "--no-default-browser-check",
            ])
            time.sleep(1.0)
            if proc.poll() is None or proc.returncode == 0:
                print("[ProofDeck Desktop] Dedicated profile app window launched.")
                return
        except Exception as e:
            print(f"[ProofDeck Desktop] Profile app mode: {e}")

    # 3. Reliable Fallback: Windows default browser
    try:
        os.system(f'start "" "{url}"')
        print("[ProofDeck Desktop] Opened in default web browser.")
    except Exception:
        import webbrowser
        webbrowser.open(url)
        print("[ProofDeck Desktop] Opened via webbrowser.")


def _is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    no_window = "--no-window" in sys.argv

    # Determine target URL
    target_url = os.environ.get("DESKTOP_START_URL") or f"http://127.0.0.1:{port}/dashboard?desktop=1"

    print("=================================================================")
    print("  ProofDeck Enterprise Desktop Edition (Local Offline Vault)")
    print(f"  Local Database : {DEFAULT_SQLITE_PATH}")
    print(f"  Desktop Engine : http://127.0.0.1:{port}")
    print("=================================================================")

    if _is_port_in_use(port):
        print(f"[ProofDeck Desktop] Engine is already active on port {port}.")
        if not no_window:
            launch_desktop_window(target_url)
        print("[ProofDeck Desktop] Ready. You can close this window when done.")
        sys.exit(0)

    desktop_app = create_desktop_app()

    if not no_window:
        threading.Thread(target=launch_desktop_window, args=(target_url,), daemon=True).start()

    desktop_app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)

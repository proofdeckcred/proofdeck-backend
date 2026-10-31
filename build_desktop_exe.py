"""
ProofDeck Enterprise — Windows Standalone Desktop Executable (.exe) Packager
------------------------------------------------------------------------------
Builds a self-contained, native Windows executable containing:
- Embedded Python runtime + Flask local offline credential engine
- Compiled React Frontend SPA (frontend/dist -> frontend_dist)
- Native WebView2 / Edge Chromium window launcher
- SQLite database & local export managers
"""
import os
import sys
import shutil
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
FRONTEND_DIST = os.path.join(ROOT_DIR, "frontend", "dist")

def main():
    print("==================================================================")
    print("  ProofDeck Enterprise Desktop — Packaging Windows Executable (.exe)")
    print("==================================================================")

    # 1. Verify frontend dist exists
    if not os.path.exists(FRONTEND_DIST):
        print(f"[ERROR] Frontend dist folder not found at: {FRONTEND_DIST}")
        print("Please run 'npm --prefix frontend run build' first.")
        sys.exit(1)

    index_html = os.path.join(FRONTEND_DIST, "index.html")
    if not os.path.exists(index_html):
        print(f"[ERROR] index.html missing in {FRONTEND_DIST}. Rebuilding frontend...")
        sys.exit(1)

    print(f"[OK] Verified React distribution at: {FRONTEND_DIST}")

    # 2. Determine PyInstaller executable
    venv_pyinstaller = os.path.join(BASE_DIR, "venv", "Scripts", "pyinstaller.exe")
    pyinstaller_cmd = venv_pyinstaller if os.path.exists(venv_pyinstaller) else "pyinstaller"

    # 3. Assemble PyInstaller arguments
    # We bundle the app into a single directory or single file.
    # A single-directory distribution (--onedir) starts in <1 second and is ideal
    # for creating an Inno Setup installer / MSI, while --onefile creates a standalone .exe.
    mode = "--onedir" if "--onedir" in sys.argv else "--onefile"
    print(f"[INFO] Build mode: {mode}")

    cmd = [
        pyinstaller_cmd,
        mode,
        "--noconfirm",
        "--clean",
        "--name=ProofDeck-Enterprise-Setup-1.0.0",
        # Hide black console window for native desktop feel (use --console if specified)
        "--console" if "--console" in sys.argv else "--noconsole",
        f"--add-data={FRONTEND_DIST};frontend_dist",
        "--hidden-import=pkg",
        "--hidden-import=pkg.routes",
        "--hidden-import=pkg.routes.desktop",
        "--hidden-import=pkg.routes.certificates",
        "--hidden-import=pkg.routes.groups",
        "--hidden-import=pkg.routes.templates",
        "--hidden-import=pkg.routes.auth",
        "--hidden-import=pkg.models",
        "--hidden-import=pkg.extensions",
        "--hidden-import=flask_cors",
        "--hidden-import=flask_jwt_extended",
        "--hidden-import=reportlab",
        "--hidden-import=pymupdf",
        "--hidden-import=fitz",
        "--hidden-import=cryptography",
        "--hidden-import=sqlalchemy",
        "--hidden-import=sqlite3",
        os.path.join(BASE_DIR, "desktop_server.py")
    ]

    print("\n[INFO] Executing PyInstaller build...")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode == 0:
        dist_dir = os.path.join(BASE_DIR, "dist")
        print("\n==================================================================")
        print("  BUILD SUCCESSFUL!")
        print(f"  Executable location: {dist_dir}")
        print("==================================================================")
    else:
        print(f"\n[ERROR] PyInstaller failed with exit code {result.returncode}")
        sys.exit(result.returncode)

if __name__ == "__main__":
    main()

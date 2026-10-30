"""Project Atlas standalone desktop launcher (`atlas-desktop`).

Starts atlas-api on a free loopback port with per-user data directories, then
opens the UI in a chromeless browser window (Edge/Chrome/Chromium ``--app``
mode when available, otherwise the default browser). Closing the launcher
(Ctrl+C or the tray console) stops the server.

Data locations:
  Windows  %LOCALAPPDATA%\\Project Atlas
  macOS    ~/Library/Application Support/Project Atlas
  Linux    $XDG_DATA_HOME/project-atlas (default ~/.local/share/project-atlas)
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def data_root() -> Path:
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Project Atlas"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Project Atlas"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "project-atlas"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def find_app_browser() -> list[str] | None:
    candidates = ["msedge", "microsoft-edge", "google-chrome", "chrome", "chromium", "chromium-browser"]
    if sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", ""), os.environ.get("LOCALAPPDATA", "")):
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
                p = Path(base) / rel
                if base and p.exists():
                    return [str(p)]
    if sys.platform == "darwin":
        for app in ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
            if Path(app).exists():
                return [app]
    for c in candidates:
        p = shutil.which(c)
        if p:
            return [p]
    return None


def main() -> int:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    env_file = root / ".env"
    if env_file.exists():
        os.environ.setdefault("ATLAS_ENV_FILE", str(env_file))
    port = int(os.environ.get("ATLAS_PORT") or free_port())
    os.environ.update({k: v for k, v in {
        "ATLAS_HOST": "127.0.0.1", "ATLAS_PORT": str(port), "ATLAS_STORAGE_DIR": str(root / "atlas-workspace"),
        "ATLAS_BACKUP_DIR": str(root / "atlas-backups"), "ATLAS_MODEL_DIR": str(root / "models"),
        "ATLAS_ENV": "production", "ATLAS_OFFLINE_MODE": "true"}.items() if k not in os.environ or k in {"ATLAS_HOST", "ATLAS_PORT"}})

    import uvicorn

    from project_atlas.core.config import load_settings
    from project_atlas.main import create_app

    settings = load_settings()
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="atlas-api", daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    for _ in range(120):
        try:
            urllib.request.urlopen(url + "api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.25)
    print(f"Project Atlas is running at {url}")
    print(f"Data directory: {root}")
    token = settings.storage_dir / "setup-token.txt"
    if token.exists():
        print(f"First run: the initial setup token is in {token}")
    browser = find_app_browser()
    if browser and os.environ.get("ATLAS_NO_BROWSER") != "1":
        profile = root / "browser-profile"
        subprocess.Popen(browser + [f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                                    "--disable-features=Translate,MediaRouter", "--disable-background-networking"])
    elif os.environ.get("ATLAS_NO_BROWSER") != "1":
        webbrowser.open(url)
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(10)
    return 0


if __name__ == "__main__":
    sys.exit(main())

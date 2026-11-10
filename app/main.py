"""Print Studio: starts the local server and opens the app window.

    .venv\\Scripts\\pythonw.exe app\\main.py
    ... main.py --browser      open in the default browser instead of an app window (for testing)
"""
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
PORT = 8765

# Started from the desktop shortcut (pythonw) there is no console: Python has no stdout/stderr, and the
# first log line would crash the server. Send all output to a log file instead.
if sys.stdout is None or sys.stderr is None:
    _log = open(Path(__file__).resolve().parents[1] / "jobs" / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log


def serve():
    import uvicorn
    from server import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def wait_ready():
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.1)


def running():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
        return True
    except OSError:
        return False


def main():
    if "--server" in sys.argv:
        serve()
        return
    owner = not running()                 # a second launch just opens another window on the same app
    if owner:
        threading.Thread(target=serve, daemon=True).start()
        wait_ready()
    url = f"http://127.0.0.1:{PORT}/"
    if "--browser" in sys.argv:
        import webbrowser
        webbrowser.open(url)
        threading.Event().wait()
    import webview
    webview.create_window("Print Studio", url, width=1440, height=900, min_size=(1100, 720),
                          background_color="#EDEFE9")
    webview.start()
    if owner:                             # window closed: stop the 3D engine too, so it frees its RAM
        import server
        server.studio.worker.stop()


if __name__ == "__main__":
    main()

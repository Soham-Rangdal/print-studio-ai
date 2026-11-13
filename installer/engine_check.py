"""Prove the 3D engine starts: launch the GPU worker, wait for "ready", then quit. No model is loaded.

A package can be "installed" according to pip and still be missing its files (a broken cached wheel), so
setup checks the real start-up instead of trusting pip. If a module is missing, its pip package is
reinstalled without the cache and the check runs again.
    python engine_check.py            exit 0 = engine starts
"""
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from config import WANGP, WANGP_PY  # noqa: E402

PACKAGE_FOR = {"whisper": "openai-whisper", "cv2": "opencv-python", "PIL": "pillow", "yaml": "pyyaml",
               "sklearn": "scikit-learn", "skimage": "scikit-image", "google": "protobuf"}


def start_once(timeout=420):
    proc = subprocess.Popen([str(WANGP_PY), str(ROOT / "worker" / "gpu_worker.py")], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", env={**os.environ, "PRINT_STUDIO_WANGP": str(WANGP)})
    err, ready = [], threading.Event()
    threading.Thread(target=lambda: [err.append(line) for line in proc.stderr], daemon=True).start()

    def read():
        for line in proc.stdout:
            try:
                if json.loads(line).get("event") == "ready":
                    ready.set()
            except ValueError:
                pass

    threading.Thread(target=read, daemon=True).start()
    ok = False
    while not ok and proc.poll() is None:
        ok = ready.wait(2)
        timeout -= 2
        if timeout <= 0:
            break
    try:
        if ok:
            proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
            proc.stdin.flush()
        proc.wait(timeout=30)
    except Exception:  # noqa: BLE001
        proc.kill()
    return ok, "".join(err[-40:])


def main():
    if not WANGP_PY.is_file():
        sys.exit(f"The 3D engine is missing: {WANGP_PY}")
    repaired = set()
    for attempt in range(4):
        print("  Starting the 3D engine to check it...", flush=True)
        ok, log = start_once()
        if ok:
            print("  The 3D engine starts.", flush=True)
            return
        m = re.findall(r"No module named '([\w.]+)'", log)
        module = m[-1].split(".")[0] if m else None
        if not module or module in repaired:
            print(log)
            sys.exit("The 3D engine did not start (see the messages above).")
        package = PACKAGE_FOR.get(module, module)
        print(f"  Missing module '{module}': reinstalling '{package}' without the download cache...", flush=True)
        subprocess.run([str(WANGP_PY), "-m", "pip", "install", "--no-cache-dir", "--force-reinstall", "--no-deps", package])
        repaired.add(module)
    sys.exit("The 3D engine still did not start after repairs.")


if __name__ == "__main__":
    main()

"""Download every AI model Print Studio uses, by running each 3D step once on a test picture.

WanGP fetches a model's weights the first time it is used, so one small run per step downloads exactly what
the app needs (and nothing of WanGP's other 100+ models). It also proves the GPU works before the user
starts. Run by setup with the app's Python:

    .venv\\Scripts\\python.exe installer\\prefetch.py
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from config import WANGP, WANGP_PY  # noqa: E402

OUT = ROOT / "jobs" / "_setup_check"
STEPS = [
    ("image", "Image model (Z-Image Turbo)", {"prompt": "a small chunky toy dragon, green body, yellow belly, "
                                              "plain white background, product photo", "count": 1, "seed": 7}),
    ("shape1", "3D shape from one picture (TRELLIS.2)", {}),
    ("texture1", "Colours from one picture (TRELLIS.2 Texture)", {}),
    ("shape4", "3D shape from four pictures (Pixal3D)", {}),
    ("texture4", "Colours from four pictures (Pixal3D Texture)", {}),
]


def main():
    if not WANGP_PY.is_file():
        sys.exit(f"The 3D engine is missing: {WANGP_PY}")
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    # WanGP's download bars go to stderr: pass them straight through so the user sees progress
    proc = subprocess.Popen([str(WANGP_PY), str(ROOT / "worker" / "gpu_worker.py")], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
                            env={**os.environ, "PRINT_STUDIO_WANGP": str(WANGP)})
    events = []
    ready = threading.Event()

    def read():
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "ready":
                ready.set()
            events.append(ev)

    threading.Thread(target=read, daemon=True).start()

    def call(n, cmd, **args):
        proc.stdin.write(json.dumps({"id": str(n), "cmd": cmd, **args}) + "\n")
        proc.stdin.flush()
        result = None
        while True:
            for ev in [e for e in events if e.get("id") == str(n)]:
                events.remove(ev)
                if ev["event"] == "error":
                    raise RuntimeError(ev.get("message", "failed"))
                if ev["event"] == "done":
                    result = ev
                if ev["event"] == "released":
                    return result
            if proc.poll() is not None:
                raise RuntimeError("the 3D engine stopped (see the messages above)")
            time.sleep(0.5)

    print("\n[*] Starting the 3D engine...", flush=True)
    while not ready.wait(2):
        if proc.poll() is not None:
            sys.exit("The 3D engine did not start (see the messages above).")
    picture = mesh1 = mesh4 = None
    for n, (key, label, args) in enumerate(STEPS, 1):
        print(f"\n[{n}/{len(STEPS)}] {label}: downloading if needed, then one test run...", flush=True)
        t0 = time.time()
        if key == "image":
            picture = call(n, "image", out_dir=str(OUT), **args)["files"][0]
        elif key == "shape1":
            mesh1 = call(n, "shape", images=[picture], seed=1, out=str(OUT / "shape1.glb"))["file"]
        elif key == "texture1":
            call(n, "texture", mesh=mesh1, images=[picture], out=str(OUT / "textured1.glb"))
        elif key == "shape4":
            mesh4 = call(n, "shape", images=[picture] * 4, seed=1, out=str(OUT / "shape4.glb"))["file"]
        elif key == "texture4":
            call(n, "texture", mesh=mesh4, images=[picture] * 4, out=str(OUT / "textured4.glb"))
        print(f"    ok ({time.time() - t0:.0f} s)", flush=True)
    proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
    proc.stdin.flush()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(OUT, ignore_errors=True)
    print("\n[*] All models are downloaded and working.", flush=True)


if __name__ == "__main__":
    main()

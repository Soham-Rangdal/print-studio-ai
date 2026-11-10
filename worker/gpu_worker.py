"""Print Studio GPU worker: one long-lived WanGP session in its own process.

Started by the app with WanGP's Python. Reads one JSON command per line on stdin, writes JSON events per
line on stdout (anything else WanGP prints goes to stderr). After every job the models are released
(memory rule 4), so RAM stays free between steps.

Commands:
  {"id": "...", "cmd": "image",   "prompt": str, "count": n, "seed": int, "out_dir": str}
  {"id": "...", "cmd": "shape",   "images": [1 or 4 paths], "seed": int, "out": path.glb}
  {"id": "...", "cmd": "texture", "mesh": path, "images": [1 or 4 paths], "out": path.glb}
  {"id": "...", "cmd": "refine",  "mesh": path, "image": path, "level": 512, "out": path.glb}
  {"id": "...", "cmd": "quit"}
Events: {"id","event":"started"|"progress"|"done"|"error", ...}
"""
import gc
import json
import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

WANGP = Path(os.environ.get("PRINT_STUDIO_WANGP") or Path(__file__).resolve().parents[2] / "Wan2GP")
_out = sys.stdout
sys.stdout = sys.stderr            # WanGP's prints must not corrupt the event stream
_lock = threading.Lock()


def emit(**event):
    with _lock:
        _out.write(json.dumps(event) + "\n")
        _out.flush()


def first(result, exts):
    return next((Path(f) for f in result.generated_files if str(f).lower().endswith(exts)), None)


def main():
    os.chdir(WANGP)
    sys.path.insert(0, str(WANGP))
    from shared.api import init
    session = init(root=WANGP, output_dir=Path(__file__).resolve().parents[1] / "jobs" / "_raw",
                   cli_args=["--profile", "4", "--attention", "sdpa"], console_output=False)
    import wgp
    emit(event="ready")

    def run(settings, exts, target):
        r = session.submit_task(settings).result()
        if not r.success:
            raise RuntimeError("; ".join(e.message for e in r.errors) or "generation failed")
        f = first(r, exts)
        if f is None:
            raise RuntimeError("the model produced no output")
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, target)
        return str(target)

    def post(mesh, target, **kw):
        r = session.submit_media_postprocessing(str(mesh), **kw).result()
        if not r.success:
            raise RuntimeError("; ".join(e.message for e in r.errors) or "post-processing failed")
        f = first(r, (".glb",))
        if f is None:
            raise RuntimeError("no model was produced")
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, target)
        return str(target)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        job = json.loads(line)
        jid, cmd = job.get("id"), job.get("cmd")
        if cmd == "quit":
            break
        emit(id=jid, event="started", cmd=cmd)
        t0 = time.time()
        try:
            if cmd == "image":
                out_dir = Path(job["out_dir"])
                files = []
                for i in range(int(job.get("count", 1))):
                    seed = int(job.get("seed", 1)) + i
                    files.append(run({"model_type": "z_image", "prompt": job["prompt"], "resolution": "1024x1024",
                                      "num_inference_steps": 8, "seed": seed},
                                     (".png", ".jpg", ".webp"), out_dir / f"option_{i + 1}.png"))
                    emit(id=jid, event="progress", done=i + 1, total=int(job.get("count", 1)), files=files)
                result = {"files": files}
            elif cmd == "shape":
                imgs = job["images"]
                model = "pixal3d_mv_shape" if len(imgs) == 4 else "trellis2_shape"
                result = {"file": run({"model_type": model, "prompt": "object", "image_refs": imgs,
                                       "video_prompt_type": "I", "image_mode": 1, "seed": int(job.get("seed", 1))},
                                      (".glb",), job["out"]), "model": model}
            elif cmd == "texture":
                imgs = job["images"]
                method = "pixal3d_texture" if len(imgs) == 4 else "trellis2_texture"
                result = {"file": post(job["mesh"], job["out"], temporal_upsampling=method,
                                       postprocessing_reference_images=imgs,
                                       temporal_postprocessing_parameters={"texture_size": 2048})}
            elif cmd == "refine":
                result = {"file": post(job["mesh"], job["out"], spatial_upsampling="hi3d",
                                       postprocessing_reference_images=[job["image"]],
                                       spatial_postprocessing_parameters={"hi3d_level": int(job.get("level", 512))})}
            else:
                raise ValueError(f"unknown command {cmd}")
            emit(id=jid, event="done", seconds=round(time.time() - t0, 1), **result)
        except Exception as e:  # noqa: BLE001 - report to the app, keep serving
            traceback.print_exc()
            emit(id=jid, event="error", message=str(e)[:500], seconds=round(time.time() - t0, 1))
        finally:
            try:                                   # memory rule 4: release this step's models
                session.close()
                wgp.release_extension_offloadobjs()
                gc.collect()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            emit(id=jid, event="released")


if __name__ == "__main__":
    main()

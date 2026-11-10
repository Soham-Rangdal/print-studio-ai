"""Phase 1: run every WanGP model of the pipeline once on this laptop and measure it.

For each stage: wall time, peak dedicated VRAM and peak *shared* GPU memory of this process (shared = the
silent spill into system RAM), peak process RAM, lowest free system RAM. The stages chain like the real
pipeline: a text-made dragon -> 3 more views -> two 3D shapes -> textures -> Hi3D -> GeoSAM2.

    <Wan2GP>\\env_venv\\Scripts\\python.exe smoke_test.py                           all stages
    ... smoke_test.py image views                                                   only some
Outputs and results.json go to print-agent\\tests\\smoke\\. Close WanGP's own window first.
"""
import json
import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT / "app"))
from config import WANGP  # noqa: E402
OUT = AGENT / "tests" / "smoke"
VIEWS = ["front", "right", "back", "left"]

DRAGON = ("A cute chunky toy dragon figurine, standing on all four legs, small folded wings close to the body, thick "
          "short horns, rounded stocky shapes, green body with a yellow belly and orange spikes, smooth matte plastic, "
          "single object, full body fully in frame, centered, front view, plain white background, soft even studio "
          "lighting, no shadows, product photo")
VIEW_PROMPT = ("The same toy dragon figurine, identical design, colours and proportions, seen exactly from the {side}, "
               "full body fully in frame, centered, plain white background, soft even studio lighting, no shadows")


class Meter:
    """Samples this process's GPU memory (Windows performance counters) and RAM every 0.5 s."""

    def __init__(self):
        import psutil
        import win32pdh
        self.psutil, self.pdh, self.pid = psutil, win32pdh, os.getpid()
        self.reset()
        threading.Thread(target=self._loop, daemon=True).start()

    def reset(self):
        self.peak = {"dedicated_gb": 0.0, "shared_gb": 0.0, "rss_gb": 0.0}
        self.min_free_ram_gb = 99.0

    def _gpu(self):
        out = {}
        for kind in ("Dedicated Usage", "Shared Usage"):
            total = 0
            try:
                paths = self.pdh.ExpandCounterPath(rf"\GPU Process Memory(pid_{self.pid}_*)\{kind}")
                q = self.pdh.OpenQuery()
                hs = [self.pdh.AddCounter(q, p) for p in paths]
                self.pdh.CollectQueryData(q)
                for h in hs:
                    total += self.pdh.GetFormattedCounterValue(h, self.pdh.PDH_FMT_LARGE)[1]
                self.pdh.CloseQuery(q)
            except Exception:  # noqa: BLE001 - counter not there yet
                pass
            out[kind] = total / 1e9
        return out["Dedicated Usage"], out["Shared Usage"]

    def _loop(self):
        proc = self.psutil.Process(self.pid)
        while True:
            ded, sh = self._gpu()
            p = self.peak
            p["dedicated_gb"] = max(p["dedicated_gb"], ded)
            p["shared_gb"] = max(p["shared_gb"], sh)
            p["rss_gb"] = max(p["rss_gb"], proc.memory_info().rss / 1e9)
            self.min_free_ram_gb = min(self.min_free_ram_gb, self.psutil.virtual_memory().available / 1e9)
            time.sleep(0.5)


def first(result, exts):
    return next((Path(f) for f in result.generated_files if str(f).lower().endswith(exts)), None)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    os.chdir(WANGP)
    sys.path.insert(0, str(WANGP))
    from shared.api import init
    session = init(root=WANGP, output_dir=OUT / "_raw", cli_args=["--profile", "4", "--attention", "sdpa"],
                   console_output=False)
    meter = Meter()
    results_file = OUT / "results.json"
    results = json.loads(results_file.read_text()) if results_file.exists() else {}
    p = {v: OUT / f"{v}.png" for v in VIEWS}

    def gen(settings, exts, target):
        r = session.submit_task(settings).result()
        if not r.success:
            raise RuntimeError("; ".join(e.message for e in r.errors))
        f = first(r, exts)
        if f is None:
            raise RuntimeError(f"no {exts} output in {r.generated_files}")
        shutil.copyfile(f, target)
        return target

    def post(mesh, target, **kw):
        r = session.submit_media_postprocessing(str(mesh), **kw).result()
        if not r.success:
            raise RuntimeError("; ".join(e.message for e in r.errors))
        f = first(r, (".glb",))
        if f is None:
            raise RuntimeError(f"no .glb output in {r.generated_files}")
        shutil.copyfile(f, target)
        return target

    stages = {
        "image": ("Z-Image Turbo: text -> front image", lambda: gen(
            {"model_type": "z_image", "prompt": DRAGON, "resolution": "1024x1024", "num_inference_steps": 8, "seed": 7},
            (".png", ".jpg", ".webp"), p["front"])),
        "views": ("Flux 3 Klein: right, back, left views", lambda: [gen(
            {"model_type": "flux3_klein", "prompt": VIEW_PROMPT.format(side=f"{side} side" if side != "back" else "back"),
             "image_refs": [str(p["front"])], "video_prompt_type": "KI", "resolution": "1024x1024", "seed": 11},
            (".png", ".jpg", ".webp"), p[side]) for side in ("right", "back", "left")]),
        "trellis_shape": ("TRELLIS.2 Shape: 1 image -> mesh", lambda: gen(
            {"model_type": "trellis2_shape", "prompt": "toy dragon", "image_refs": [str(p["front"])],
             "video_prompt_type": "I", "image_mode": 1, "seed": 1}, (".glb",), OUT / "shape_trellis.glb")),
        "pixal_shape": ("Pixal3D Multi-View: 4 views -> mesh", lambda: gen(
            {"model_type": "pixal3d_mv_shape", "prompt": "toy dragon", "image_refs": [str(p[v]) for v in VIEWS],
             "video_prompt_type": "I", "image_mode": 1, "seed": 1}, (".glb",), OUT / "shape_pixal.glb")),
        "pixal_texture": ("Pixal3D Texture (4 views) on the Pixal3D mesh", lambda: post(
            OUT / "shape_pixal.glb", OUT / "textured_pixal.glb", temporal_upsampling="pixal3d_texture",
            postprocessing_reference_images=[str(p[v]) for v in VIEWS],
            temporal_postprocessing_parameters={"texture_size": 2048})),
        "trellis_texture": ("TRELLIS.2 Texture (1 view) on the TRELLIS.2 mesh", lambda: post(
            OUT / "shape_trellis.glb", OUT / "textured_trellis.glb", temporal_upsampling="trellis2_texture",
            postprocessing_reference_images=[str(p["front"])],
            temporal_postprocessing_parameters={"texture_size": 2048})),
        "hi3d": ("Hi3D refine (level 512) on the Pixal3D mesh", lambda: post(
            OUT / "shape_pixal.glb", OUT / "refined_hi3d.glb", spatial_upsampling="hi3d",
            postprocessing_reference_images=[str(p["front"])], spatial_postprocessing_parameters={"hi3d_level": 512})),
        "geosam2": ("GeoSAM2: split the Pixal3D mesh into parts", lambda: gen(
            {"model_type": "geosam2", "prompt": "segmented mesh", "custom_guide": str(OUT / "shape_pixal.glb"),
             "image_mode": 1, "seed": 3}, (".glb",), OUT / "parts_geosam2.glb")),
    }
    chosen = [a for a in sys.argv[1:] if a in stages] or list(stages)
    for key in chosen:
        label, fn = stages[key]
        print(f"\n=== {key}: {label}", flush=True)
        meter.reset()
        t = time.time()
        entry = {"label": label}
        try:
            fn()
            entry["ok"] = True
        except Exception as e:  # noqa: BLE001 - record and continue with the next stage
            entry["ok"] = False
            entry["error"] = str(e)[:600]
            traceback.print_exc()
        if "--release" in sys.argv:   # memory rule 4: drop this stage's models before the next one
            import gc
            import wgp
            session.close()
            wgp.release_extension_offloadobjs()
            gc.collect()
            entry["free_ram_after_release_gb"] = round(meter.psutil.virtual_memory().available / 1e9, 2)
        time.sleep(1.0)
        entry.update(seconds=round(time.time() - t), **{k: round(v, 2) for k, v in meter.peak.items()},
                     min_free_ram_gb=round(meter.min_free_ram_gb, 2))
        results[key] = entry
        results_file.write_text(json.dumps(results, indent=1), encoding="utf-8")
        status = "OK" if entry["ok"] else "FAILED: " + entry["error"][:200]
        print(f"--- {key}: {status} | {entry['seconds']} s | VRAM {entry['dedicated_gb']} GB | shared "
              f"{entry['shared_gb']} GB | RAM {entry['rss_gb']} GB | free RAM low {entry['min_free_ram_gb']} GB", flush=True)
    print("\nDone. Results:", results_file)


if __name__ == "__main__":
    main()

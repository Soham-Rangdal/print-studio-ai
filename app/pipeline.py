"""Print Studio pipeline: projects, steps, the GPU worker and the gemma helper.

Every project lives in jobs\\<id>\\ with a job.json that holds its state, so the app can be closed and
reopened at any time. One background thread runs the steps; GPU steps take turns through one lock.

Stages (what she sees):
  writing -> imagining -> choose_image        (from an idea)
  photos  ->                                   (from 1 or 4 photos)
  importing ->                                 (from a 3D file she already has: STL, 3MF, OBJ, GLB, ...)
  shaping -> review_shape                      (3D model with colours: approve / try again)
  measuring -> size                            (height + her 4 filaments, live size chart)
  preparing -> review_final                    (printability checks, final colours: approve)
  exporting -> done                            (files, open in Creality Print)
  error
"""
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "jobs"
sys.path.insert(0, str(ROOT / "tools"))
import colours  # noqa: E402
import editmesh  # noqa: E402
import export3mf  # noqa: E402
import importmesh  # noqa: E402
import meshprep  # noqa: E402
import render  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CREALITY, OLLAMA_MODEL, OLLAMA_URL, WANGP, WANGP_PY  # noqa: E402

IDEA_SYSTEM = """You help design toys and objects for a multicolour FDM 3D printer (4 filament colours).
Given the user's idea, reply with ONLY a JSON object, no other text:
{"name": "<2-4 word name, Title Case>",
 "subject": "<one sentence describing ONE object to print: chunky, sturdy toy-like proportions, thick parts,
             no thin wings, spikes or strands, standing on a flat stable base or wide feet, at most 4 clear
             flat colour areas named explicitly, no text, no scene>"}"""


def _ask_llm(idea):
    """Gemma through the local Ollama server. keep_alive 0 unloads it straight after, so the GPU is free for the
    3D models (memory rule 1). Raises if Ollama isn't running or the model isn't pulled."""
    import urllib.request
    body = json.dumps({"model": OLLAMA_MODEL, "stream": False, "format": "json", "keep_alive": 0,
                       "options": {"temperature": 0.4, "num_ctx": 2048},
                       "messages": [{"role": "system", "content": IDEA_SYSTEM}, {"role": "user", "content": idea}]})
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", body.encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        text = json.loads(r.read())["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0))

REFERENCE_HEIGHT_MM = 100.0
DEFAULT_PALETTE = ["#3F9B48", "#F3D34A", "#EE7A22", "#F5F3EE"]
FILAMENT_DENSITY = 1.24          # g/cm³, PLA
WALL_MM = 1.2                    # ~3 lines of a 0.4 mm nozzle
INFILL = 0.15
GRAMS_CALIBRATION = 0.82        # Creality Print sliced the 12 cm dragon at 77.4 g where the formula gave 94 g

# typical times on this laptop (phase 1/2 measurements), for the progress estimate
ETA = {"converting": 30, "stepping": 90, "importing": 15, "writing": 20, "imagining": 75, "shaping": 260, "editprep": 20, "measuring": 135, "preparing": 140,
       "exporting": 10}

IMAGE_STYLE = ("Single object, full body fully in frame, centered, front view, plain white background, soft even "
               "studio lighting, no shadows, smooth matte plastic toy figurine, product photo")


class Worker:
    """The WanGP GPU worker process, spoken to with JSON lines."""

    def __init__(self, log):
        self.log, self.proc, self.ready = log, None, threading.Event()
        self.pending, self.lock = {}, threading.Lock()

    def start(self):
        if not WANGP_PY.is_file():                 # reported when a 3D step is asked for (see call)
            self.log(f"3D engine not found: {WANGP_PY}")
            return
        self.proc = subprocess.Popen([str(WANGP_PY), str(ROOT / "worker" / "gpu_worker.py")], stdin=subprocess.PIPE,
                                     env={**os.environ, "PRINT_STUDIO_WANGP": str(WANGP)},
                                     stdout=subprocess.PIPE, stderr=open(ROOT / "jobs" / "worker.log", "w", encoding="utf-8"),
                                     text=True, encoding="utf-8", bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "ready":
                self.ready.set()
                continue
            q = self.pending.get(ev.get("id"))
            if q:
                q.put(ev)
        for q in list(self.pending.values()):
            q.put({"event": "error", "message": "The 3D engine stopped unexpectedly."})

    def call(self, cmd, on_progress=None, timeout=1800, **args):
        if self.proc is None:
            raise RuntimeError("The 3D engine isn't installed. Run Print Studio's setup again.")
        if not self.ready.wait(timeout=300):
            raise RuntimeError("The 3D engine did not start.")
        jid = uuid.uuid4().hex[:8]
        q = queue.Queue()
        self.pending[jid] = q
        with self.lock:
            self.proc.stdin.write(json.dumps({"id": jid, "cmd": cmd, **args}) + "\n")
            self.proc.stdin.flush()
        result = None
        try:
            while True:
                ev = q.get(timeout=timeout)
                if ev["event"] == "progress" and on_progress:
                    on_progress(ev)
                elif ev["event"] == "done":
                    result = ev
                elif ev["event"] == "error":
                    raise RuntimeError(ev.get("message", "failed"))
                elif ev["event"] == "released":
                    return result
        finally:
            self.pending.pop(jid, None)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.kill()


class Studio:
    def __init__(self, notify):
        self.notify = notify                       # called with a job dict whenever it changes
        self.gpu = threading.Lock()                # one heavy model at a time (memory rule 1)
        self.files = threading.RLock()             # job.json reads and writes never overlap
        self.tasks = queue.Queue()
        self.worker = Worker(print)
        self._cache = {}                           # job id -> prepared reference model (for live estimates)
        JOBS.mkdir(exist_ok=True)

    def start(self):
        self.worker.start()
        threading.Thread(target=self._loop, daemon=True).start()
        for job in self.list_jobs():               # resume work interrupted by closing the app
            if job["stage"] in ETA:
                self._stage(job, job["stage"], job.get("status") or "Continuing")   # fresh timer
                self.tasks.put((job["id"], job["stage"]))

    # ------------------------------------------------------------------ storage
    def _dir(self, jid):
        return JOBS / jid

    def load(self, jid):
        with self.files:
            return json.loads((self._dir(jid) / "job.json").read_text(encoding="utf-8"))

    def save(self, job):
        """Atomic: write a temporary file, then swap it in, so a reader never sees a half-written file."""
        job["updated"] = time.time()
        p = self._dir(job["id"]) / "job.json"
        tmp = p.with_suffix(".tmp")
        with self.files:
            tmp.write_text(json.dumps(job, indent=1), encoding="utf-8")
            os.replace(tmp, p)
        self.notify(job)
        return job

    def list_jobs(self):
        out = []
        for p in sorted(JOBS.glob("*/job.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                pass
        return sorted(out, key=lambda j: j.get("created", 0), reverse=True)

    def _next_number(self):
        nums = [int(j["number"].split("-")[1]) for j in self.list_jobs() if j.get("number", "").startswith("PS-")]
        return f"PS-{(max(nums) + 1) if nums else 1:03d}"

    def _new(self, source, name):
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "model"
        jid = datetime.now().strftime("%Y%m%d-%H%M%S-") + slug
        (self._dir(jid)).mkdir(parents=True)
        return {"id": jid, "number": self._next_number(), "name": name, "source": source, "created": time.time(),
                "stage": "", "status": "", "attempt": 1, "images": [], "photos": [], "unseen": False,
                "settings": {"height_mm": REFERENCE_HEIGHT_MM, "palette": list(DEFAULT_PALETTE)}}

    # ------------------------------------------------------------------ public actions
    def create_from_idea(self, idea):
        job = self._new("idea", idea.strip().capitalize()[:40] or "New model")
        job.update(idea=idea.strip())
        self._stage(job, "writing", "Reading your idea")
        self.tasks.put((job["id"], "writing"))
        return job

    def create_from_photos(self, files):
        """files: list of (filename, bytes) in order front, right, back, left (or a single photo)."""
        job = self._new("photos", "Photo model")
        d = self._dir(job["id"]) / "photos"
        d.mkdir()
        names = ["front", "right", "back", "left"] if len(files) == 4 else ["front"]
        for (fname, data), view in zip(files, names):
            ext = Path(fname).suffix.lower() or ".png"
            (d / f"{view}{ext}").write_bytes(data)
            job["photos"].append(f"photos/{view}{ext}")
        self._stage(job, "shaping", "Building the 3D model")
        self.tasks.put((job["id"], "shaping"))
        return job

    def create_from_file(self, files):
        """files: list of (filename, bytes): one 3D file, or a model with its companions, or a .zip."""
        main = next((n for n, _ in files if Path(n).suffix.lower() in importmesh.MODEL_EXT | {".zip"}), files[0][0])
        stem = re.sub(r"^(ps|model|print)[\s_-]*\d+[\s_-]*", "", Path(main).stem, flags=re.I)   # "PS-001 Dragon"
        name = re.sub(r"[_\-.]+", " ", stem).strip().capitalize()[:40] or "3D file"
        job = self._new("file", name)
        d = self._dir(job["id"]) / "source"
        d.mkdir()
        for fname, data in files:
            safe = re.sub(r"[^A-Za-z0-9 ._()-]+", "_", Path(fname).name).strip() or "model"
            if Path(safe).suffix.lower() in importmesh.ACCEPTED_EXT:
                (d / safe).write_bytes(data)
        job["source_files"] = sorted(p.name for p in d.iterdir())
        self._stage(job, "importing", "Opening your file")
        self.tasks.put((job["id"], "importing"))
        return job

    def create_conversion(self, files):
        """Mesh files -> solid STEP files for CAD, one per model file (a .zip may hold several)."""
        models = [n for n, _ in files if Path(n).suffix.lower() in importmesh.MODEL_EXT | {".zip"}]
        if not models:
            raise ValueError("Add at least one mesh file: STL, 3MF, OBJ, GLB, PLY, OFF or a .zip.")
        first = re.sub(r"[_\-.]+", " ", Path(models[0]).stem).strip()
        job = self._new("convert", (f"{first} (solid)" if len(models) == 1 else f"{len(models)} meshes to solid")[:40])
        d = self._dir(job["id"]) / "source"
        d.mkdir()
        for fname, data in files:
            safe = re.sub(r"[^A-Za-z0-9 ._()-]+", "_", Path(fname).name).strip() or "model"
            if Path(safe).suffix.lower() in importmesh.ACCEPTED_EXT:
                (d / safe).write_bytes(data)
        job["conversions"] = [{"file": Path(n).name, "status": "waiting"} for n in models]
        job["eta_per_file"] = 30
        self._stage(job, "converting", "Converting to solid")
        job["eta_s"] = 30 * len(models)
        self.save(job)
        self.tasks.put((job["id"], "converting"))
        return job

    def act(self, jid, action, data):
        job = self.load(jid)
        if action == "seen":
            job["unseen"] = False
            return self.save(job)
        if action == "choose_image" and job["stage"] == "choose_image":
            job["chosen_image"] = job["images"][int(data["index"])]
            self._stage(job, "shaping", "Building the 3D model")
            self.tasks.put((jid, "shaping"))
        elif action == "more_images" and job["stage"] == "choose_image":
            job["attempt"] += 1
            self._stage(job, "imagining", "Drawing new options")
            self.tasks.put((jid, "imagining"))
        elif action == "retry_shape" and job["stage"] == "review_shape":
            job["attempt"] += 1
            self._stage(job, "shaping", "Building another version")
            self.tasks.put((jid, "shaping"))
        elif action == "turn" and job["stage"] == "review_shape" and job["source"] == "file":
            with self.files:
                self._turn(job, data.get("axis", "x"))
        elif action == "approve_shape" and job["stage"] == "review_shape":
            job["edits"] = []
            self._stage(job, "editprep", "Opening the model for editing")
            self.tasks.put((jid, "editprep"))
        elif action == "finish_edit" and job["stage"] == "edit":
            self._stage(job, "measuring", "Measuring the model")
            self.tasks.put((jid, "measuring"))
        elif action == "back_to_edit" and job["stage"] in ("size", "review_final"):
            self._stage(job, "editprep", "Opening the model for editing")
            self.tasks.put((jid, "editprep"))
        elif action == "prepare" and job["stage"] in ("size", "review_final"):
            job["settings"] = {"height_mm": float(data["height_mm"]), "palette": list(data["palette"])[:4]}
            self._stage(job, "preparing", "Making it printable")
            self.tasks.put((jid, "preparing"))
        elif action == "back_to_size" and job["stage"] == "review_final":
            self._stage(job, "size", "")
        elif action == "approve_final" and job["stage"] == "review_final":
            job["name"] = (data.get("name") or job["name"]).strip()[:40]
            self._stage(job, "exporting", "Saving the print files")
            self.tasks.put((jid, "exporting"))
        elif action == "retry" and job["stage"] == "error" and job.get("error_stage"):
            self._stage(job, job["error_stage"], "Trying again")
            self.tasks.put((jid, job["error_stage"]))
        elif action == "rename":
            job["name"] = str(data.get("name", job["name"])).strip()[:40] or job["name"]
            return self.save(job)
        elif action == "make_step" and job["stage"] == "done" and job["source"] != "convert":
            self._stage(job, "stepping", "Making the solid file")
            self.tasks.put((jid, "stepping"))
        elif action == "open_slicer" and job.get("files", {}).get("project"):
            project = self._dir(jid) / job["files"]["project"]
            if CREALITY:
                subprocess.Popen([str(CREALITY), str(project)])
            else:                                   # no Creality Print: open with whatever handles .3mf
                os.startfile(project)
            return job
        elif action == "show_folder":
            if job["source"] == "convert":
                subprocess.Popen(["explorer", str(self._dir(jid) / "solid")])
                return job
            target = self._dir(jid) / job.get("files", {}).get("project", "")
            subprocess.Popen(["explorer", "/select,", str(target)] if target.is_file() else ["explorer", str(self._dir(jid))])
            return job
        elif action == "delete":
            shutil.rmtree(self._dir(jid), ignore_errors=True)
            self.notify({"id": jid, "deleted": True})
            return {"id": jid, "deleted": True}
        else:
            raise ValueError(f"'{action}' is not possible right now")
        return self.save(job)

    # ------------------------------------------------------------------ part editing
    def _base_mesh(self, job):
        """The generated model as arrays (glTF axes), cached per job and model version."""
        d = self._dir(job["id"])
        p = d / f"base_{job['model_glb']}.npz"
        if not p.exists():
            mesh, rgb = meshprep.load_textured(str(d / job["model_glb"]))
            np.savez(p, vertices=np.asarray(mesh.vertices, np.float32), faces=np.asarray(mesh.faces, np.int32), rgb=rgb)
        z = np.load(p)
        return z["vertices"], z["faces"], z["rgb"]

    def _edited(self, job):
        """The model with her edits replayed in order; each edit's triangles are stored beside job.json."""
        v, f, c = self._base_mesh(job)
        d = self._dir(job["id"])
        for e in job.get("edits", []):
            e = dict(e)
            if "faces_file" in e:
                e["faces"] = np.load(d / e["faces_file"])
            v, f, c = editmesh.apply(v, f, c, e)
        return v, f, c

    def _write_edit_view(self, job):
        v, f, c = self._edited(job)
        n = editmesh.to_bins(v, f, c, self._dir(job["id"]))
        job["edit_faces"] = int(n)
        job["edit_version"] = job.get("edit_version", 0) + 1

    def edit(self, jid, data):
        """One edit from the editor: apply it, store it, and refresh the editor's geometry."""
        job = self.load(jid)
        if job["stage"] != "edit":
            raise ValueError("Editing is not open for this model")
        op = data.get("op")
        if op == "undo":
            if job.get("edits"):
                last = job["edits"].pop()
                if "faces_file" in last:
                    (self._dir(jid) / last["faces_file"]).unlink(missing_ok=True)
        elif op == "reset":
            for e in job.get("edits", []):
                if "faces_file" in e:
                    (self._dir(jid) / e["faces_file"]).unlink(missing_ok=True)
            job["edits"] = []
        elif op in ("remove", "keep", "scale", "paint", "cut_below"):
            entry = {"op": op}
            if op != "cut_below":
                faces = np.asarray(data.get("faces") or [], np.int32)
                if len(faces) == 0:
                    raise ValueError("Select a part first")
                name = f"edit_{len(job.get('edits', [])) + 1}_{uuid.uuid4().hex[:6]}.npy"
                np.save(self._dir(jid) / name, faces)
                entry.update(faces_file=name, count=int(len(faces)))
            if op == "scale":
                entry["factor"] = float(np.clip(float(data.get("factor", 1.0)), 0.3, 3.0))
            if op == "paint":
                entry["rgb"] = str(data["rgb"])
            if op == "cut_below":
                entry["frac"] = float(np.clip(float(data.get("frac", 0.0)), 0.0, 0.6))
            job.setdefault("edits", []).append(entry)
        else:
            raise ValueError(f"Unknown edit {op}")
        with self.files:
            self._write_edit_view(job)
        return self.save(job)

    def estimate(self, jid, palette):
        """Live numbers for the size chart: colour shares for this palette at the reference model."""
        ref = self._reference(jid)
        if ref is None:
            return None
        label, share = colours.assign_filaments(ref["faces"], ref["rgb"], ref["areas"], palette, smooth_iters=1)
        return {"share": share}

    # ------------------------------------------------------------------ the step runner
    def _stage(self, job, stage, status):
        job.update(stage=stage, status=status, stage_started=time.time(), eta_s=ETA.get(stage), error=None)
        if stage in ("choose_image", "review_shape", "edit", "size", "review_final", "done", "converted"):
            job["unseen"] = True
        self.save(job)

    def _loop(self):
        """The step runner. It must never die: every failure becomes a visible 'try again' on the job."""
        import traceback
        while True:
            jid, stage = self.tasks.get()
            try:
                job = self.load(jid)
                if job["stage"] != stage:
                    continue
                getattr(self, f"_do_{stage}")(job)
            except FileNotFoundError:
                continue
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                try:
                    job = self.load(jid)
                    job.update(stage="error", status=_friendly(e), error_stage=stage, error=str(e)[:400])
                    self.save(job)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()

    def _do_writing(self, job):
        subject = job["idea"]
        with self.gpu:
            try:
                data = _ask_llm(job["idea"])
                subject, job["name"] = str(data["subject"]), str(data["name"])[:40]
            except Exception:  # noqa: BLE001 - no Ollama / no model: the idea itself still works as a prompt
                pass
        job["subject"] = subject
        job["prompt"] = f"{subject}. {IMAGE_STYLE}"
        self._stage(job, "imagining", "Drawing three options")
        self._do_imagining(job)

    def _do_imagining(self, job):
        out = self._dir(job["id"]) / f"images_{job['attempt']}"

        def progress(ev):
            j = self.load(job["id"])
            j["images"] = [str(Path(f).relative_to(self._dir(job["id"]))).replace("\\", "/") for f in ev["files"]]
            j["status"] = f"Drawing option {min(ev['done'] + 1, ev['total'])} of {ev['total']}" if ev["done"] < ev["total"] else "Done"
            self.save(j)

        with self.gpu:
            r = self.worker.call("image", prompt=job["prompt"], count=3, seed=job["attempt"] * 100, out_dir=str(out),
                                 on_progress=progress)
        job = self.load(job["id"])
        job["images"] = [str(Path(f).relative_to(self._dir(job["id"]))).replace("\\", "/") for f in r["files"]]
        self._stage(job, "choose_image", "Pick the one you like")

    def _views(self, job):
        d = self._dir(job["id"])
        if job["source"] == "photos":
            return [str(d / p) for p in job["photos"]]
        return [str(d / job["chosen_image"])]

    def _do_shaping(self, job):
        d, n = self._dir(job["id"]), job["attempt"]
        views = self._views(job)
        with self.gpu:
            job["status"] = "Building the 3D shape"
            self.save(job)
            shape = self.worker.call("shape", images=views, seed=n, out=str(d / f"shape_{n}.glb"))
            job = self.load(job["id"])
            job["status"] = "Painting the colours"
            self.save(job)
            tex = self.worker.call("texture", mesh=shape["file"], images=views, out=str(d / f"model_{n}.glb"))
        job = self.load(job["id"])
        job["model_glb"] = f"model_{n}.glb"
        mesh, rgb = meshprep.load_textured(tex["file"])
        v = _y_up_to_z_up(np.asarray(mesh.vertices))
        render.render(v, np.asarray(mesh.faces), rgb, "iso", 512).save(d / "thumb.png")
        job["thumb"] = "thumb.png"
        self._stage(job, "review_shape", "Does it look right?")

    def _do_importing(self, job):
        d = self._dir(job["id"])
        imp = importmesh.load(d / "source")
        job = self.load(job["id"])
        info = imp.info
        job["imported"] = info
        span = float(np.ptp(imp.vertices[:, 1])) or 1.0
        job["imported"]["mm_per_unit"] = info["height_mm"] / span
        if 5.0 <= info["height_mm"] <= 290.0:              # a real size in the file: start from it
            job["settings"]["height_mm"] = round(info["height_mm"])
        if info.get("palette"):                            # painted 3MF: its own filaments
            job["palette_hint"] = info["palette"]
        self._set_model(job, imp.vertices, imp.faces, imp.rgb)
        msg = "Is this your model?"
        self._stage(job, "review_shape", msg)

    def _set_model(self, job, v, f, rgb):
        """A new version of the model (glTF axes): the viewer's GLB, the editor's arrays, the thumbnail."""
        d = self._dir(job["id"])
        n = job.get("model_n", 0) + 1
        job["model_n"] = n
        name = f"model_{n}.glb"
        _export_glb(v, f, rgb, d / name, gltf_axes=True)
        np.savez(d / f"base_{name}.npz", vertices=np.asarray(v, np.float32), faces=np.asarray(f, np.int32),
                 rgb=np.asarray(rgb, np.uint8))
        render.render(_y_up_to_z_up(np.asarray(v)), np.asarray(f), rgb, "iso", 512).save(d / "thumb.png")
        job["model_glb"], job["thumb"] = name, "thumb.png"

    def _turn(self, job, axis):
        """Stand an imported model up differently: a quarter turn tipping it forward (x) or sideways (z)."""
        v, f, rgb = self._base_mesh(job)
        a = {"x": [1, 0, 0], "z": [0, 0, 1]}.get(axis, [1, 0, 0])
        import trimesh
        R = trimesh.transformations.rotation_matrix(np.pi / 2, a)[:3, :3]
        v = np.asarray(v, float) @ R.T
        self._set_model(job, v, f, rgb)
        imp = job.get("imported", {})
        k = imp.get("mm_per_unit", 1.0)
        e = np.ptp(v, axis=0) * k
        imp.update(width_mm=round(float(e[0]), 1), height_mm=round(float(e[1]), 1), depth_mm=round(float(e[2]), 1))
        if 5.0 <= imp["height_mm"] <= 290.0:
            job["settings"]["height_mm"] = round(imp["height_mm"])

    def _do_editprep(self, job):
        with self.files:
            self._write_edit_view(job)
        self._stage(job, "edit", "Change parts, or continue")

    def _edited_trimesh(self, job):
        import trimesh
        v, f, c = self._edited(job)
        return trimesh.Trimesh(v, f, process=False), np.asarray(c)

    def _do_measuring(self, job):
        d = self._dir(job["id"])
        self._cache.pop(job["id"], None)            # the model may have been edited since the last measure
        mesh, rgb = self._edited_trimesh(job)
        if job.get("edits"):
            # show her edited model (not the generated one) while measuring and on the size step
            name = f"edited_{job.get('edit_version', 0)}.glb"
            _export_glb(mesh.vertices, mesh.faces, rgb, d / name, gltf_axes=True)
            job = self.load(job["id"])
            job["edited_glb"] = name
            self.save(job)
        else:
            job = self.load(job["id"])
            job.pop("edited_glb", None)
            self.save(job)
        model = meshprep.prepare(mesh, rgb, REFERENCE_HEIGHT_MM, keep_surface=job["source"] == "file",
                                 log=lambda *_: None)
        tm = model.trimesh()
        areas = tm.area_faces
        np.savez_compressed(d / "reference.npz", vertices=model.vertices, faces=model.faces, rgb=model.face_rgb,
                            areas=areas)
        suggested = _suggest_with_painted(job.get("edits", []), model.face_rgb, areas)
        if job.get("palette_hint") and not any(e.get("op") == "paint" for e in job.get("edits", [])):
            # a painted 3MF already says which filaments it wants: keep them, in its own order
            _, share = colours.assign_filaments(model.faces, model.face_rgb, areas, job["palette_hint"],
                                                smooth_iters=0)
            suggested = [(h, round(float(x), 3)) for h, x in zip(job["palette_hint"], share)]
        suggested = _pad_palette(suggested)
        job = self.load(job["id"])
        job["reference"] = {"height_mm": REFERENCE_HEIGHT_MM, "width_mm": model.report["width_mm"],
                            "depth_mm": model.report["depth_mm"], "volume_cm3": model.report["volume_cm3"],
                            "area_cm2": round(float(areas.sum()) / 100.0, 1)}
        job["suggested_palette"] = suggested
        job["settings"]["palette"] = [h for h, _ in suggested]
        self._stage(job, "size", "Choose the size and colours")

    def _reference(self, jid):
        if jid not in self._cache:
            p = self._dir(jid) / "reference.npz"
            if not p.exists():
                return None
            z = np.load(p)
            self._cache[jid] = {k: z[k] for k in ("vertices", "faces", "rgb", "areas")}
        return self._cache[jid]

    def _do_preparing(self, job):
        d = self._dir(job["id"])
        s = job["settings"]
        mesh, rgb = self._edited_trimesh(job)
        model = meshprep.prepare(mesh, rgb, s["height_mm"], keep_surface=job["source"] == "file",
                                 log=lambda *_: None)
        tm = model.trimesh()
        label, share = colours.assign_filaments(model.faces, model.face_rgb, tm.area_faces, s["palette"])
        pal = np.array([colours.hex_to_rgb(h) for h in s["palette"]])
        render.turnaround(model.vertices, model.faces, pal[label], size=420).save(d / "final_views.png")
        _export_glb(model.vertices, model.faces, pal[label], d / "final.glb")
        tm.export(d / "print.stl")
        np.save(d / "filament_per_face.npy", label.astype(np.uint8))
        job = self.load(job["id"])
        job["final"] = dict(model.report, share=share, grams=_grams(tm, share))
        job["final_glb"], job["final_views"] = "final.glb", "final_views.png"
        self._stage(job, "review_final", "Ready to check")

    def _do_converting(self, job):
        import tostep
        import stepcheck
        d = self._dir(job["id"])
        src, out = d / "source", d / "solid"
        out.mkdir(exist_ok=True)
        for z in list(src.glob("*.zip")):
            importmesh._unzip(z, src / z.stem)
        files = sorted((p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in importmesh.MODEL_EXT),
                       key=lambda p: str(p).lower())
        job = self.load(job["id"])
        prev = {c["file"]: c for c in job.get("conversions", [])}
        job["conversions"] = [prev.get(p.name, {"file": p.name, "status": "waiting"}) for p in files]
        job["eta_s"] = 30 * max(1, sum(c["status"] != "done" for c in job["conversions"]))
        self.save(job)
        used = set()
        for i, p in enumerate(files):
            job = self.load(job["id"])
            c = job["conversions"][i]
            if c["status"] == "done":
                continue
            stem = re.sub(r"[^A-Za-z0-9 _()-]+", "_", p.stem).strip() or "part"
            while stem.lower() in used:
                stem += "_2"
            used.add(stem.lower())
            c.update(status="working")
            job["status"] = f"Converting {i + 1} of {len(files)}: {p.name}"
            self.save(job)
            try:
                imp = importmesh.load_file(p, keep_axes=True, max_faces=None)
                step = out / f"{stem}.step"
                rep = tostep.convert(imp.vertices, imp.faces, step, name=stem, log=lambda *_: None)
                info, shape = stepcheck.check(step)
                stepcheck.preview(shape, out / f"{stem}.png")
                c.update(status="done", step=f"solid/{stem}.step", preview=f"solid/{stem}.png", report=rep,
                         check=info)
            except (importmesh.FileProblem, tostep.ConvertProblem) as e:
                c.update(status="failed", message=str(e))
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                c.update(status="failed", message="This file couldn't be converted.", error=str(e)[:300])
            job = self.load(job["id"])
            job["conversions"][i] = c
            self.save(job)
        job = self.load(job["id"])
        ok = sum(c["status"] == "done" for c in job["conversions"])
        if ok == 0:
            raise importmesh.FileProblem("None of the files could be converted. " +
                                         "; ".join(f"{c['file']}: {c.get('message', '')}" for c in job["conversions"]))
        if job["conversions"] and job["conversions"][0].get("preview"):
            job["thumb"] = job["conversions"][0]["preview"]
        self._stage(job, "converted", f"{ok} solid file{'s' if ok != 1 else ''} ready")

    def _do_stepping(self, job):
        """A solid (STEP) copy of a finished print model, for CAD."""
        import trimesh
        import tostep
        d = self._dir(job["id"])
        tm = trimesh.load(d / "print.stl")
        safe = re.sub(r"[^A-Za-z0-9 _-]+", "", job["name"]).strip() or "model"
        name = f"{job['number']} {safe}.step"
        rep = tostep.convert(tm.vertices, tm.faces, d / name, name=safe, log=lambda *_: None)
        job = self.load(job["id"])
        job.setdefault("files", {})["step"] = name
        job["step_report"] = rep
        self._stage(job, "done", "Ready to print")

    def _do_exporting(self, job):
        d = self._dir(job["id"])
        import trimesh
        tm = trimesh.load(d / "print.stl")
        label = np.load(d / "filament_per_face.npy")
        thumb = io.BytesIO()
        from PIL import Image
        Image.open(d / "final_views.png").crop((0, 0, 420, 420)).resize((256, 256)).save(thumb, "PNG")
        safe = re.sub(r"[^A-Za-z0-9 _-]+", "", job["name"]).strip() or "model"
        name = f"{job['number']} {safe}.3mf"
        export3mf.write_creality_project(d / name, tm.vertices, tm.faces, label, job["settings"]["palette"],
                                         job["name"], thumb.getvalue())
        job = self.load(job["id"])
        job["files"] = {"project": name, "stl": "print.stl"}
        self._stage(job, "done", "Ready to print")


def _y_up_to_z_up(v):
    """glTF (x, y, z) with Y up -> printer (x, -z, y) with Z up: the same +90° turn about X as meshprep."""
    return v @ np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float).T


def _export_glb(vertices, faces, face_rgb, path, gltf_axes=False):
    import trimesh
    v = np.asarray(vertices, float)
    if not gltf_axes:
        # printer (x, y, z) with Z up -> glTF (x, z, -y) with Y up; the inverse of meshprep's +90° turn about X
        v = v @ np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float).T
    v = v - v.mean(axis=0)
    m = trimesh.Trimesh(v, faces, process=False)
    m.unmerge_vertices()
    # glTF vertex colours are linear light; screen (sRGB) colours stored as-is look washed out in the viewer
    linear = np.round(((np.asarray(face_rgb, float) / 255.0) ** 2.2) * 255.0)
    m.visual = trimesh.visual.ColorVisuals(m, face_colors=np.c_[linear, np.full(len(linear), 255)].astype(np.uint8))
    m.export(path)


def _pad_palette(suggested, k=4):
    """Always four slots (a one-colour STL suggests one colour): fill up with common filaments."""
    out = list(suggested)[:k]
    have = {h.upper() for h, _ in out}
    for h in DEFAULT_PALETTE:
        if len(out) >= k:
            break
        if h.upper() not in have:
            out.append((h, 0.0))
    return out


def _suggest_with_painted(edits, face_rgb, areas, k=4):
    """A colour she painted on purpose always gets a filament slot, however small the part. The other
    slots are suggested from the parts she didn't paint, so the painted colour doesn't push out a
    colour the model needs (the dragon's belly). Later paints win when there are more than four."""
    painted = []
    for e in reversed(edits):
        h = e.get("rgb", "").upper() if e.get("op") == "paint" else ""
        if h and h not in painted:
            painted.append(h)
    painted = painted[:k]
    if not painted:
        return colours.suggest_palette(face_rgb, areas, k=k)
    rgb = np.asarray(face_rgb, int)
    total = float(areas.sum()) or 1.0
    is_painted = np.zeros(len(rgb), bool)
    entries = []
    for h in painted:
        m = np.abs(rgb - np.array(colours.hex_to_rgb(h), int)).max(axis=1) <= 6
        is_painted |= m
        entries.append((h, round(float(areas[m].sum()) / total, 3)))
    rest = k - len(painted)
    if rest and (~is_painted).any():
        entries += colours.suggest_palette(face_rgb[~is_painted], areas[~is_painted], k=rest)
    return sorted(entries, key=lambda s: -s[1])


def _grams(tm, share):
    """Rough filament per slot: walls (~1.2 mm) all round plus 15% infill, in PLA."""
    area_cm2 = float(tm.area) / 100.0
    vol = float(tm.volume) / 1000.0 if tm.is_watertight else 0.0
    shell = min(vol, area_cm2 * WALL_MM / 10.0)
    total = (shell + INFILL * max(0.0, vol - shell)) * FILAMENT_DENSITY * GRAMS_CALIBRATION
    return [round(total * s, 1) for s in share]


def _friendly(e):
    if isinstance(e, importmesh.FileProblem):
        return str(e)
    text = str(e).lower()
    if "out of memory" in text or "cuda" in text:
        return "The computer ran out of graphics memory. Close other programs and try again."
    if "engine" in text:
        return str(e)
    return "Something went wrong in this step. Try again; if it keeps happening, try another photo or idea."

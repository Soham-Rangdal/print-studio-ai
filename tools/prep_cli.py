"""Phase 2 chain: textured GLB -> printable solid -> filament colours -> previews + report.

    .venv\\Scripts\\python tools\\prep_cli.py model.glb --height 120 --out jobs\\test
    ... --palette "#3FA34D,#F2D16B,#E8702A,#F5F5F0"     her loaded filaments (default: suggested from the model)
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colours  # noqa: E402
import meshprep  # noqa: E402
import render  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--height", type=float, required=True, help="model height in mm")
    ap.add_argument("--palette", default="", help="comma-separated hex colours of the loaded filaments")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("Loading and reading texture colours ...")
    mesh, rgb = meshprep.load_textured(a.glb)
    print(f"  {len(mesh.faces)} faces")
    print("Making it printable ...")
    model = meshprep.prepare(mesh, rgb, a.height)
    tm = model.trimesh()
    areas = tm.area_faces

    suggested = colours.suggest_palette(model.face_rgb, areas, k=4)
    palette = [c.strip() for c in a.palette.split(",") if c.strip()] or [h for h, _ in suggested]
    print("Mapping colours to filaments", palette, "...")
    label, share = colours.assign_filaments(model.faces, model.face_rgb, areas, palette)

    print("Rendering previews ...")
    render.turnaround(model.vertices, model.faces, model.face_rgb).save(out / "preview_texture.png")
    pal_rgb = np.array([colours.hex_to_rgb(h) for h in palette])
    render.turnaround(model.vertices, model.faces, pal_rgb[label]).save(out / "preview_filaments.png")

    tm.export(out / "print.stl")
    np.save(out / "filament_per_face.npy", label.astype(np.uint8))
    report = dict(model.report, suggested_palette=suggested, palette=palette, filament_share=share,
                  seconds=round(time.time() - t0, 1))
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

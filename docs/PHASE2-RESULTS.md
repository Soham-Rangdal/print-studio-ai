# Phase 2 results: mesh repair, printability checks, colour mapping

Code (all CPU, `print-agent\.venv`):
- `tools\meshprep.py`: load GLB + per-triangle texture colours; orient (glTF Y-up → printer Z-up, front −Y);
  scale to height; drop fragments; voxelise (~0.15–0.5 mm, finer than the nozzle); fill the inside
  (seal holes 2 → 4 → 8 → 14 mm until solid); flat bottom; separate-piece check; thin-part check
  (local thickness < 0.8 mm unprintable, < 1.2 mm fragile); marching cubes; Taubin smoothing;
  manifold3d simplify (always watertight); colours carried to the new surface.
- `tools\colours.py`: suggested 4-filament palette (area-weighted k-means in Lab); nearest-filament per
  triangle; majority smoothing; islands < 6 mm² merged.
- `tools\render.py`: CPU preview renderer (turnarounds, texture or filament colours).
- `tools\prep_cli.py`: the chain → `print.stl`, `filament_per_face.npy`, previews, `report.json`.

| Test | Result |
|---|---|
| TRELLIS.2 dragon, 120 mm | 1,263 fragments removed; watertight; **235.9 cm³ solid**; 164k faces; flat bottom 605 mm²; no warnings; 68–76 s |
| Same, 30 mm | Watertight, 3.8 cm³ (consistent with 4× scale); **thin parts flagged** (wings, claws) as expected |
| Pixal3D dragon (bad views), 120 mm, palette green/yellow/orange/white | 12,826 fragments removed; watertight; 185.7 cm³; claws white; **warnings: 2 separate pieces, small bed contact (66 mm²)**, both true |

## Bugs found and fixed during testing

1. Simplifier (fast_simplification) left 6 non-manifold edges → replaced by manifold3d `simplify` (always valid).
2. **Model came out hollow** (26.7 cm³ shell): holes defeated closing + fill → new fill: grow surface, flood the
   outside from the border, grow back; retry with bigger seals if still a shell. Volume check catches it.
3. Thin check flagged 88% (artefact of the hollow model + opening method) → local-thickness method.
4. Hole sealing hit the grid border at small sizes (228 open edges) → padding sized to the largest seal.
5. Contour ripples from the voxel grid → Taubin smoothing.

## Known limits

- Bad input views (Janus: face on the back) can't be repaired: use Pixal3D MV only with real 4-side photos.
- Fine details smaller than the voxel (~0.3 mm at 12 cm) are smoothed away: fine for a 0.4 mm nozzle.
- The 4-colour reduction drops small colour areas (e.g. white claws) unless that filament is loaded.
- Colour detail on the surface is per triangle; the 3MF writer (phase 3) will carry it as paint data.

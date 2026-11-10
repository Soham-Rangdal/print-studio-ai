# Open a 3D file: results (2026-11-10)

A third way in, beside "Describe it" and "Use photos". She drops or picks a 3D file she already has
(downloaded, or from another app). From there it continues like any model: check, edit, size and colours,
print checks, Creality Print file.

## Formats

| File | Read as | Colours |
|---|---|---|
| 3MF (Creality Print, Bambu Studio, Orca, MakerWorld, PrusaSlicer) | own reader: objects in separate files, components, transforms, units | **painted filaments kept** (`paint_color` / `mmu_segmentation` codes decoded, project `filament_colour`), material colours, per-object filament |
| STL | Z up, mm | none → white |
| OBJ (+ .mtl + texture, or all in a .zip) | Y up (Blender default), mm | texture / material colours |
| GLB / GLTF (+ .bin) | Y up, metres | texture / vertex colours |
| PLY, OFF | Z up, mm | vertex / face colours |
| ZIP | unpacked safely (no paths outside, 600 MB cap), the best model file inside is used | |

More than 400k triangles: lightened to 400k (colours carried over) so editing stays quick.

## What she sees

- **Step C, "Is this your model?"**: format, triangles, the size saved in the file, what happens to the colours.
  "Tip forward" and "Roll sideways" buttons turn it a quarter turn at a time for files that come in lying down.
- The size saved in the file (5–290 mm) becomes the starting height in step E.
- A painted 3MF's filaments become her 4 slots, in their own order.
- **Exact surface kept**: a file that is already a closed solid and stands flat is not rebuilt from voxels
  (sharp edges and fine detail stay) and nothing is cut off its bottom. The print checks still run. After
  edits that open it (remove, cut), it is rebuilt as usual.

Files: `tools/importmesh.py`, `app/pipeline.py` (`create_from_file`, `_do_importing`, `_turn`, `_set_model`),
`tools/meshprep.py` (`keep_surface`), `app/server.py` (`/api/jobs/file`), `app/static/app.js` (`renderImported`).

## Tested

| File | Result |
|---|---|
| PS-001's painted 3MF (round trip) | 4 filaments back exactly; height 11.6 cm from the file; surface kept (172,408 triangles, 0 mm cut, watertight); exported again |
| Cow STL (no colours) | 1 colour + 3 filler slots; height 9.7 cm from the file |
| Dragon OBJ + .mtl + texture in a .zip | upright, texture colours |
| Dragon GLB | upright, texture colours |
| Coloured PLY | colour kept |
| Broken STL | "The file has no surfaces in it" on the error step |
| Turn ×4 | back where it started; sizes follow the turn |

Also fixed: the print checks reported the height before the bottom cut (12.0 cm for an 11.6 cm print); they
now report the real printed size.

## Known limits

- STEP / FBX / Blender files aren't read (save them as STL, OBJ or GLB first).
- OBJ files saved Z-up come in lying down: one "Tip forward" fixes them.
- Bambu "colour by object" projects (no painting, different filament per part) read the per-object filament
  only from the main model's settings; nested parts fall back to their parent's filament.
- Screens checked through the page itself (the browser pane was hidden), not by eye.

# Mesh → solid body (STEP): results (2026-11-10)

Meshes (STL, 3MF, OBJ, GLB, PLY, OFF, or a .zip of several) become STEP files: one solid body that Fusion,
SolidWorks, FreeCAD and Onshape open for sketching, extruding, cutting and editing faces.

## Where she finds it

- **Start → Open a 3D file → "Convert to solid (STEP)"**: drop any number of meshes (up to 60). Each becomes
  `<name>.step` with a picture of the result (flat faces blue, cylinders orange). "Show the STEP files"
  opens the folder.
- **Print file step → "Also save a solid (STEP)"**: a STEP copy of a model the app made.

## How it works (`tools/tostep.py`, OpenCascade via `cadquery-ocp`)

1. Triangles on the same plane → one **planar face**, holes included.
2. Strips of a tessellated hole, boss, slot end or rounded edge → one **true cylinder** (axis and radius
   fitted), with **true circles / arcs** where it meets the planes.
3. Everything else stays **small flat faces**: still one closed solid.
4. Faces are sewn, made into a solid, merged and fixed, and then checked: a valid B-rep, a solid body (not
   just a shell), and the same volume as the mesh. If the exact rebuild fails the check, it falls back to
   planes only, then plain triangles. Each fallback is reported.

Organic meshes over 12,000 regions are lightened to about 12,000 triangles first. Above that, CAD programs
crawl and the conversion takes minutes.

## Tested (each file read back with a separate STEP reader)

| Mesh | Result |
|---|---|
| Bracket: plate, 4 holes, boss with bore, rounded slot (2,028 triangles) | **17 faces: 9 planes + 8 cylinders**, 1 valid solid, volume 31.396 vs 31.397 cm³, 0.1 s |
| Rounded-corner plate, coarse 16-segment hole, hole through a slanted face (548 triangles) | 4 corner fillets + the coarse hole as true cylinders; the hole through the slant stays faceted (its edge is an ellipse); 1 valid solid |
| Dragon print.stl (172,408 triangles) | lightened to 12,009 → 11,589 flat faces, 1 valid solid, volume within 0.2 %, 30 s, 30 MB |
| Broken STL | "The file has no surfaces in it", the other files still convert |
| App: batch of 3 files, and "Also save a solid" on PS-001 | both work; files listed with face counts |

## Limits

- Only planes and cylinders are rebuilt exactly. Spheres, cones, tori (corner blends), free-form NURBS and
  holes meeting a slanted face stay faceted.
- Organic shapes become a faceted solid: you can cut, join, shell and add features in CAD, but you can't
  reshape it like a sketch. No converter can recover a design history that the mesh never had.
- It hasn't been opened in Fusion itself (not installed here). It was checked with OpenCascade's reader,
  the same kernel FreeCAD uses.

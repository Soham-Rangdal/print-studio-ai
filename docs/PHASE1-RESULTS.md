# Phase 1 results: every model runs on the laptop (RTX 3070 8 GB, 32 GB RAM)

Test object: a chunky toy dragon made from text. Raw data: `tests\smoke\results.json` (with model
release) and `tests\smoke\results_no_release.json` (first run, without). Times include model loading.

| Stage | Model | Time | Peak VRAM | Result |
|---|---|---|---|---|
| Text → image (1024²) | Z-Image Turbo | **26 s** | 1.8 GB | Excellent printable toy look |
| 3 more views | Flux 3 Klein | 169 s | 1.6 GB | Right side good; **back and left were copies of the front** |
| 1 image → shape | TRELLIS.2 Shape | **126 s** | 2.5 GB | Faithful shape; 100k faces, not watertight, 32 pieces |
| 4 views → shape | Pixal3D Multi-View | 207 s* | 2.7 GB | Wrong sides (bad views in); 500k faces, 42 pieces |
| Colours, 4 views | Pixal3D Texture | 127 s* | 5.5 GB | Right palette (render check pending) |
| Colours, 1 view | TRELLIS.2 Texture | **66 s** | 3.8 GB | Right palette (render check pending) |
| Fine detail (512) | Hi3D | **57 s** | 2.3 GB | Ran fine |
| Part split | GeoSAM2 | 167 s* | 6.5 GB | 893 parts, mostly fragments: not useful for colours |

\* measured before the release fix, when RAM was swapping; probably faster now.

## What we learned

1. **VRAM is fine.** Highest peak 6.5 GB (GeoSAM2), 5.5 GB for Pixal3D Texture. Everything fits in 8 GB.
2. **RAM was the real limit.** Without releasing models between stages WanGP kept earlier models
   cached; free RAM fell to 0.1 GB and Windows swapped. **Fix (now proven):** `session.close()` +
   `wgp.release_extension_offloadobjs()` after every stage → ~15 GB free again, and swap-bound stages ran
   up to 2.5× faster (Hi3D 145 s → 57 s).
3. **"Shared GPU memory" in the counters is mostly mmgp's pinned RAM**, not a spill. Spills are detected by
   slowdowns and RAM pressure instead.
4. **Multi-view from one generated image is unreliable** (Flux 3 Klein copied the front for back/left).
   Text route → TRELLIS.2 (one image). Pixal3D Multi-View is for **real photos** of 4 sides. If extra
   views are generated later: mirror the side view for the other side, and prompt the back from a side view.
5. **Raw meshes are never printable as-is** (holes, dozens of loose pieces) → the phase 2 repair stage is essential.
6. **SolidCraft previews show shape only, not textures** → phase 2 adds a small colour-preview renderer.
7. **GeoSAM2 is optional.** Colours come from the texture → filament mapping.

## Expected time per object (GPU stages, with release)

- **From text:** image 26 s + TRELLIS.2 shape ~126 s + texture ~66 s (+ Hi3D ~57 s) ≈ **4–5 min**
- **From 4 photos:** Pixal3D shape + texture ≈ **5–6 min** (to re-measure with release)
- Plus gemma swaps, repair, colour mapping, SolidCraft and export: estimated **8–12 min in total**.

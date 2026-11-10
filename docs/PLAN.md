# Print Agent: photo or idea → multicolour 3D print (Creality K2 Pro + CFS)

A chatbot for my sister: she uploads 1–4 photos or describes an object ("a dragon"), approves a 3D
preview, says how tall it should be and which 4 filaments are loaded, and gets a file that opens in
Creality Print with the colours already assigned to her CFS slots.

## Fixed facts

| Item | Value |
|---|---|
| Printer | Creality K2 Pro, 300 × 300 × 300 mm → models capped at 290 mm per side |
| Colours | 1 CFS = up to 4 filaments (PLA / PETG; no TPU through the CFS) |
| Slicer | Creality Print 7.3 (OrcaSlicer-based), `C:\Program Files\Creality\Creality Print 7.3\` |
| Laptop | RTX 3070 8 GB, 32 GB RAM, Windows 11 |
| LLM | gemma4 12B (local GGUF from Ollama's folder, with vision), via llama.cpp |
| 3D / image models | WanGP (all downloaded, int8): Z-Image Turbo, Flux 3 Klein, Pixal3D MV + Texture, TRELLIS.2 Shape + Texture, Hi3D, GeoSAM2, BiRefNet |
| CAD | SolidCraft (`solidcraft-cli`: JSON scripts, snapshots, 3MF/STL export, MCP) |
| Mesh code | `print-agent\.venv`: trimesh, manifold3d, scikit-learn, numpy, scipy |

## The conversation she has

1. **"What do you want to print?"** She uploads 1–4 photos, or types an idea.
2. **Idea → image.** The agent rewrites her idea into a 3D-friendly, printable prompt (one whole object, plain
   background, even light, chunky toy style, thick parts), shows 2–4 images, she picks one.
   Optionally it makes side and back views from the chosen image, so the 4-view model can be used.
3. **Photo check.** The agent looks at the photos (gemma vision): one object, fully in frame, sharp,
   which view is front/side/back. If one is unusable it asks for a retake.
4. **3D model.** A few minutes. Then a turnaround preview: "Looks good?" → yes / try again (new seed).
5. **"How tall, in cm?"** and **"Which 4 colours are loaded in your CFS?"** (pick from a colour list).
   The agent warns if it won't fit or if thin parts (wings, spikes, tails) get too thin to print.
6. **Optional extras:** flat base, name embossed on the base.
7. **Final preview** with her real filament colours → approve.
8. **Files.** A Creality Print project (opens with colours and CFS slots set), plus STL and an editable
   SolidCraft file. One button opens it in Creality Print, where she adds supports and prints.

## Pipeline stages

| # | Stage | Tool | Runs on | Output |
|---|---|---|---|---|
| 1 | Intake: parse what she wants into structured fields | gemma (JSON-constrained) | GPU | `request.json` |
| 2 | Text → image (2–4 candidates) | Z-Image Turbo | GPU | `images/*.png` |
| 2b | Extra views from one image (optional) | Flux 3 Klein (reference editing) | GPU | `views/front,right,back,left.png` |
| 3 | Photo check and view labelling | gemma vision | GPU | ok / retake message |
| 4 | Background removal | BiRefNet (inside WanGP) | GPU/CPU | cut-out images |
| 5 | 3D shape: 4 views → Pixal3D Multi-View; 1 view → TRELLIS.2 | WanGP | GPU | `shape.glb` |
| 6 | Fine detail (optional, off by default: slow) | Hi3D 512/1024 | GPU | `shape_hd.glb` |
| 7 | Colours: Pixal3D Texture (uses all views) or TRELLIS.2 Texture | WanGP | GPU | `textured.glb` |
| 8 | Preview turnaround + approval | SolidCraft snapshot / 3D viewer | CPU | `preview/*.png` |
| 9 | Scale to her height, fit check (≤ 290 mm), thin-part check | trimesh | CPU | numbers + warnings |
| 10 | Make printable: weld, fill holes, drop loose bits, make manifold, decimate, flat bottom | trimesh + manifold3d | CPU | `print.stl` |
| 11 | Colour mapping: texture colour per triangle → nearest of her 4 filaments (in Lab colour space), smoothing, remove tiny islands | numpy + scikit-learn | CPU | filament number per triangle |
| 12 | Base + name (optional), print face, previews in her filament colours, editable design | SolidCraft (`solidcraft-cli run`) | CPU | `base.stl`, `design.sc`, `final/*.png` |
| 13 | Export the Creality Print project: one solid object, triangles **painted** with filament 1–4, her printer and filament colours from the template | own 3MF writer + `templates\k2pro_template.3mf` | CPU | `model.3mf` |
| 14 | Open in Creality Print | `CrealityPrint.exe model.3mf` | — | — |

### Key design decisions

- **Colour by painting, not by cutting.** Cutting the surface into colour pieces gives open shells that
  can't be printed. Instead the 3MF keeps **one solid mesh** and stores a filament number on each
  triangle (OrcaSlicer's "colour painting" format). Creality Print then builds the colour volumes
  itself. The exact encoding is taken from a project saved by her Creality Print (the template).
- **Fixed workflow, not a free-roaming agent.** The steps are a LangGraph state machine. Gemma is used
  where judgement is needed (understanding her, writing image prompts, checking photos, explaining
  problems); geometry, scaling and file writing are plain code, because they must be exact.
- **One model on the GPU at a time.** Gemma (~7.4 GB) and the WanGP models can't share 8 GB.
  - WanGP runs in a **separate GPU worker process**.
  - Before a GPU job the agent unloads gemma; it reloads it afterwards (~10–20 s).
  - The worker can be restarted if CUDA memory gets fragmented.
- **Every request gets its own job folder** (`jobs\<date>-<name>\`). Each stage writes its result
  there, so a failed or rejected step reruns alone and nothing is recomputed.
- **She approves three times:** image, 3D shape, final colours. Nothing is exported without a yes.

## Memory management

Budget: 8 GB VRAM (one tenant at a time), ~24 GB usable RAM (of 32), shared GPU memory avoided.

1. **GPU residency manager.** GPU states: chat (gemma) / GPU job (WanGP worker) / idle, guarded by a
   lock. Before a GPU job the agent closes gemma (frees its VRAM); afterwards gemma reloads (~5–10 s).
2. **WanGP streams weights from RAM** (mmgp profile 4), int8 weights.
3. **Gemma: GPU layers + CPU layers, q8 KV cache, 12k context.** The vision projector needs VRAM too,
   so photo checks use fewer GPU layers (measured in phase 1).
4. **One WanGP model in RAM at a time**; stages are ordered and batched to minimise model switches.
5. **Gemma is memory-mapped** (use_mmap on, no mlock) so Windows can drop its pages when a big model
   needs RAM. Worst case ≈ 7.4 (gemma) + 11–12 (Z-Image / Flux + text encoder) + 1–2 (mesh) + 6–8 (OS).
6. **The GPU worker is a separate process**: killed and restarted on CUDA errors or fragmentation.
7. **Budget check + retry ladder** per stage (record the rung that worked):
   Z-Image 1024² → 768²; Pixal3D MV 1536 → 1024; textures 4096 → 2048 → 1024; Hi3D 1024 → 512 → skip;
   faces 500k → 300k → 150k; gemma GPU layers 38 → fewer.
- **Spill detection:** log peak VRAM / shared / RAM per stage. Optional NVIDIA setting "Prefer No
  Sysmem Fallback" for WanGP's Python turns the silent slowdown into a catchable out-of-memory error.
- SolidCraft snapshots only when the worker is idle (or CPU renderer); Creality Print opens last.
- Every stage writes to the job folder, so a crash or "try again" never recomputes finished stages.

## Folder layout

```
D:\video-studio\print-agent\
  app.py                 web chat for her (Gradio: chat, photo upload, 3D viewer, download buttons)
  agent\graph.py         LangGraph state machine (the stages above)
  agent\llm.py           gemma loader (reuses scriptwriter-agent's ollama_models.py) + load/unload
  agent\prompts.py       intake, image-prompt writer, photo checker
  worker\gpu_worker.py   WanGP session in its own process: image, shape, texture, refine jobs
  tools\printprep.py     scaling, repair, manifold, flat bottom, thin-part check
  tools\colours.py       texture → filament mapping, smoothing
  tools\solidcraft.py    base/name, previews, .sc file via solidcraft-cli
  tools\export3mf.py     Creality Print project writer (from the template)
  templates\             k2pro_template.3mf (saved from her Creality Print)
  jobs\                  one folder per print request
  tests\                 test images and expected results
```

## Build order (each phase ends with a test)

| Phase | What | Done when |
|---|---|---|
| 1 | **GPU smoke tests:** run each WanGP model once on the laptop through the worker (image, Pixal3D MV, TRELLIS.2, textures, Hi3D) | Each fits in 8 GB; real times measured. Biggest risk, so first |
| 2 | **Mesh tools:** print prep, scaling, thin-part check, colour mapping | A generated model becomes a watertight, scaled mesh with a filament number per triangle |
| 3 | **3MF export:** save the template from her Creality Print, decode its paint format, write projects | A test file opens in Creality Print with 4 colours on the right CFS slots |
| 4 | **SolidCraft:** base, name, previews, .sc file | Previews look right; base and name print |
| 5 | **Agent graph** run from the command line, end to end | Photo or text in → 3MF out, with the 3 approvals |
| 6 | **Web app** for her | She can use it from her phone or laptop on the home Wi-Fi |
| 7 | **10-object test set** (toys, figurine, dragon from text, a household object), tune defaults | Most print first time; known failure cases written down |

## Known risks

- **8 GB may be too little** for some stages (Hi3D 1024, textures). Fallbacks: lower resolution,
  skip Hi3D, or run that stage on RunPod.
- **Colour detail is limited to 4 filaments.** Fine paint (eyes, small text) turns blocky or disappears.
- **Back sides are invented** from one photo; four photos are much better.
- **Thin parts** (wings, spikes) may need thickening or a sturdier "toy" style; the agent warns but
  cannot fix every case.
- **Speed:** probably 10–25 minutes per object on this laptop (to be measured in phase 1).
- **SUPRA-Tex is non-commercial.** It isn't used; avoid it if she ever sells prints.

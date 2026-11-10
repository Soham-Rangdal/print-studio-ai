# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Desktop window on Windows: a local Python backend (FastAPI, in `print-agent\.venv`) serving a web UI
(static HTML/CSS/JS, no build step) inside a native window (pywebview, Edge WebView2), started from a
desktop shortcut. Chosen by the user ("Desktop window"); framework choice delegated: plain HTML/CSS/JS
because the app runs offline on one machine and needs no build tooling.

## Users

One person: the owner's sister, who owns a Creality K2 Pro with one CFS (4 filament slots) and wants to
print her own models. She is not a 3D designer and does not use 3D or AI tools. She uses the app on her
brother's Windows laptop (RTX 3070 8 GB), at home, for a few objects at a time.

## Product Purpose

Print Studio turns a photo (1–4 angles of an object) or a typed idea ("a dragon") into a multicolour
model that is ready to print on her K2 Pro: it makes or uses the image, builds the 3D model, repairs it,
sizes it in centimetres, maps its colours to the 4 filaments she has loaded, and hands a file to
Creality Print. Success: she goes from an idea or photo to a print she is happy with, without help.

## Positioning

Everything runs locally on this laptop with models already downloaded (no accounts, no cloud, no
per-model cost), and the whole path is tuned to one printer: its build size, its 4-colour CFS and its
slicer. It checks printability (size, thin parts, loose pieces, bed contact) before she wastes filament.

## Operating Context

- Steps are slow (an image ~30 s, a 3D model ~2–5 min, repair ~1 min; whole object ~8–12 min), so
  progress and waiting must be clear and calm, and she may leave and come back.
- One GPU: only one heavy step runs at a time.
- Output opens in Creality Print 7.3, where she adds supports and sends the print.
- She approves three times: the image, the 3D shape, the final colours.

## Capabilities and Constraints

- Inputs: 1 photo, 4 photos (front, right, back, left), or a text idea.
- Models (local, WanGP): Z-Image Turbo (text → image), TRELLIS.2 (1 image → 3D) and Pixal3D Multi-View
  (4 photos → 3D), with their texturers; Hi3D refiner optional. Gemma 12B (local) writes image prompts.
- Printer limits: 300 mm build volume (models capped at 290 mm); 4 filaments; PLA/PETG through the CFS.
- Warnings the app must surface: too big, thin parts (< 0.8 mm won't print, < 1.2 mm fragile),
  separate pieces, small bed contact.
- Undecided: exact Creality Print colour-project format (to be confirmed against her saved template);
  base/name embossing (SolidCraft) not built yet.

## Brand Commitments

- Name: **Print Studio**.
- Voice: simple, everyday English. No technical words (mesh, voxel, manifold, texture, inference).
  Say "model", "shape", "colours", "too thin to print".

## Evidence on Hand

- Real test output: `tests\smoke\` (text-made dragon, 3D shapes) and `jobs\test_*` (repaired models,
  previews). No user testimonials or print photos exist; do not invent any.

## Product Principles

1. **Her choices, not the machine's.** Every slow step ends with something to look at and a clear yes /
   try again; nothing is exported without her approval.
2. **Tell the truth about the print.** Warn before filament is wasted, in plain words, with what to do.
3. **Calm while waiting.** Long steps show what is happening and how long is left; nothing looks frozen.
4. **One path, few decisions.** Sensible defaults (size, colours suggested from the model); advanced
   options only when needed.

## Accessibility & Inclusion

Plain language throughout. Readable sizes on a laptop screen; full keyboard use; respects reduced motion.

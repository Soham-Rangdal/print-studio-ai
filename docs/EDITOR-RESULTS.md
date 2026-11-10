# Part editor: results (2026-11-10)

New step **D Edit**, between "Does it look right?" and "Size & colours". She changes parts of the generated
model before it is made printable; holes left by removing parts are closed later by the solid rebuild.

## What she can do

| Tool | How |
|---|---|
| Select a colour area | Click a part: everything of that colour that touches it is selected |
| Draw around | Pen: draw a loop with the left button (right button turns the model). "Front only" takes what she can see; "Straight through" also takes the back. Alt/Ctrl takes away from the selection |
| Grow / Shrink / Clear | Adjust the selection one ring of triangles at a time |
| Remove / Keep only this | Delete the part, or delete everything else |
| Resize | 50–200 %, around where the part attaches (spikes grow out of the body, not away from it) |
| Paint | 16 swatches; a painted colour always gets one of the 4 filament slots |
| Cut from the bottom | Slider with a live red plane; removes a base |
| Undo / Start over | Edits are a list replayed on the original model, so undo is exact |

Files: `tools/editmesh.py` (edits), `app/static/editor.js` (three.js viewer, GPU picking, lasso),
`app/pipeline.py` (`edit`, `_edited`, `_suggest_with_painted`), `app/static/app.js` (panel).

## Verified on PS-001 (dragon), through to the print file

- Cut 9 % off the bottom → base gone; it stands on its feet (3.7 mm flattened, 719 mm² on the bed).
- One spike resized to 160 %; left horn painted white with the pen.
- Size step shows the edited model (`edited_N.glb`); palette suggested: green, red, mustard, **white**.
- Print checks re-ran on the edited model; 3MF saved with all 4 filaments painted.

## Bugs found and fixed

1. **Generated models are double-skinned**: right under the visible surface is an inward-facing layer with junk
   texture colours. Two consequences, both fixed:
   - Painting/removing only touched the visible layer → selections now also take opposite-facing twin
     triangles within ¾ of an edge (`editmesh._twins`). The horn went from 625 to 1,520 painted triangles.
   - **Colour transfer in meshprep picked the hidden layer about half the time**, which put tan/pink blotches
     over every model (the dragon's "camouflage", much of the cow's mottling). It now takes the nearest
     original triangle that faces the same way as the rebuilt surface (`meshprep._colour_source`).
2. Colours were looked up after the model was lowered onto the bed (offset by the bottom cut, up to ~4 mm) →
   colours are now carried over before lowering.
3. A painted colour pushed out a colour the model needed (belly turned olive) → the other 3 slots are now
   suggested from the unpainted surface only.
4. Size/measuring/preparing previews showed the original model → they show the edited one.

## Known limits

- Colour-area selection follows the texture, so a base whose sides are a different shade needs the cut slider.
- Baked lighting in photo textures (cow) still bands into 2–3 browns with 4 filaments: paint the body one colour.
- Not yet tested in the UI this round: "Straight through" pen mode and "Keep only" (the edit itself is tested).

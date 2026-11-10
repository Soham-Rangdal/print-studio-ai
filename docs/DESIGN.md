---
name: Print Studio
description: A home-sewing-pattern world for turning photos and ideas into multicolour prints on a Creality K2 Pro.
colors:
  tissue: "#EDEFE9"
  tissue-sunken: "#E0E4DC"
  paper: "#F7F8F4"
  ink: "#1B2230"
  ink-secondary: "#4A5263"
  ink-tertiary: "#6B7282"
  rule: "#C4CBC0"
  band: "#0F5C4E"
  band-ink: "#F3EEE2"
  band-soft: "#DCE7E1"
  chart: "#F2B233"
  chart-soft: "#FBE7B8"
  cut: "#D2462F"
  cut-soft: "#F8DDD5"
  ok: "#2F7D4F"
typography:
  catalogue-number:
    fontFamily: "Jost, Segoe UI, system-ui, sans-serif"
    fontSize: "40px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Jost, Segoe UI, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  label:
    fontFamily: "Jost, Segoe UI, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "0.06em"
  body:
    fontFamily: "Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0em"
rounded:
  sm: "6px"
  md: "10px"
  lg: "14px"
spacing:
  xs: "6px"
  sm: "10px"
  md: "18px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.tissue}"
    rounded: "{rounded.md}"
    padding: "0 16px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "0 16px"
  envelope-lit:
    backgroundColor: "{colors.chart-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
---

# Design System: Print Studio

## Overview

Every model is issued like a home-sewing pattern: a catalogue number, views A–F of the making, a size chart and the materials needed. The app is a working tool (Operate), so the pattern world contributes type, palette, density and one signature move, while the layout stays a familiar three-column desktop app: envelope rail, the model, the decision column. Built from the direction contract in `.impeccable/surfaces/app-static-index-html.md`.

## Colors

Restrained ground with committed jobs for each colour; the only vivid colours on screen are the model itself and her real filament swatches.

### Primary
- **Catalogue band teal `#0F5C4E`**: the brand band at the top of the rail, catalogue numbers, the active step, focus rings, progress bars, the slider.

### Secondary
- **Size-chart saffron `#F2B233`** (soft `#FBE7B8`): the chosen size-chart row, text selection, and "finished while you were away" on an envelope. Nothing else.

### Tertiary
- **Cut-line red `#D2462F`**: print warnings only (too big, too thin, loose pieces, small bed contact, a step running far over time).

### Neutral
- **Pattern tissue `#EDEFE9`** (sunken `#E0E4DC`, raised paper `#F7F8F4`): a cool tissue grey-green, deliberately not cream.
- **Engraving ink `#1B2230`** with secondary `#4A5263` and tertiary `#6B7282` text; rules `#C4CBC0`.

### Named Rules
- **Colour quarantine:** the app's chrome stays ink, tissue and teal; colour that means "the object" (model, filament swatches) is never used for chrome.
- **Saffron means "yours":** her chosen size and things waiting for her, nothing decorative.

## Typography

**Jost** (self-hosted, `app/static/fonts`) for catalogue numbers, headings and small uppercase labels: the geometric pattern-envelope voice. **Segoe UI** for body and controls. Tabular numerals for every measurement.

### Hierarchy
- Catalogue number 40px/600, tracking −0.02em (PS-001).
- Screen heading 34px/500 (start), decision title 22px/600, size readout 44px/600 (−0.03em).
- Labels 11.5–13px uppercase, tracking +0.06em.
- Body 15px/1.5; notes 13–13.5px in tertiary ink.

## Layout

Three columns: rail 272px, the model (fluid), decision column 372px; whole-window height with each column scrolling on its own. Primary action pinned at the foot of the decision column. Below 1240px the columns narrow; below 1040px the rail hides.

## Elevation & Depth

Flat, like printed paper: elevation is a 1px rule or a change of ground (sunken wells for images and the 3D view, raised paper for the decision column). The only shadow is the slider thumb's 1–3px lift.

## Shapes

Radii 6 / 10 / 14px (tags, controls, wells). Pills only for idea chips. Step letters and slot numbers sit in circles like pattern view markers.

## Components

### Buttons
Primary: ink fill, tissue text, 40px (48px "big" in the decision foot). Quiet: 1px ink outline. Ghost: no border. All press to scale 0.97.

### Envelope (rail item)
Thumbnail, catalogue number in teal, name, status with a dot; teal pulsing dot while working, saffron fill and halo when it needs her (lit until seen).

### Step track
Pattern views A–F with circled letters; done = filled ink, current = filled teal with a 3px teal underline.

### Size chart (signature component)
Readout, slider and a table of preset heights with width, depth and grams; her row in saffron, rows that don't fit the 290 mm build in cut-line red. Dragging the slider updates every number live; the four CFS slots below show colour, share and grams.

### Inputs / Fields
Tissue-filled textarea with a 1px rule and a teal focus outline; dashed drop slots for the four photo views.

## Do's and Don'ts

### Do:
- Say what is happening and how long it usually takes; say so honestly when it runs long.
- Keep warnings in cut-line red with what to do about them.
- Use the pattern vocabulary sparingly: catalogue number, views, size chart, materials.

### Don't:
- Don't use cream backgrounds, gradient text, glass, glyph icons or side-stripe accents.
- Don't add colour to chrome; colour belongs to the model and her filaments.
- Don't animate continuously sideways; waiting states breathe in place.

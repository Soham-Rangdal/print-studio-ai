"use strict";
/* Print Studio UI. One window: envelope rail, the model, the decision column. */

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const ICON = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  idea: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>',
  photo: '<rect x="3" y="6" width="18" height="14" rx="2.5"/><path d="M8.5 6l1.5-2.5h4L15.5 6"/><circle cx="12" cy="13" r="3.5"/>',
  cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  warn: '<path d="M12 4l9 16H3L12 4z"/><path d="M12 10v4.5M12 17.5v.01"/>',
  retry: '<path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5"/><path d="M4 3.5v5h5"/>',
  open: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
  folder: '<path d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4.5l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5v7.5A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5v-10z"/>',
  file: '<path d="M7 3.5h7l4.5 4.5v12A1.5 1.5 0 0 1 17 21.5H7A1.5 1.5 0 0 1 5.5 20V5A1.5 1.5 0 0 1 7 3.5z"/><path d="M14 3.5V8h4.5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  trash: '<path d="M4.5 7h15M10 11v6M14 11v6M6.5 7l1 12.5h9l1-12.5M9.5 7V4.5h5V7"/>',
  click: '<path d="M9 4.5v8.2l-1.6-1.6a1.6 1.6 0 0 0-2.3 2.3l4.4 4.6A4.5 4.5 0 0 0 12.8 19.5H15a4.5 4.5 0 0 0 4.5-4.5v-3.5a1.5 1.5 0 0 0-3 0v-.5a1.5 1.5 0 0 0-3 0v-.5a1.5 1.5 0 0 0-3 0V4.5a1.5 1.5 0 0 0-3 0z"/>',
  pen: '<path d="M4 20l1.2-4.4L15.6 5.2a2 2 0 0 1 2.8 0l.4.4a2 2 0 0 1 0 2.8L8.4 18.8 4 20z"/><path d="M14 6.8l3.2 3.2"/>',
};
const icon = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n]}</svg>`;

const STEPS = [
  { key: "A", label: "Idea", stages: ["new", "writing", "importing"] },
  { key: "B", label: "Picture", stages: ["imagining", "choose_image"] },
  { key: "C", label: "Shape", stages: ["shaping", "review_shape"] },
  { key: "D", label: "Edit", stages: ["editprep", "edit"] },
  { key: "E", label: "Size & colours", stages: ["measuring", "size"] },
  { key: "F", label: "Check", stages: ["preparing", "review_final"] },
  { key: "G", label: "Print file", stages: ["exporting", "done"] },
];
const WORKING = new Set(["converting", "stepping", "importing", "writing", "imagining", "shaping", "editprep", "measuring", "preparing", "exporting"]);
const WAITING_FOR_HER = new Set(["choose_image", "review_shape", "edit", "size", "review_final"]);
const PRESETS_CM = [5, 8, 10, 12, 15, 20, 25];
const MAX_MM = 290;
const COMMON = [
  ["White", "#F5F3EE"], ["Black", "#1E1E1E"], ["Grey", "#8A8D91"], ["Red", "#C8312B"], ["Orange", "#EE7A22"],
  ["Yellow", "#F3D34A"], ["Green", "#3F9B48"], ["Teal", "#1E8C8A"], ["Blue", "#2A5BC4"], ["Purple", "#6E4AB2"],
  ["Pink", "#E58BB4"], ["Skin", "#E9C4A3"], ["Brown", "#7A4E2D"], ["Gold", "#C9A24A"],
];

// names only (not offered as presets): so a dark green is never called "Black"
const NAMES = COMMON.concat([
  ["Dark green", "#2E4A2A"], ["Light green", "#9BD08A"], ["Navy", "#1F2E5A"], ["Light blue", "#9CC4EC"],
  ["Beige", "#D9C7A3"], ["Cream", "#EFE6CF"], ["Dark red", "#7E1F1F"], ["Lilac", "#B9A3DC"], ["Dark grey", "#4A4C50"],
  ["Silver", "#BFC3C8"], ["Peach", "#F4B48A"], ["Lime", "#B5D334"], ["Olive", "#6E7A2C"], ["Mustard", "#C9A227"],
]);
const state = { edit: { tool: "area", through: false, scale: 130, cut: 0 }, editor: null, editorVersion: null,
  jobs: [], current: null, draft: { idea: "", photos: {}, files: [] }, size: null, timer: null };

/* ---------------------------------------------------------------- data */
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = "Something went wrong.";
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}
const act = (action, body = {}) => api(`/api/jobs/${state.current}/${action}`, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
const job = () => state.jobs.find((j) => j.id === state.current);
const fileUrl = (j, p) => `/jobs/${encodeURIComponent(j.id)}/${p}?v=${Math.round(j.updated || 0)}`;

function upsert(j) {
  if (j.deleted) {
    state.jobs = state.jobs.filter((x) => x.id !== j.id);
    if (state.current === j.id) state.current = null;
  } else {
    const i = state.jobs.findIndex((x) => x.id === j.id);
    const prev = i >= 0 ? state.jobs[i] : null;
    if (i >= 0) state.jobs[i] = j; else state.jobs.unshift(j);
    if (j.id === state.current && prev && prev.stage === j.stage && j.stage === "size") { renderRail(); return; }
    if (j.id === state.current && prev && prev.stage === j.stage && j.stage === "edit" && state.editor) {
      renderRail();                      // keep the 3D view and its camera; only reload the geometry
      if (j.edit_version !== state.editorVersion) loadEditor(j);
      renderEditPanel(j);
      return;
    }
  }
  render();
}

/* ---------------------------------------------------------------- rail */
function statusText(j) {
  if (j.stage === "error") return "Needs attention";
  if (j.stage === "done") return j.unseen ? "Print file ready" : "Ready to print";
  if (WAITING_FOR_HER.has(j.stage)) return j.unseen ? "Ready for you" : "Waiting for you";
  return j.status || "Working";
}
function renderRail() {
  $("#new-model").innerHTML = `${icon("plus")}New model`;
  const list = $("#envelopes");
  if (!state.jobs.length) {
    list.innerHTML = `<p class="rail-empty">Your models will be kept here, each with its own pattern number.</p>`;
    return;
  }
  list.innerHTML = `<h2>Your models</h2>` + state.jobs.map((j) => {
    const cls = ["envelope", WORKING.has(j.stage) ? "working" : "", j.unseen ? "lit" : "", j.stage === "error" ? "failed" : ""].join(" ");
    const thumb = j.thumb ? `<img src="${fileUrl(j, j.thumb)}" alt="">` : (j.images?.[0] ? `<img src="${fileUrl(j, j.chosen_image || j.images[0])}" alt="">` : (j.photos?.[0] ? `<img src="${fileUrl(j, j.photos[0])}" alt="">` : icon("cube")));
    return `<button class="${cls}" data-id="${esc(j.id)}" aria-current="${j.id === state.current}">
      <span class="thumb">${thumb}</span>
      <span class="meta"><span class="cat num">${esc(j.number)}</span><span class="title">${esc(j.name)}</span>
      <span class="state"><span class="dot"></span>${esc(statusText(j))}</span></span></button>`;
  }).join("");
}

/* ---------------------------------------------------------------- head: number, name, steps */
function renderHead(j) {
  const stage = j ? j.stage : "new";
  const nowIdx = STEPS.findIndex((s) => s.stages.includes(stage === "error" ? j.error_stage : stage));
  const steps = j && j.source === "convert"
    ? [["A", "Meshes", ["converting"]], ["B", "Solid files", ["converted"]]].map(([k, l, st]) => {
      const now = st.includes(stage === "error" ? j.error_stage : stage);
      const done = !now && stage === "converted";
      return `<div class="step ${now ? "now" : done ? "done" : ""}"><span class="letter">${k}</span>${l}</div>`;
    }).join("")
    : STEPS.map((s, i) => {
    const skipped = j && j.source !== "idea" && s.key === "B";
    const cls = i === nowIdx ? "now" : (i < nowIdx || skipped) ? "done" : "";
    const label = j && s.key === "A" && j.source !== "idea" ? (j.source === "file" ? "File" : "Photos") : s.label;
    return `<div class="step ${cls}"><span class="letter">${s.key}</span>${esc(label)}</div>`;
    }).join("");
  $("#stage-head").innerHTML = j
    ? `<div class="titleline"><span class="catno num">${esc(j.number)}</span>
        <input class="name" id="name" value="${esc(j.name)}" aria-label="Model name" maxlength="40">
        <button class="btn ghost" id="delete" type="button" title="Delete this model">${icon("trash")}<span class="sr-only">Delete</span></button></div>
       <nav class="steps" aria-label="Steps">${steps}</nav>`
    : `<div class="titleline"><span class="catno num">New</span><span class="name" style="pointer-events:none">Make something to print</span></div>
       <nav class="steps" aria-label="Steps">${steps}</nav>`;
}

/* ---------------------------------------------------------------- waiting */
function waitBlock(j, extra = "") {
  const typical = j.eta_s || 60;
  return `<div class="wait"><div class="doing">${esc(j.status || "Working")}</div>
    <div class="bar"><i id="bar"></i></div>
    <div class="times num"><span id="elapsed">0:00</span><span id="left">about ${fmtMin(typical)}</span></div>
    <p class="reassure">${extra || "You can leave this window open and come back: this model will light up in the list when it needs you."}</p></div>`;
}
function fmtMin(s) { s = Math.max(0, Math.round(s)); return s < 60 ? `${s} s` : `${Math.round(s / 60)} min`; }
function tick() {
  const j = job();
  if (!j || !WORKING.has(j.stage) || !j.stage_started) return;
  const el = (Date.now() / 1000) - j.stage_started, typical = j.eta_s || 60;
  const m = Math.floor(el / 60), s = Math.floor(el % 60);
  const e = $("#elapsed"), l = $("#left"), b = $("#bar");
  if (e) e.textContent = `${m}:${String(s).padStart(2, "0")}`;
  // honest progress: past the usual time say so, and past three times the usual time, say it may be stuck
  if (l) l.textContent = el < typical ? `about ${fmtMin(typical - el)} left`
    : el < typical * 3 ? "taking longer than usual" : "this is much slower than normal";
  if (l) l.classList.toggle("late", el >= typical * 3);
  if (b) b.style.width = `${Math.min(92, (el / typical) * 100)}%`;
}

/* ---------------------------------------------------------------- views per stage */
function viewer(src, tag, hint = "Drag to turn it around") {
  return `<div class="view-pane issue"><model-viewer src="${src}" camera-controls auto-rotate auto-rotate-delay="0"
    rotation-per-second="18deg" shadow-intensity="0.7" shadow-softness="0.9" exposure="1.05" environment-image="neutral"
    interaction-prompt="none" alt="3D model"></model-viewer>
    <span class="view-tag">${esc(tag)}</span><span class="view-hint">${esc(hint)}</span></div>`;
}
function imagePane(src, tag) {
  return `<div class="view-pane issue" style="place-items:center"><img src="${src}" alt="" style="max-height:100%;object-fit:contain">
    <span class="view-tag">${esc(tag)}</span></div>`;
}

function render() {
  renderRail();
  const j = job();
  renderHead(j);
  if (!j) return renderStart();
  if (j.unseen && (WAITING_FOR_HER.has(j.stage) || j.stage === "done")) act("seen").catch(() => {});
  const canvas = $("#canvas"), body = $("#decide-body"), foot = $("#decide-foot");
  foot.innerHTML = "";
  const st = j.stage;
  if (st !== "edit" && state.editor) { state.editor.destroy(); state.editor = null; state.editorVersion = null; }

  if (st === "writing" || st === "imagining") {
    const imgs = j.images || [];
    canvas.innerHTML = `<div class="options">${[0, 1, 2].map((i) => imgs[i]
      ? `<div class="option issue" style="cursor:default"><img src="${fileUrl(j, imgs[i])}" alt=""><span class="opt-label">${i + 1}</span></div>`
      : `<div class="slot-wait">${st === "writing" ? "Reading your idea" : `Drawing option ${i + 1}`}</div>`).join("")}</div>`;
    body.innerHTML = `<h2>Drawing your idea</h2><p>“${esc(j.idea)}”</p>${waitBlock(j, "Three pictures are being drawn in a printable toy style. You'll pick one.")}`;
  } else if (st === "choose_image") {
    const imgs = j.images || [];
    state.pick = state.pick ?? null;
    canvas.innerHTML = `<div class="options">${imgs.map((p, i) => `<button class="option issue" data-pick="${i}" aria-pressed="${state.pick === i}">
      <img src="${fileUrl(j, p)}" alt="Option ${i + 1}"><span class="opt-label">${i + 1}</span></button>`).join("")}</div>`;
    body.innerHTML = `<h2>Pick a picture</h2><p>The 3D model is built from the picture you choose, so pick the one whose shape you like best. Colours can be changed later.</p>
      <h3>Good to know</h3><p class="note">A whole object with thick, chunky parts prints best. Thin wings, tails or spikes may break.</p>`;
    foot.innerHTML = `<button class="btn primary big" id="use-pick" ${state.pick === null ? "disabled" : ""}>${icon("cube")}Make it 3D</button>
      <button class="btn quiet" id="more">${icon("retry")}Draw three new options</button>`;
  } else if (st === "shaping") {
    const src = j.source === "photos" ? j.photos[0] : j.chosen_image;
    canvas.innerHTML = imagePane(fileUrl(j, src), j.source === "photos" ? "Your photo" : "Your picture");
    body.innerHTML = `<h2>Building the 3D model</h2><p>First the shape, then the colours are painted on.</p>${waitBlock(j, "This is the slowest step: a few minutes. The model will light up in the list when it's ready.")}`;
  } else if (st === "importing") {
    canvas.innerHTML = `<div class="view-pane"></div>`;
    body.innerHTML = `<h2>Opening your file</h2><p class="note">${esc((j.source_files || []).join(", "))}</p>${waitBlock(j, "Reading the shape and its colours.")}`;
  } else if (st === "review_shape" && j.source === "file") {
    canvas.innerHTML = viewer(fileUrl(j, j.model_glb), "Your file");
    renderImported(j);
    return;
  } else if (st === "review_shape") {
    canvas.innerHTML = viewer(fileUrl(j, j.model_glb), "3D model");
    body.innerHTML = `<h2>Does it look right?</h2><p>Turn it around and look at the back and the bottom too. The parts a photo can't see were made up by the computer.</p>
      <h3>Look for</h3><p class="note">Missing or extra parts, a second face on the back, a lumpy surface, or parts floating loose.</p>`;
    foot.innerHTML = `<button class="btn primary big" id="approve-shape">${icon("check")}Looks good</button>
      <button class="btn quiet" id="retry-shape">${icon("retry")}Try another version</button>`;
  } else if (st === "editprep") {
    canvas.innerHTML = viewer(fileUrl(j, j.model_glb), "3D model");
    body.innerHTML = `<h2>Opening the editor</h2>${waitBlock(j, "Getting the model ready so you can select its parts.")}`;
  } else if (st === "edit") {
    mountEditor(j);
    renderEditPanel(j);
  } else if (st === "measuring") {
    canvas.innerHTML = viewer(fileUrl(j, j.edited_glb || j.model_glb), j.edited_glb ? "Your edited model" : "3D model");
    body.innerHTML = `<h2>Measuring the model</h2>${waitBlock(j, "Working out its proportions and its main colours, so the size chart and colours below can be filled in.")}`;
  } else if (st === "size") {
    canvas.innerHTML = viewer(fileUrl(j, j.edited_glb || j.model_glb), j.edited_glb ? "Your edited model" : "3D model");
    renderSize(j);
    return;
  } else if (st === "preparing") {
    canvas.innerHTML = viewer(fileUrl(j, j.edited_glb || j.model_glb), j.edited_glb ? "Your edited model" : "3D model");
    body.innerHTML = `<h2>Making it printable</h2><p>Closing holes, giving it a flat bottom, checking for thin or loose parts, and painting it with your four filaments.</p>${waitBlock(j)}`;
  } else if (st === "review_final") {
    canvas.innerHTML = viewer(fileUrl(j, j.final_glb), "With your filaments");
    renderFinal(j);
  } else if (st === "exporting") {
    canvas.innerHTML = viewer(fileUrl(j, j.final_glb), "With your filaments");
    body.innerHTML = `<h2>Saving the print file</h2>${waitBlock(j)}`;
  } else if (st === "done") {
    canvas.innerHTML = viewer(fileUrl(j, j.final_glb), "Ready to print");
    renderDone(j);
  } else if (st === "stepping") {
    canvas.innerHTML = viewer(fileUrl(j, j.final_glb), "Ready to print");
    body.innerHTML = `<h2>Making the solid file</h2><p>A STEP copy of this model for CAD programs (Fusion, SolidWorks, FreeCAD).</p>${waitBlock(j, "A minute or two for a detailed model.")}`;
  } else if (st === "converting" || st === "converted") {
    renderSolids(j);
    return;
  } else if (st === "error") {
    canvas.innerHTML = j.model_glb ? viewer(fileUrl(j, j.model_glb), "3D model")
      : j.source === "convert" ? solidsGrid(j) : `<div class="view-pane"></div>`;
    body.innerHTML = `<h2>This step didn't work</h2><div class="error-box">${esc(j.status)}</div>`;
    foot.innerHTML = `<button class="btn primary big" id="retry-step">${icon("retry")}Try this step again</button>`;
  }
  tick();
}

/* ---------------------------------------------------------------- mesh -> solid (STEP) */
function solidsGrid(j) {
  return `<div class="solids">${(j.conversions || []).map((c) => {
    const pic = c.preview ? `<img src="${fileUrl(j, c.preview)}" alt="">`
      : `<div class="slot-wait">${c.status === "failed" ? "Couldn't convert" : c.status === "working" ? "Converting" : "Waiting"}</div>`;
    return `<figure class="solid ${c.status}">${pic}<figcaption>${esc(c.file)}</figcaption></figure>`;
  }).join("")}</div>`;
}
function solidLine(c) {
  if (c.status === "failed") return `<span class="bad">${esc(c.message || "Couldn't convert")}</span>`;
  if (c.status !== "done") return c.status === "working" ? "Converting…" : "Waiting";
  const r = c.report || {}, ch = c.check || {}, f = ch.faces || {};
  const n = (f.plane || 0) + (f.cylinder || 0) + (f.other || 0);
  const what = r.level === "triangles" ? `${n.toLocaleString()} small flat faces`
    : `${n.toLocaleString()} faces: ${(f.plane || 0).toLocaleString()} flat${f.cylinder ? `, ${f.cylinder} round` : ""}`;
  const kind = r.level === "exact" ? "planes and cylinders rebuilt" : r.level === "planes" ? "flat faces merged; curves stay faceted" : "faceted";
  return `${what} (${kind})${ch.valid ? "" : " · check it in CAD"}${r.lightened_to ? ` · lightened from ${r.triangles_in.toLocaleString()} triangles` : ""}`;
}
function renderSolids(j) {
  $("#canvas").innerHTML = solidsGrid(j);
  const done = (j.conversions || []).filter((c) => c.status === "done").length;
  $("#decide-body").innerHTML = `<h2>${j.stage === "converted" ? "Solid files ready" : "Converting to solid"}</h2>
    <p>Each mesh becomes a STEP file: one solid body that Fusion, SolidWorks, FreeCAD and Onshape open for sketching, extruding and editing faces.</p>
    <div class="files">${(j.conversions || []).map((c) => `<div class="file">${icon("file")}<div><b>${esc(c.step ? c.step.split("/").pop() : c.file)}</b><span>${solidLine(c)}</span></div></div>`).join("")}</div>
    ${j.stage === "converting" ? waitBlock(j, "About half a minute per file; organic shapes take longer.") : ""}
    <h3>In the pictures</h3>
    <div class="legend"><span><i style="background:#4678C8"></i>Flat faces</span><span><i style="background:#E68C32"></i>Round (cylinders)</span><span><i style="background:#A0A0A0"></i>Other</span></div>
    <p class="note">Flat areas, holes, bosses and rounded edges become real planes and cylinders. Organic shapes (figures, sculpts) become many small flat faces: still one solid you can cut, join and add features to, but not reshape like a sketch.</p>`;
  $("#decide-foot").innerHTML = j.stage === "converted"
    ? `<button class="btn primary big" id="show-folder">${icon("folder")}Show the STEP files</button><span class="note">${done} of ${(j.conversions || []).length} converted</span>`
    : "";
}

/* ---------------------------------------------------------------- C (file): check an imported model */
function renderImported(j) {
  const im = j.imported || {};
  const cm = (mm) => (mm / 10).toFixed(1);
  const real = im.height_mm >= 5 && im.height_mm <= 290;
  const colourNote = im.painted ? `Its painted colours are kept: ${(im.palette || []).length} filaments.`
    : im.coloured ? "Its colours are kept and matched to your 4 filaments later."
    : "This file has no colours. You'll choose your filaments, and can paint parts in the next step.";
  $("#decide-body").innerHTML = `<h2>Is this your model?</h2>
    <p>Turn it around. It should stand the way it will print: upright, on its bottom.</p>
    <dl class="facts">
      <div><dt>File</dt><dd>${esc(im.format || "")}</dd></div>
      <div><dt>Triangles</dt><dd>${(im.simplified_to || im.faces_in_file || 0).toLocaleString()}</dd></div>
      <div style="grid-column: 1 / -1"><dt>Size in the file (W × D × H)</dt><dd>${real ? `${cm(im.width_mm)} × ${cm(im.depth_mm)} × ${cm(im.height_mm)} cm` : "not given"}</dd></div>
    </dl>
    <p class="note">${esc(colourNote)}${im.simplified_to ? ` It had ${im.faces_in_file.toLocaleString()} triangles; it was lightened to ${im.simplified_to.toLocaleString()} so it stays quick to edit.` : ""}${real ? "" : " You'll choose the height in step E."}</p>
    <h3>Lying down or upside down?</h3>
    <div class="row"><button class="btn quiet" data-turn="x">${icon("retry")}Tip forward</button>
      <button class="btn quiet" data-turn="z">${icon("retry")}Roll sideways</button></div>
    <p class="note">Each press turns it a quarter turn. Press again until it stands right.</p>`;
  $("#decide-foot").innerHTML = `<button class="btn primary big" id="approve-shape">${icon("check")}It stands right</button>`;
}

/* ---------------------------------------------------------------- start: idea, photos or a file */
function renderStart() {
  const d = state.draft;
  const views = ["front", "right", "back", "left"];
  $("#canvas").innerHTML = `<div class="start issue">
    <h1>What would you like to print?</h1>
    <p class="lede">Describe it, show it with photos, or open a 3D file you already have. You'll approve the shape and the colours before anything is saved.</p>
    <div class="way"><h2>${icon("idea")}Describe it</h2>
      <p>A short description works: what it is, a style, and its colours.</p>
      <textarea class="idea" id="idea" placeholder="A friendly cartoon dragon, green with a yellow belly">${esc(d.idea)}</textarea>
      <div class="ideas">${["A friendly cartoon dragon", "A cat sitting on a cushion", "A small elephant planter", "A rocket pencil holder"].map((t) => `<button class="chip" data-idea="${esc(t)}">${esc(t)}</button>`).join("")}</div>
      <button class="btn primary" id="go-idea" ${d.idea.trim() ? "" : "disabled"}>${icon("idea")}Draw it</button></div>
    <div class="way"><h2>${icon("photo")}Use photos</h2>
      <p>One photo works. Four photos (front, right, back, left) give a much better back and sides.</p>
      <div class="views4">${views.map((v) => `<div class="drop" data-view="${v}" tabindex="0" role="button" aria-label="Add ${v} photo">
        ${d.photos[v] ? `<img src="${d.photos[v].url}" alt=""><button class="clear" data-clear="${v}" aria-label="Remove">${icon("close")}</button>` : `<span><strong>${v[0].toUpperCase() + v.slice(1)}</strong>Add photo</span>`}</div>`).join("")}</div>
      <p class="note ${photoHint().warn ? "warn" : ""}" id="photo-hint">${esc(photoHint().text)}</p>
      <button class="btn primary" id="go-photos" ${photoHint().ok ? "" : "disabled"}>${icon("cube")}Make it 3D</button></div>
    <div class="way way-file"><h2>${icon("open")}Open a 3D file</h2>
      <p>Already have a model? STL, 3MF, OBJ, GLB or PLY. Open it to print (a painted 3MF keeps its colours), or convert several meshes at once into solid STEP files for CAD.</p>
      <div class="filedrop" data-filedrop tabindex="0" role="button" aria-label="Choose a 3D file">
        ${d.files.length ? `<span><strong>${esc(d.files.map((f) => f.name).join(", "))}</strong>${fileHint().text}</span><button class="clear" id="clear-files" aria-label="Remove">${icon("close")}</button>`
          : `<span><strong>Drop the file here</strong>or click to choose it</span>`}</div>
      <div class="file-actions"><button class="btn primary" id="go-file" ${fileHint().ok ? "" : "disabled"}>${icon("open")}Open it to print</button>
        <button class="btn quiet" id="go-convert" ${fileHint().ok ? "" : "disabled"}>${icon("cube")}Convert to solid (STEP)</button></div></div>
  </div>`;
  $("#decide-body").innerHTML = `<h2>How it works</h2>
    <div class="checks">${[
      ["A", "Tell it what to make: words, photos or a 3D file."],
      ["B", "Pick the picture you like (for words)."],
      ["C", "Check the 3D shape from all sides."],
      ["D", "Choose the height and your 4 filament colours."],
      ["E", "Read the print checks."],
      ["F", "Open the file in Creality Print and print."],
    ].map(([k, t]) => `<div class="check"><span class="step now" style="padding:0"><span class="letter">${k}</span></span><span>${t}</span></div>`).join("")}</div>
    <p class="note">A model takes about 8 to 12 minutes from start to file. Everything runs on this laptop.</p>`;
  $("#decide-foot").innerHTML = "";
}
const MODEL_EXT = [".stl", ".3mf", ".obj", ".glb", ".gltf", ".ply", ".off", ".zip"];
const FILE_EXT = MODEL_EXT.concat([".mtl", ".bin", ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp"]);
const extOf = (n) => (n.match(/\.[^.]+$/) || [""])[0].toLowerCase();
function fileHint() {
  const f = state.draft.files;
  if (!f.length) return { ok: false, text: "" };
  const models = f.filter((x) => MODEL_EXT.includes(extOf(x.name)));
  if (!models.length) return { ok: false, text: "Add the model itself too (.obj, .stl, ...)." };
  const mb = f.reduce((a, x) => a + x.size, 0) / 2 ** 20;
  return { ok: true, text: `${models.length > 1 ? `${models.length} models, ` : ""}${mb < 1 ? "under 1" : Math.round(mb)} MB` };
}
function setFiles(list) {
  const ok = [...list].filter((f) => FILE_EXT.includes(extOf(f.name)));
  if (!ok.length) { alert("That isn't a 3D file this app can open. Use STL, 3MF, OBJ, GLB, PLY, OFF or a .zip."); return; }
  state.draft.files = ok;
  renderStart();
}
function photoHint() {
  const n = Object.keys(state.draft.photos).length, has = (v) => !!state.draft.photos[v];
  if (n === 0) return { text: "Plain background, the whole object in view, good light.", ok: false };
  if (n === 4) return { text: "Four sides: great.", ok: true };
  if (n === 1 && has("front")) return { text: "One photo: the back and sides will be guessed. Add all four sides for a better model.", ok: true };
  return { text: "Add all four sides, or keep only the front photo.", ok: false, warn: true };
}

/* ---------------------------------------------------------------- D: size chart + materials (the signature) */
function initSize(j) {
  if (state.size && state.size.id === j.id) return state.size;
  const sug = j.suggested_palette || [];
  state.size = {
    id: j.id,
    h: Math.round((j.settings?.height_mm || 100) / 10 * 2) / 2,
    palette: (j.settings?.palette || sug.map((s) => s[0])).slice(0, 4),
    share: sug.map((s) => s[1]),
  };
  return state.size;
}
function grams(ref, hcm) {
  const s = hcm / (ref.height_mm / 10), V = ref.volume_cm3 * s ** 3, A = ref.area_cm2 * s * s;
  const shell = Math.min(V, A * 0.12);
  return (shell + 0.15 * Math.max(0, V - shell)) * 1.24 * 0.82;   // calibrated on a real Creality Print slice
}
function dims(ref, hcm) {
  const k = hcm * 10 / ref.height_mm;
  return { h: hcm * 10, w: ref.width_mm * k, d: ref.depth_mm * k };
}
function colourName(hex) {
  const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [r, g, b] = rgb(hex);
  let best = NAMES[0], bd = 1e9;
  for (const c of NAMES) { const [R, G, B] = rgb(c[1]); const dd = (r - R) ** 2 + (g - G) ** 2 + (b - B) ** 2; if (dd < bd) { bd = dd; best = c; } }
  return bd < 2500 ? best[0] : `${best[0]}-ish`;
}
function renderSize(j) {
  const S = initSize(j), ref = j.reference;
  const maxCm = Math.floor(MAX_MM / Math.max(ref.height_mm, ref.width_mm, ref.depth_mm) * ref.height_mm / 10 * 2) / 2;
  $("#decide-body").innerHTML = `<h2>Size and colours</h2>
    <div class="sizer">
      <div class="readout"><b class="num" id="h-read">${S.h}<small>cm</small></b><span id="h-dims"></span></div>
      <input type="range" id="h" min="3" max="${Math.min(29, maxCm)}" step="0.5" value="${S.h}" aria-label="Height in centimetres">
      <table class="chart" aria-label="Size chart"><thead><tr><th>Height</th><th>Width</th><th>Depth</th><th>Filament</th></tr></thead><tbody id="chart"></tbody></table>
    </div>
    <h3>Filaments in your CFS</h3>
    <div class="slots" id="slots"></div>
    <div class="palette-row" id="presets" aria-label="Common colours">${COMMON.map(([n, c]) => `<button style="background:${c}" data-colour="${c}" title="${n}" aria-label="${n}"></button>`).join("")}</div>
    <p class="note">Pick a slot, then a colour. Grams are an estimate for Creality Print's standard settings; the prime tower for colour changes adds a little more.</p>`;
  $("#decide-foot").innerHTML = `<button class="btn primary big" id="prepare">${icon("check")}Make it printable</button>
    <button class="btn quiet" id="back-edit">${icon("back")}Back to edit parts</button>`;
  S.active = S.active ?? 0;
  drawSize(j);
}
function drawSize(j) {
  const S = state.size, ref = j.reference;
  const fill = ($("#h").value - $("#h").min) / ($("#h").max - $("#h").min) * 100;
  $("#h").style.setProperty("--fill", `${fill}%`);
  const d = dims(ref, S.h), g = grams(ref, S.h);
  $("#h-read").innerHTML = `${S.h}<small>cm</small>`;
  $("#h-dims").innerHTML = `${(d.w / 10).toFixed(1)} × ${(d.d / 10).toFixed(1)} cm base<br>about ${Math.round(g)} g`;
  const rows = [...new Set([...PRESETS_CM, S.h])].sort((a, b) => a - b);
  $("#chart").innerHTML = rows.map((h) => {
    const dd = dims(ref, h), big = Math.max(dd.h, dd.w, dd.d) > MAX_MM;
    return `<tr class="${h === S.h ? "pick" : "preset"} ${big ? "toobig" : ""}" data-h="${h}"><td>${h} cm${h === S.h ? " · yours" : ""}</td>
      <td>${(dd.w / 10).toFixed(1)}</td><td>${(dd.d / 10).toFixed(1)}</td><td>${big ? "too big" : `${Math.round(grams(ref, h))} g`}</td></tr>`;
  }).join("");
  const total = g;
  $("#slots").innerHTML = S.palette.map((c, i) => `<div class="slot">
      <span class="n">${i + 1}</span>
      <label class="swatch" style="background:${c}; ${S.active === i ? "outline:2px solid var(--band);outline-offset:2px" : ""}" data-slot="${i}">
        <input type="color" value="${c}" data-slot-input="${i}" aria-label="Colour of slot ${i + 1}"></label>
      <span class="label">${colourName(c)}<small>Slot ${i + 1} · ${Math.round((S.share[i] || 0) * 100)}% of the surface</small></span>
      <span class="grams num">${Math.round(total * (S.share[i] || 0))} g</span></div>`).join("");
}
let estTimer = null;
function reestimate(j) {
  clearTimeout(estTimer);
  estTimer = setTimeout(async () => {
    try {
      const r = await api(`/api/estimate/${j.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ palette: state.size.palette }) });
      state.size.share = r.share;
      drawSize(j);
    } catch (_) {}
  }, 250);
}

/* ---------------------------------------------------------------- D: part editor */
function mountEditor(j) {
  const canvas = $("#canvas");
  if (state.editor && $("#editor-pane")) return;
  canvas.innerHTML = `<div class="editor-pane issue" id="editor-pane"><span class="editor-hint" id="editor-hint"></span></div>`;
  const start = () => {
    state.editor = window.PrintEditor.mount($("#editor-pane"), { onSelection: (s) => { state.selection = s; updateSelInfo(); } });
    state.editor.setTool(state.edit.tool);
    state.editor.through = state.edit.through;
    loadEditor(j);
    updateHint();
  };
  window.PrintEditor ? start() : window.addEventListener("printeditor-ready", start, { once: true });
}
function loadEditor(j) {
  state.editorVersion = j.edit_version;
  state.editor.load(`/jobs/${encodeURIComponent(j.id)}/`, j.edit_version, j.edit_faces).then(() => {
    state.editor.setCut(state.edit.cut);      // 0 after a cut is applied: clears the red preview plane
  });
}
function updateHint() {
  const h = $("#editor-hint");
  if (h) h.textContent = state.edit.tool === "pen"
    ? "Draw around a part with the left button · turn the model with the right button · hold Alt to unselect"
    : "Click a colour area to select it · drag to turn the model · hold Alt to unselect";
}
function updateSelInfo() {
  const s = state.selection || { count: 0, share: 0 }, el = $("#selinfo");
  if (!el) return;
  el.innerHTML = s.count
    ? `<span><b>${s.count.toLocaleString()}</b> triangles · ${(s.share * 100).toFixed(1)}% of the model</span>`
    : `<span class="note">Nothing selected yet</span>`;
  document.querySelectorAll("[data-needs-sel]").forEach((b) => { b.disabled = !s.count; });
}
const EDIT_LABEL = {
  remove: (e) => `Removed a part (${e.count.toLocaleString()} triangles)`,
  keep: (e) => `Kept only a part (${e.count.toLocaleString()} triangles)`,
  scale: (e) => `Resized a part to ${Math.round(e.factor * 100)}%`,
  paint: (e) => `Painted a part ${colourName(e.rgb)}`,
  cut_below: (e) => `Cut ${Math.round(e.frac * 100)}% off the bottom`,
};
function renderEditPanel(j) {
  const E = state.edit, edits = j.edits || [];
  $("#decide-body").innerHTML = `<h2>Change parts</h2>
    <p>Optional. Remove a base, resize spikes or a tail, or recolour an area. Holes are closed and the print checks run again afterwards.</p>
    <h3>1 · Select</h3>
    <div class="seg" role="group" aria-label="Selection tool">
      <button data-tool="area" aria-pressed="${E.tool === "area"}">${icon("click")}Colour area</button>
      <button data-tool="pen" aria-pressed="${E.tool === "pen"}">${icon("pen")}Draw around</button></div>
    ${E.tool === "pen" ? `<div class="seg small" role="group" aria-label="Pen depth">
      <button data-through="0" aria-pressed="${!E.through}">Front only</button>
      <button data-through="1" aria-pressed="${E.through}">Straight through</button></div>` : ""}
    <div class="selinfo" id="selinfo"></div>
    <div class="row"><button class="btn quiet" id="sel-grow" data-needs-sel>Grow</button>
      <button class="btn quiet" id="sel-shrink" data-needs-sel>Shrink</button>
      <button class="btn ghost" id="sel-clear" data-needs-sel>Clear</button></div>
    <h3>2 · Change the selected part</h3>
    <div class="row"><button class="btn quiet" id="ed-remove" data-needs-sel>${icon("trash")}Remove</button>
      <button class="btn quiet" id="ed-keep" data-needs-sel>Keep only this</button></div>
    <div class="rangeline"><input type="range" id="ed-scale" min="50" max="200" step="5" value="${E.scale}" aria-label="New size of the part"><output id="ed-scale-out">${E.scale}%</output></div>
    <button class="btn quiet" id="ed-resize" data-needs-sel>Resize to ${E.scale}%</button>
    <div class="palette-row" aria-label="Paint with">${COMMON.map(([n, c]) => `<button style="background:${c}" data-paint="${c}" title="Paint ${n}" aria-label="Paint ${n}" data-needs-sel></button>`).join("")}</div>
    <h3>Cut from the bottom</h3>
    <div class="rangeline"><input type="range" id="ed-cut" min="0" max="40" step="1" value="${Math.round(E.cut * 100)}" aria-label="How much to cut off the bottom"><output id="ed-cut-out">${Math.round(E.cut * 100)}%</output></div>
    <button class="btn quiet" id="ed-cut-apply" ${E.cut > 0 ? "" : "disabled"}>Cut below the red plane</button>
    <h3>Changes</h3>
    ${edits.length ? `<ul class="edits">${edits.map((e) => `<li>${esc(EDIT_LABEL[e.op] ? EDIT_LABEL[e.op](e) : e.op)}</li>`).join("")}</ul>
      <div class="row"><button class="btn quiet" id="ed-undo">${icon("retry")}Undo last</button><button class="btn ghost" id="ed-reset">Start over</button></div>`
      : `<p class="note">No changes yet.</p>`}`;
  $("#decide-foot").innerHTML = `<button class="btn primary big" id="finish-edit">${icon("check")}${edits.length ? "Continue to size and colours" : "Continue without changes"}</button>`;
  updateSelInfo();
}
async function sendEdit(body) {
  const j = job();
  try {
    document.querySelectorAll("#decide button").forEach((b) => (b.disabled = true));
    const updated = await api(`/api/edit/${j.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (body.op === "cut_below") { state.edit.cut = 0; }
    upsert(updated);
  } catch (err) { alert(err.message); renderEditPanel(job()); }
}

/* ---------------------------------------------------------------- E and F */
function renderFinal(j) {
  const f = j.final || {}, s = j.settings;
  const warnings = f.warnings || [];
  const total = (f.grams || []).reduce((a, b) => a + b, 0);
  $("#decide-body").innerHTML = `<h2>Print checks</h2>
    <dl class="facts">
      <div><dt>Height</dt><dd class="num">${(f.height_mm / 10).toFixed(1)} cm</dd></div>
      <div><dt>Base</dt><dd class="num">${(f.width_mm / 10).toFixed(1)} × ${(f.depth_mm / 10).toFixed(1)} cm</dd></div>
      <div><dt>Filament</dt><dd class="num">about ${Math.round(total)} g</dd></div>
      <div><dt>Solid</dt><dd>${f.watertight ? "Yes" : "No"}</dd></div>
    </dl>
    <div class="checks">${warnings.length ? warnings.map((w) => `<div class="check bad">${icon("warn")}<span>${esc(w)}</span></div>`).join("") : ""}
      ${checkLine(!warnings.some((w) => w.startsWith("Too big")), "Fits on the K2 Pro bed")}
      ${checkLine(!warnings.some((w) => w.includes("thin")), "No parts too thin to print")}
      ${checkLine(!warnings.some((w) => w.includes("separate")), "One piece, nothing loose")}
      ${checkLine(!warnings.some((w) => w.includes("contact")), "Stands firmly on the bed")}</div>
    <h3>Filaments</h3>
    <div class="slots">${s.palette.map((c, i) => `<div class="slot"><span class="n">${i + 1}</span><span class="swatch" style="background:${c};cursor:default"></span>
      <span class="label">${colourName(c)}<small>Slot ${i + 1}</small></span><span class="grams num">${Math.round((f.grams || [])[i] || 0)} g</span></div>`).join("")}</div>
    ${j.final_views ? `<h3>All sides</h3><div class="turn"><img src="${fileUrl(j, j.final_views)}" alt="Front, right, back and angled views"></div>` : ""}`;
  $("#decide-foot").innerHTML = `<button class="btn primary big" id="approve-final">${icon("file")}Save print file</button>
    <button class="btn quiet" id="back-size">${icon("back")}Change size or colours</button>`;
}
function checkLine(ok, text) {
  return ok ? `<div class="check ok">${icon("check")}<span>${text}</span></div>` : "";
}
function renderDone(j) {
  $("#decide-body").innerHTML = `<h2>Ready to print</h2>
    <p>Open it in Creality Print. The colours are already painted on CFS slots 1 to 4.</p>
    <div class="files"><div class="file">${icon("file")}<div><b>${esc(j.files.project)}</b><span>Print file with colours</span></div></div>
      <div class="file">${icon("cube")}<div><b>print.stl</b><span>One-colour copy, for any slicer</span></div></div>
      ${j.files.step ? `<div class="file">${icon("file")}<div><b>${esc(j.files.step)}</b><span>Solid body for CAD (${solidLine({ status: "done", report: j.step_report, check: { valid: true, faces: { plane: j.step_report?.planes, cylinder: j.step_report?.cylinders, other: j.step_report?.other } } })})</span></div></div>` : ""}</div>
    <h3>In Creality Print</h3>
    <div class="checks">${["Check the four colours are on slots 1 to 4", "Add supports if parts hang in the air", "Slice, then send it to the K2 Pro"]
      .map((t, i) => `<div class="check"><span class="step done" style="padding:0"><span class="letter">${i + 1}</span></span><span>${t}</span></div>`).join("")}</div>`;
  $("#decide-foot").innerHTML = `<button class="btn primary big" id="open-slicer">${icon("open")}Open in Creality Print</button>
    <button class="btn quiet" id="show-folder">${icon("folder")}Show the files</button>
    ${j.files.step ? "" : `<button class="btn quiet" id="make-step">${icon("cube")}Also save a solid (STEP)</button>`}`;
}

/* ---------------------------------------------------------------- events */
document.addEventListener("click", async (e) => {
  const t = e.target.closest("button, [data-view], [data-filedrop], tr[data-h]");
  if (!t) return;
  try {
    if (t.id === "new-model") { state.current = null; state.pick = null; render(); return; }
    if (t.dataset.id) { state.current = t.dataset.id; state.pick = null; state.size = null; render(); return; }
    if (t.dataset.idea) { state.draft.idea = t.dataset.idea; renderStart(); $("#idea").focus(); return; }
    if (t.dataset.clear) { e.stopPropagation(); delete state.draft.photos[t.dataset.clear]; renderStart(); return; }
    if (t.dataset.view) { pickPhoto(t.dataset.view); return; }
    if (t.id === "clear-files") { e.stopPropagation(); state.draft.files = []; renderStart(); return; }
    if (t.dataset.filedrop !== undefined) { pickModel(); return; }
    if (t.id === "go-file") {
      t.disabled = true;
      const fd = new FormData(); state.draft.files.forEach((f) => fd.append("files", f));
      const j = await api("/api/jobs/file", { method: "POST", body: fd }); state.draft.files = []; state.current = j.id; upsert(j); return;
    }
    if (t.id === "go-convert") {
      t.disabled = true;
      const fd = new FormData(); state.draft.files.forEach((f) => fd.append("files", f));
      const j = await api("/api/convert", { method: "POST", body: fd }); state.draft.files = []; state.current = j.id; upsert(j); return;
    }
    if (t.id === "make-step") { t.disabled = true; await act("make_step"); return; }
    if (t.dataset.turn) { t.disabled = true; await act("turn", { axis: t.dataset.turn }); return; }
    if (t.id === "go-idea") { t.disabled = true; const j = await api("/api/jobs/idea", { method: "POST", body: new URLSearchParams({ idea: state.draft.idea }) }); state.draft.idea = ""; state.current = j.id; upsert(j); return; }
    if (t.id === "go-photos") {
      t.disabled = true;
      const order = Object.keys(state.draft.photos).length === 4 ? ["front", "right", "back", "left"] : ["front"];
      const fd = new FormData(); order.forEach((v) => fd.append("photos", state.draft.photos[v].file));
      const j = await api("/api/jobs/photos", { method: "POST", body: fd }); state.draft.photos = {}; state.current = j.id; upsert(j); return;
    }
    if (t.dataset.pick !== undefined) { state.pick = +t.dataset.pick; render(); return; }
    if (t.id === "use-pick") { t.disabled = true; await act("choose_image", { index: state.pick }); state.pick = null; return; }
    if (t.id === "more") { await act("more_images"); return; }
    if (t.id === "approve-shape") { t.disabled = true; await act("approve_shape"); return; }
    if (t.id === "retry-shape") { await act("retry_shape"); return; }
    if (t.dataset.h && job()?.stage === "size") { state.size.h = +t.dataset.h; $("#h").value = state.size.h; drawSize(job()); return; }
    if (t.dataset.colour && state.size) { state.size.palette[state.size.active] = t.dataset.colour; drawSize(job()); reestimate(job()); return; }
    if (t.id === "prepare") { t.disabled = true; await act("prepare", { height_mm: state.size.h * 10, palette: state.size.palette }); return; }
    if (t.id === "approve-final") { t.disabled = true; await act("approve_final", { name: $("#name")?.value }); return; }
    if (t.id === "back-size") { state.size = null; await act("back_to_size"); return; }
    if (t.id === "open-slicer") { await act("open_slicer"); return; }
    if (t.id === "show-folder") { await act("show_folder"); return; }
    if (t.dataset.tool) { state.edit.tool = t.dataset.tool; state.editor?.setTool(t.dataset.tool); updateHint(); renderEditPanel(job()); return; }
    if (t.dataset.through !== undefined) { state.edit.through = t.dataset.through === "1"; if (state.editor) state.editor.through = state.edit.through; renderEditPanel(job()); return; }
    if (t.id === "sel-grow") { state.editor?.grow(); return; }
    if (t.id === "sel-shrink") { state.editor?.shrink(); return; }
    if (t.id === "sel-clear") { state.editor?.clear(); return; }
    if (t.id === "ed-remove") { await sendEdit({ op: "remove", faces: state.editor.selected() }); return; }
    if (t.id === "ed-keep") {
      if (confirm("Keep only the selected part and remove everything else?")) await sendEdit({ op: "keep", faces: state.editor.selected() });
      return;
    }
    if (t.id === "ed-resize") { await sendEdit({ op: "scale", faces: state.editor.selected(), factor: state.edit.scale / 100 }); return; }
    if (t.dataset.paint) { await sendEdit({ op: "paint", faces: state.editor.selected(), rgb: t.dataset.paint }); return; }
    if (t.id === "ed-cut-apply") { await sendEdit({ op: "cut_below", frac: state.edit.cut }); return; }
    if (t.id === "ed-undo") { await sendEdit({ op: "undo" }); return; }
    if (t.id === "ed-reset") { if (confirm("Undo all changes to this model?")) await sendEdit({ op: "reset" }); return; }
    if (t.id === "finish-edit") { t.disabled = true; await act("finish_edit"); return; }
    if (t.id === "back-edit") { state.size = null; await act("back_to_edit"); return; }
    if (t.id === "retry-step") { await act("retry"); return; }
    if (t.id === "delete") { if (confirm("Delete this model and its files? This can't be undone.")) await act("delete"); return; }
  } catch (err) { alert(err.message); }
});
document.addEventListener("pointerdown", (e) => {
  const sw = e.target.closest("[data-slot]");
  if (sw && state.size) { state.size.active = +sw.dataset.slot; drawSize(job()); }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "idea") { state.draft.idea = e.target.value; $("#go-idea").disabled = !e.target.value.trim(); }
  if (e.target.id === "h" && state.size) { state.size.h = +e.target.value; drawSize(job()); }
  if (e.target.id === "ed-scale") {
    state.edit.scale = +e.target.value;
    $("#ed-scale-out").textContent = `${state.edit.scale}%`;
    const b = $("#ed-resize"); if (b) b.textContent = `Resize to ${state.edit.scale}%`;
  }
  if (e.target.id === "ed-cut") {
    state.edit.cut = +e.target.value / 100;
    $("#ed-cut-out").textContent = `${e.target.value}%`;
    $("#ed-cut-apply").disabled = state.edit.cut <= 0;
    state.editor?.setCut(state.edit.cut);           // live preview: the red plane and the part that would go
  }
  if (e.target.dataset.slotInput !== undefined && state.size) {
    const i = +e.target.dataset.slotInput; state.size.palette[i] = e.target.value.toUpperCase(); state.size.active = i;
    e.target.closest(".swatch").style.background = e.target.value; reestimate(job());
  }
});
document.addEventListener("change", (e) => { if (e.target.dataset.slotInput !== undefined) drawSize(job()); });
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.dataset?.view) { e.preventDefault(); pickPhoto(e.target.dataset.view); }
  if ((e.key === "Enter" || e.key === " ") && e.target.dataset?.filedrop !== undefined) { e.preventDefault(); pickModel(); }
});
document.addEventListener("focusout", async (e) => {
  if (e.target.id === "name" && job() && e.target.value.trim() && e.target.value !== job().name) {
    try { await act("rename", { name: e.target.value }); } catch (_) {}
  }
});
for (const ev of ["dragover", "dragleave", "drop"]) {
  document.addEventListener(ev, (e) => {
    const d = e.target.closest?.("[data-view], [data-filedrop]");
    if (!d) return;
    e.preventDefault();
    d.classList.toggle("over", ev === "dragover");
    if (ev !== "drop" || !e.dataTransfer.files.length) return;
    if (d.dataset.view) setPhoto(d.dataset.view, e.dataTransfer.files[0]); else setFiles(e.dataTransfer.files);
  });
}
function pickPhoto(view) {
  const p = $("#file-picker");
  p.onchange = () => { if (p.files[0]) setPhoto(view, p.files[0]); p.value = ""; };
  p.click();
}
function pickModel() {
  const p = $("#model-picker");
  p.onchange = () => { if (p.files.length) setFiles(p.files); p.value = ""; };
  p.click();
}
function setPhoto(view, file) {
  if (!file.type.startsWith("image/")) return;
  state.draft.photos[view] = { file, url: URL.createObjectURL(file) };
  renderStart();
}

/* ---------------------------------------------------------------- boot */
(async function boot() {
  state.jobs = await api("/api/jobs");
  const lit = state.jobs.find((j) => j.unseen) || state.jobs.find((j) => WAITING_FOR_HER.has(j.stage))
    || state.jobs.find((j) => WORKING.has(j.stage));
  state.current = lit ? lit.id : null;
  render();
  const es = new EventSource("/api/events");
  es.onmessage = (m) => { try { upsert(JSON.parse(m.data)); } catch (_) {} };
  state.timer = setInterval(tick, 1000);
})();

// Print Studio part editor: three.js view, selection by colour area or pen outline, cut preview.
// The page talks to it through window.PrintEditor; triangle i here is triangle i on the server.
import * as THREE from "three";
import { OrbitControls } from "/static/vendor/three/addons/controls/OrbitControls.js";

const HIGHLIGHT = new THREE.Color("#0F5C4E");

class Editor {
  constructor(container, { onSelection } = {}) {
    this.el = container;
    this.onSelection = onSelection || (() => {});
    this.tool = "area";          // "area" | "pen"
    this.through = false;        // pen: front surface only, or straight through the model
    this.tolerance = 38;         // colour area: how different a neighbour may be (RGB distance)

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: false });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.el.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(32, 1, 0.001, 100);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f86, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(-1.2, 2.2, 2.4);
    this.scene.add(sun);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;

    this.pickScene = new THREE.Scene();
    this.pickTarget = new THREE.WebGLRenderTarget(1, 1);

    // the pen outline is drawn in an SVG laid over the canvas
    this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    this.svg.setAttribute("class", "lasso");
    this.path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    this.svg.appendChild(this.path);
    this.el.appendChild(this.svg);

    this._bind();
    this._resize();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(this.el);
    this._loop = () => { this.controls.update(); this.renderer.render(this.scene, this.camera); this._raf = requestAnimationFrame(this._loop); };
    this._raf = requestAnimationFrame(this._loop);
  }

  // ------------------------------------------------------------------ geometry
  async load(url, version, faceCount) {
    const [pos, rgb] = await Promise.all([
      fetch(`${url}edit_pos.bin?v=${version}`).then((r) => r.arrayBuffer()),
      fetch(`${url}edit_rgb.bin?v=${version}`).then((r) => r.arrayBuffer()),
    ]);
    const P = new Float32Array(pos), C = new Uint8Array(rgb);
    const F = Math.min(faceCount || P.length / 9, P.length / 9, C.length / 3);
    this.F = F;
    this.baseRGB = C;
    this.sel = new Uint8Array(F);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(P.subarray(0, F * 9), 3));
    geo.computeVertexNormals();
    this.colors = new Float32Array(F * 9);
    geo.setAttribute("color", new THREE.BufferAttribute(this.colors, 3));
    // picking: each triangle drawn in its own flat colour = its index + 1
    const ids = new Uint8Array(F * 9);
    for (let i = 0; i < F; i++) {
      const id = i + 1, r = id & 255, g = (id >> 8) & 255, b = (id >> 16) & 255;
      for (let k = 0; k < 3; k++) { ids[i * 9 + k * 3] = r; ids[i * 9 + k * 3 + 1] = g; ids[i * 9 + k * 3 + 2] = b; }
    }
    const pickGeo = new THREE.BufferGeometry();
    pickGeo.setAttribute("position", geo.getAttribute("position"));
    pickGeo.setAttribute("color", new THREE.BufferAttribute(ids, 3, true));

    if (this.mesh) { this.scene.remove(this.mesh); this.mesh.geometry.dispose(); this.pickScene.remove(this.pickMesh); this.pickMesh.geometry.dispose(); }
    this.mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.78, metalness: 0 }));
    this.scene.add(this.mesh);
    this.pickMesh = new THREE.Mesh(pickGeo, new THREE.MeshBasicMaterial({ vertexColors: true }));
    this.pickScene.add(this.pickMesh);

    this._centroids(P);
    this._adjacency(P);
    this._paint();
    const first = !this.box;
    geo.computeBoundingBox();
    this.box = geo.boundingBox.clone();
    if (first) this.fit();
    this._cutPlane();
    this._emit();
  }

  fit() {
    const s = this.box.getBoundingSphere(new THREE.Sphere());
    this.controls.target.copy(s.center);
    const d = s.radius / Math.sin(THREE.MathUtils.degToRad(this.camera.fov / 2)) * 1.08;
    this.camera.position.copy(s.center).add(new THREE.Vector3(0.55, 0.32, 1).normalize().multiplyScalar(d));
    this.camera.near = d / 100; this.camera.far = d * 10; this.camera.updateProjectionMatrix();
  }

  _centroids(P) {
    const F = this.F, c = new Float32Array(F * 3);
    for (let i = 0; i < F; i++) for (let a = 0; a < 3; a++) c[i * 3 + a] = (P[i * 9 + a] + P[i * 9 + 3 + a] + P[i * 9 + 6 + a]) / 3;
    this.cent = c;
  }

  _adjacency(P) {
    // weld corners that share a position, then link triangles that share an edge (CSR lists)
    const F = this.F;
    let min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < F * 3; i++) for (let a = 0; a < 3; a++) { const x = P[i * 3 + a]; if (x < min[a]) min[a] = x; if (x > max[a]) max[a] = x; }
    const span = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2]) || 1, Q = 100000 / span, K = 131072;
    const vid = new Int32Array(F * 3), keyMap = new Map();
    for (let i = 0; i < F * 3; i++) {
      const key = (Math.round((P[i * 3] - min[0]) * Q) * K + Math.round((P[i * 3 + 1] - min[1]) * Q)) * K + Math.round((P[i * 3 + 2] - min[2]) * Q);
      let id = keyMap.get(key);
      if (id === undefined) { id = keyMap.size; keyMap.set(key, id); }
      vid[i] = id;
    }
    const V = keyMap.size, edgeOwner = new Map(), pairs = [];
    for (let f = 0; f < F; f++) for (let k = 0; k < 3; k++) {
      let a = vid[f * 3 + k], b = vid[f * 3 + (k + 1) % 3];
      if (a > b) [a, b] = [b, a];
      const key = a * V + b, o = edgeOwner.get(key);
      if (o === undefined) edgeOwner.set(key, f); else pairs.push(o, f);
    }
    const deg = new Int32Array(F + 1);
    for (let i = 0; i < pairs.length; i++) deg[pairs[i] + 1]++;
    for (let i = 0; i < F; i++) deg[i + 1] += deg[i];
    const fill = deg.slice(0, F), nb = new Int32Array(pairs.length);
    for (let i = 0; i < pairs.length; i += 2) { nb[fill[pairs[i]]++] = pairs[i + 1]; nb[fill[pairs[i + 1]]++] = pairs[i]; }
    this.adjStart = deg; this.adj = nb;
  }

  // ------------------------------------------------------------------ display
  _paint() {
    const F = this.F, c = this.colors, base = this.baseRGB, sel = this.sel;
    const lin = (u) => { const s = u / 255; return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); };
    const LUT = new Float32Array(256); for (let i = 0; i < 256; i++) LUT[i] = lin(i);
    const below = this._cutY;
    for (let i = 0; i < F; i++) {
      let r = LUT[base[i * 3]], g = LUT[base[i * 3 + 1]], b = LUT[base[i * 3 + 2]];
      if (sel[i]) { r = r * 0.35 + HIGHLIGHT.r * 0.65; g = g * 0.35 + HIGHLIGHT.g * 0.65; b = b * 0.35 + HIGHLIGHT.b * 0.65; }
      if (below !== undefined && this.cent[i * 3 + 1] < below) { r = r * 0.25 + 0.6; g = g * 0.25 + 0.15; b = b * 0.25 + 0.12; }
      for (let k = 0; k < 3; k++) { c[i * 9 + k * 3] = r; c[i * 9 + k * 3 + 1] = g; c[i * 9 + k * 3 + 2] = b; }
    }
    if (this.mesh) this.mesh.geometry.getAttribute("color").needsUpdate = true;
  }

  setCut(frac) {
    if (!this.box) return;
    this._cutFrac = frac;
    this._cutY = frac > 0 ? this.box.min.y + frac * (this.box.max.y - this.box.min.y) : undefined;
    this._cutPlane();
    this._paint();
  }

  _cutPlane() {
    if (this.plane) { this.scene.remove(this.plane); this.plane.geometry.dispose(); this.plane = null; }
    if (this._cutY === undefined || !this.box) return;
    const size = this.box.getSize(new THREE.Vector3()), c = this.box.getCenter(new THREE.Vector3());
    const g = new THREE.PlaneGeometry(size.x * 1.35, size.z * 1.35);
    this.plane = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: 0xd2462f, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false }));
    this.plane.rotation.x = -Math.PI / 2;
    this.plane.position.set(c.x, this._cutY, c.z);
    this.scene.add(this.plane);
  }

  // ------------------------------------------------------------------ selection
  selected() { const out = []; for (let i = 0; i < this.F; i++) if (this.sel[i]) out.push(i); return out; }
  clear() { this.sel.fill(0); this._paint(); this._emit(); }
  grow() {
    const add = [];
    for (let f = 0; f < this.F; f++) if (this.sel[f]) for (let j = this.adjStart[f]; j < this.adjStart[f + 1]; j++) if (!this.sel[this.adj[j]]) add.push(this.adj[j]);
    for (const f of add) this.sel[f] = 1;
    this._paint(); this._emit();
  }
  shrink() {
    const drop = [];
    for (let f = 0; f < this.F; f++) if (this.sel[f]) for (let j = this.adjStart[f]; j < this.adjStart[f + 1]; j++) if (!this.sel[this.adj[j]]) { drop.push(f); break; }
    for (const f of drop) this.sel[f] = 0;
    this._paint(); this._emit();
  }
  _emit() {
    let n = 0; for (let i = 0; i < this.F; i++) n += this.sel[i];
    this.onSelection({ count: n, share: this.F ? n / this.F : 0 });
  }

  _pickRegion(x0, y0, w, h) {
    const W = this.el.clientWidth, H = this.el.clientHeight, pr = this.renderer.getPixelRatio();
    const tw = Math.round(W * pr), th = Math.round(H * pr);
    if (this.pickTarget.width !== tw || this.pickTarget.height !== th) this.pickTarget.setSize(tw, th);
    this.renderer.setRenderTarget(this.pickTarget);
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.render(this.pickScene, this.camera);
    this.renderer.setRenderTarget(null);
    const px = Math.max(0, Math.floor(x0 * pr)), pw = Math.min(tw - px, Math.ceil(w * pr) + 1);
    const pyTop = Math.max(0, Math.floor(y0 * pr)), ph = Math.min(th - pyTop, Math.ceil(h * pr) + 1);
    const buf = new Uint8Array(pw * ph * 4);
    this.renderer.readRenderTargetPixels(this.pickTarget, px, th - pyTop - ph, pw, ph, buf);
    return { buf, px, pyTop, pw, ph, pr };
  }

  _faceAt(x, y) {
    const { buf } = this._pickRegion(x, y, 1, 1);
    const id = buf[0] | (buf[1] << 8) | (buf[2] << 16);
    return id > 0 ? id - 1 : -1;
  }

  selectArea(x, y, subtract) {
    const seed = this._faceAt(x, y);
    if (seed < 0) return;
    const C = this.baseRGB, tol2 = this.tolerance * this.tolerance;
    const r0 = C[seed * 3], g0 = C[seed * 3 + 1], b0 = C[seed * 3 + 2];
    const seen = new Uint8Array(this.F), stack = [seed];
    seen[seed] = 1;
    while (stack.length) {
      const f = stack.pop();
      this.sel[f] = subtract ? 0 : 1;
      for (let j = this.adjStart[f]; j < this.adjStart[f + 1]; j++) {
        const n = this.adj[j];
        if (seen[n]) continue;
        const dr = C[n * 3] - r0, dg = C[n * 3 + 1] - g0, db = C[n * 3 + 2] - b0;
        if (dr * dr + dg * dg + db * db <= tol2) { seen[n] = 1; stack.push(n); }
      }
    }
    this._paint(); this._emit();
  }

  selectOutline(points, subtract) {
    if (points.length < 3) return;
    const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
    const x0 = Math.min(...xs), y0 = Math.min(...ys), x1 = Math.max(...xs), y1 = Math.max(...ys);
    const inside = (x, y) => {
      let c = false;
      for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
        const [xi, yi] = points[i], [xj, yj] = points[j];
        if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
      }
      return c;
    };
    const hit = new Uint8Array(this.F);
    if (this.through) {
      // straight through: every triangle whose centre falls inside the outline, front or back
      const v = new THREE.Vector3(), W = this.el.clientWidth, H = this.el.clientHeight;
      for (let f = 0; f < this.F; f++) {
        v.set(this.cent[f * 3], this.cent[f * 3 + 1], this.cent[f * 3 + 2]).project(this.camera);
        const sx = (v.x + 1) / 2 * W, sy = (1 - v.y) / 2 * H;
        if (sx >= x0 && sx <= x1 && sy >= y0 && sy <= y1 && inside(sx, sy)) hit[f] = 1;
      }
    } else {
      // front surface: the triangles actually visible inside the outline (exact, from the picking image)
      const { buf, px, pyTop, pw, ph, pr } = this._pickRegion(x0, y0, x1 - x0, y1 - y0);
      for (let row = 0; row < ph; row++) for (let col = 0; col < pw; col++) {
        const sx = (px + col) / pr, sy = (pyTop + (ph - 1 - row)) / pr;
        if (!inside(sx, sy)) continue;
        const o = (row * pw + col) * 4, id = buf[o] | (buf[o + 1] << 8) | (buf[o + 2] << 16);
        if (id > 0) hit[id - 1] = 1;
      }
    }
    for (let f = 0; f < this.F; f++) if (hit[f]) this.sel[f] = subtract ? 0 : 1;
    this._paint(); this._emit();
  }

  // ------------------------------------------------------------------ input
  _bind() {
    const el = this.renderer.domElement;
    let down = null, pts = null;
    const pos = (e) => { const r = el.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    el.addEventListener("contextmenu", (e) => e.preventDefault());
    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      down = pos(e);
      if (this.tool === "pen") {
        pts = [down];
        el.setPointerCapture(e.pointerId);
        this.controls.enabled = false;
      }
    });
    el.addEventListener("pointermove", (e) => {
      if (!pts) return;
      const p = pos(e), last = pts[pts.length - 1];
      if (Math.hypot(p[0] - last[0], p[1] - last[1]) > 2) pts.push(p);
      this.path.setAttribute("d", "M" + pts.map((q) => q.join(" ")).join(" L") + " Z");
    });
    el.addEventListener("pointerup", (e) => {
      if (e.button !== 0 || !down) return;
      const p = pos(e), subtract = e.altKey || e.ctrlKey;
      if (pts) {
        if (pts.length > 4) this.selectOutline(pts, subtract);
        pts = null;
        this.path.setAttribute("d", "");
        this.controls.enabled = true;
      } else if (this.tool === "area" && Math.hypot(p[0] - down[0], p[1] - down[1]) < 5) {
        this.selectArea(p[0], p[1], subtract);    // a click, not a drag to turn the model
      }
      down = null;
    });
  }

  setTool(tool) {
    this.tool = tool;
    // with the pen, the left button draws; turning the model moves to the right button
    this.controls.mouseButtons = tool === "pen"
      ? { LEFT: null, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE }
      : { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
    this.el.classList.toggle("pen", tool === "pen");
  }

  _resize() {
    const w = this.el.clientWidth || 1, h = this.el.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  destroy() {
    cancelAnimationFrame(this._raf);
    this._ro.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.pickTarget.dispose();
    this.el.innerHTML = "";
  }
}

window.PrintEditor = {
  mount: (el, opts) => new Editor(el, opts),
};
window.dispatchEvent(new Event("printeditor-ready"));

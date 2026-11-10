"""Part edits on the AI model, before it is made printable.

The editor works on the model as generated (glTF axes: Y up, millimetres don't matter yet). Each edit
names the triangles it acts on by their index in the mesh *as it was just before that edit*, so the
edit list replays deterministically on the original model; undo = replay without the last edit.

Edits (dicts):
  {"op": "remove",    "faces": [...]}                       delete these triangles
  {"op": "keep",      "faces": [...]}                       delete every other triangle
  {"op": "scale",     "faces": [...], "factor": 1.3}        grow/shrink the part around where it attaches
  {"op": "paint",     "faces": [...], "rgb": "#RRGGBB"}     recolour the part
  {"op": "cut_below", "frac": 0.08}                         remove everything below this fraction of the height

Holes left by remove / keep / cut are closed later by meshprep's solid rebuild (open regions are
filled), so the result is still one solid piece; scaling moves the part's vertices, and the triangles
around it stretch with them, so nothing tears.
"""
import numpy as np


def hex_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.uint8)


def apply(vertices, faces, rgb, edit):
    v, f, c = np.asarray(vertices, float).copy(), np.asarray(faces, np.int64), np.asarray(rgb, np.uint8).copy()
    op = edit["op"]
    sel = np.zeros(len(f), bool)
    if "faces" in edit:
        idx = np.asarray(edit["faces"], np.int64)
        sel[idx[(idx >= 0) & (idx < len(f))]] = True
        sel |= _twins(v, f, sel)
    if op == "remove":
        return _keep(v, f, c, ~sel)
    if op == "keep":
        return _keep(v, f, c, sel)
    if op == "paint":
        c[sel] = hex_rgb(edit["rgb"])
        return v, f, c
    if op == "scale":
        verts = np.unique(f[sel])
        if len(verts) == 0:
            return v, f, c
        anchor = _anchor(f, sel, v)
        v[verts] = anchor + (v[verts] - anchor) * float(edit["factor"])
        return v, f, c
    if op == "cut_below":
        y = v[:, 1]
        cut = y.min() + float(edit["frac"]) * (y.max() - y.min())
        return _keep(v, f, c, v[f][:, :, 1].mean(axis=1) >= cut)
    raise ValueError(f"unknown edit {op}")


def replay(vertices, faces, rgb, edits):
    for e in edits:
        vertices, faces, rgb = apply(vertices, faces, rgb, e)
    return vertices, faces, rgb


def _keep(v, f, c, mask):
    f, c = f[mask], c[mask]
    used = np.unique(f)
    remap = np.full(len(v), -1, np.int64)
    remap[used] = np.arange(len(used))
    return v[used], remap[f], c


def _twins(v, f, sel, reach=0.75):
    """The generated models are often double-skinned: right under the visible surface sits a second,
    inward-facing layer that the editor can't see or click. Painting or removing only the visible layer
    lets the hidden one show through later (the solid rebuild takes colour from whichever skin is
    nearest), so a selection also takes every opposite-facing triangle lying within `reach` of an edge
    length of a selected one. On a genuinely thin part this takes its other side too, which is wanted."""
    if not sel.any() or sel.all():
        return np.zeros(len(f), bool)
    from scipy.spatial import cKDTree
    tri = v[f]
    cen = tri.mean(axis=1)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-20
    edge = float(np.median(np.linalg.norm(tri[sel, 1] - tri[sel, 0], axis=1)))
    cand = np.where(~sel)[0]
    near = cKDTree(cen[sel]).query(cen[cand], distance_upper_bound=reach * edge)
    hit = np.isfinite(near[0])
    src = np.where(sel)[0]
    out = np.zeros(len(f), bool)
    c_hit = cand[hit]
    out[c_hit[(n[c_hit] * n[src[near[1][hit]]]).sum(axis=1) < -0.5]] = True
    return out


def _anchor(f, sel, v):
    """Where the part attaches: the middle of its border with the rest of the model (the vertices shared
    by selected and unselected triangles). A part with no border (a loose piece, or everything) scales
    around its own centre."""
    inside = np.unique(f[sel])
    outside = np.unique(f[~sel])
    border = np.intersect1d(inside, outside, assume_unique=True)
    pts = v[border] if len(border) else v[inside]
    return pts.mean(axis=0)


def to_bins(vertices, faces, rgb, folder):
    """The editor's geometry: one position triple per triangle corner (float32) and one colour per
    triangle (uint8), in triangle order, so triangle i in the browser is triangle i here."""
    tri = np.asarray(vertices, np.float32)[np.asarray(faces)]
    tri.tofile(folder / "edit_pos.bin")
    np.asarray(rgb, np.uint8).tofile(folder / "edit_rgb.bin")
    return len(faces)

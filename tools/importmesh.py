"""Open 3D files she already has (downloaded, or from another app) as a Print Studio model.

    load(folder) -> Imported(vertices, faces, rgb, info)

`folder` holds what she uploaded: one model file, or a model with its companions (an OBJ with its .mtl and
texture, a .gltf with its .bin), or a .zip of those. The result is in the editor's frame (glTF axes: Y up,
front +Z), one colour per triangle, so it continues exactly like a generated model: review, edit, size,
colours, checks, print file.

Formats: STL, 3MF, OBJ, GLB/GLTF, PLY, OFF, ZIP.
  * 3MF is read here, not by trimesh: painted multicolour projects (Creality Print, Bambu Studio, Orca,
    MakerWorld downloads) keep their colours — the per-triangle `paint_color` codes and the project's
    filament colours — and the production-extension layout (objects in separate files) is followed.
  * STL / PLY / OFF / 3MF come from the printing world: Z up, millimetres. GLB / GLTF: Y up, metres.
    OBJ: Y up (Blender's default). A file that still comes in lying down is turned on the review step.
"""
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

MODEL_EXT = {".3mf", ".glb", ".gltf", ".obj", ".stl", ".ply", ".off"}
COMPANION_EXT = {".mtl", ".bin", ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp"}
ACCEPTED_EXT = MODEL_EXT | COMPANION_EXT | {".zip"}
PREFERENCE = [".3mf", ".glb", ".gltf", ".obj", ".ply", ".stl", ".off"]   # which file is "the model"
MAX_FACES = 400_000          # more than enough detail for a 0.4 mm nozzle; keeps the editor fast
MAX_UNZIPPED = 600 * 2**20
UNCOLOURED = (245, 243, 238)       # white: the most likely filament for a model without colours


class FileProblem(Exception):
    """A problem with her file, worded for her."""


@dataclass
class Imported:
    vertices: np.ndarray          # (N,3) float, glTF axes (Y up)
    faces: np.ndarray             # (M,3) int
    rgb: np.ndarray               # (M,3) uint8
    info: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------------------ entry
def load(folder, keep_axes=False, max_faces=MAX_FACES):
    """keep_axes: leave the file's own axes and give millimetres (for the CAD converter); otherwise the
    editor's frame (glTF axes). max_faces=None keeps every triangle."""
    folder = Path(folder)
    for z in list(folder.glob("*.zip")):
        _unzip(z, folder / z.stem)
    candidates = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in MODEL_EXT]
    if not candidates:
        raise FileProblem("No 3D model found. Use an STL, 3MF, OBJ, GLB, PLY or OFF file (or a .zip of one).")
    main = min(candidates, key=lambda p: (PREFERENCE.index(p.suffix.lower()), -p.stat().st_size))
    return load_file(main, keep_axes=keep_axes, max_faces=max_faces)


def load_file(main, keep_axes=False, max_faces=MAX_FACES):
    """One model file (its companions, like an OBJ's .mtl and texture, next to it)."""
    main = Path(main)
    ext = main.suffix.lower()
    try:
        if ext == ".3mf":
            v, f, rgb, info = _load_3mf(main)
            y_up = False
        else:
            v, f, rgb, info = _load_trimesh(main)
            y_up = ext in (".glb", ".gltf", ".obj")   # OBJ mostly comes from 3D art tools (Blender: Y up)
    except FileProblem:
        raise
    except Exception as e:  # noqa: BLE001
        raise FileProblem(f"This file couldn't be read ({main.name}). It may be damaged or use a format "
                          "variant that isn't supported.") from e
    if len(f) == 0:
        raise FileProblem("The file has no surfaces in it (it may hold only points or lines).")

    v = np.asarray(v, float)
    if keep_axes:
        unit = info.pop("unit_mm", 1000.0 if ext in (".glb", ".gltf") else 1.0)
        v = v * unit
        e = v.max(0) - v.min(0)
        info.update(format=ext.lstrip(".").upper(), file=main.name, faces_in_file=int(len(f)),
                    width_mm=round(float(e[0]), 3), depth_mm=round(float(e[1]), 3), height_mm=round(float(e[2]), 3))
        return Imported(v, np.asarray(f, np.int64), np.asarray(rgb, np.uint8), info)
    if not y_up:                                   # printer Z up -> glTF Y up: (x, y, z) -> (x, z, -y)
        v = v @ np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float).T
    unit = info.pop("unit_mm", 1000.0 if ext in (".glb", ".gltf") else 1.0)   # glTF is in metres
    ext_mm = (v.max(0) - v.min(0)) * unit
    info.update(format=ext.lstrip(".").upper(), file=main.name, faces_in_file=int(len(f)),
                width_mm=round(float(ext_mm[0]), 1), height_mm=round(float(ext_mm[1]), 1),
                depth_mm=round(float(ext_mm[2]), 1))
    if max_faces and len(f) > max_faces:
        v, f, rgb = _simplify(v, f, rgb, max_faces)
        info["simplified_to"] = int(len(f))
    return Imported(v, np.asarray(f, np.int64), np.asarray(rgb, np.uint8), info)


def _unzip(path, dest):
    try:
        with zipfile.ZipFile(path) as z:
            total = 0
            for m in z.infolist():
                name = Path(m.filename)
                if m.is_dir() or name.is_absolute() or ".." in name.parts:
                    continue
                if name.suffix.lower() not in MODEL_EXT | COMPANION_EXT:
                    continue
                total += m.file_size
                if total > MAX_UNZIPPED:
                    raise FileProblem("The .zip is too big once unpacked (over 600 MB).")
                out = dest / name
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(m) as src, open(out, "wb") as dst:
                    dst.write(src.read())
    except zipfile.BadZipFile as e:
        raise FileProblem("The .zip file is damaged and couldn't be opened.") from e


# ------------------------------------------------------------------------------------------ trimesh formats
def _load_trimesh(path):
    import meshprep
    scene = trimesh.load(str(path), force="scene")
    meshes, colours, coloured = [], [], False
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        geom = scene.geometry[name]
        if not isinstance(geom, trimesh.Trimesh) or len(geom.faces) == 0:
            continue
        g = geom.copy()
        g.apply_transform(transform)
        meshes.append(g)
        c = meshprep._face_colours(geom)
        colours.append(c)
        coloured |= _has_colour(geom)
    if not meshes:
        raise FileProblem("The file has no surfaces in it (it may hold only points or lines).")
    mesh = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    rgb = np.concatenate(colours)
    if not coloured:
        rgb[:] = UNCOLOURED
    return np.asarray(mesh.vertices), np.asarray(mesh.faces), rgb, {"coloured": bool(coloured)}


def _has_colour(geom):
    vis = geom.visual
    if isinstance(vis, trimesh.visual.TextureVisuals):
        mat = vis.material
        return any(getattr(mat, a, None) is not None for a in ("baseColorTexture", "image")) or \
            getattr(mat, "baseColorFactor", None) is not None
    if vis.kind in ("face", "vertex"):
        c = np.asarray(vis.face_colors)[:, :3]
        return bool(len(c)) and not np.all(c == (102, 102, 102))      # trimesh's own default grey
    return False


# ------------------------------------------------------------------------------------------ 3MF
NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
NS_MAT = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
UNITS_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}


def _load_3mf(path):
    from lxml import etree
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    root_name = "3D/3dmodel.model"
    if "_rels/.rels" in names:
        m = re.search(rb'Target="/?([^"]+\.model)"', z.read("_rels/.rels"))
        if m and m.group(1).decode() in names:
            root_name = m.group(1).decode()
    if root_name not in names:
        found = [n for n in names if n.lower().endswith(".model")]
        if not found:
            raise FileProblem("This 3MF file has no model inside.")
        root_name = found[0]

    filament = _filament_colours(z, names)
    docs, unit = {}, 1.0

    def doc(name):
        name = name.lstrip("/")
        if name not in docs:
            docs[name] = etree.fromstring(z.read(name), parser=etree.XMLParser(huge_tree=True))
        return docs[name]

    root = doc(root_name)
    unit = UNITS_MM.get(root.get("unit", "millimeter"), 1.0)
    obj_extruder = _object_extruders(z, names)

    verts, faces, rgb, painted_any, coloured_any = [], [], [], False, False
    offset = 0

    def emit(model_name, obj_id, transform, extruder):
        nonlocal offset, painted_any, coloured_any
        d = doc(model_name)
        obj = d.find(f".//{{{NS_CORE}}}object[@id='{obj_id}']")
        if obj is None:
            return
        ext = obj_extruder.get((model_name, obj_id), extruder)
        mesh = obj.find(f"{{{NS_CORE}}}mesh")
        if mesh is not None:
            vs = mesh.find(f"{{{NS_CORE}}}vertices")
            ts = mesh.find(f"{{{NS_CORE}}}triangles")
            v = np.array([[float(e.get("x")), float(e.get("y")), float(e.get("z"))] for e in vs], float)
            tri_el = list(ts)
            t = np.array([[int(e.get("v1")), int(e.get("v2")), int(e.get("v3"))] for e in tri_el], np.int64)
            if len(v) == 0 or len(t) == 0:
                return
            v = np.c_[v, np.ones(len(v))] @ transform
            colours, painted, coloured = _triangle_colours(d, obj, tri_el, filament, ext)
            painted_any |= painted
            coloured_any |= coloured
            verts.append(v[:, :3])
            faces.append(t + offset)
            rgb.append(colours)
            offset += len(v)
            return
        comps = obj.find(f"{{{NS_CORE}}}components")
        for c in (comps if comps is not None else []):
            child_model = c.get(f"{{{NS_PROD}}}path", "/" + model_name).lstrip("/")
            emit(child_model, c.get("objectid"), _matrix(c.get("transform")) @ transform, ext)

    for item in root.find(f"{{{NS_CORE}}}build"):
        model_name = item.get(f"{{{NS_PROD}}}path", "/" + root_name).lstrip("/")
        emit(model_name, item.get("objectid"), _matrix(item.get("transform")), 1)

    if not faces:
        raise FileProblem("This 3MF file has no model inside.")
    rgb = np.concatenate(rgb)
    info = {"coloured": bool(coloured_any), "painted": bool(painted_any), "unit_mm": 1.0}   # scaled below
    if painted_any and filament:
        used = sorted({tuple(c) for c in rgb.tolist()}, key=lambda c: -int((rgb == c).all(1).sum()))
        info["palette"] = ["#%02X%02X%02X" % tuple(c) for c in used[:4]]
    return np.concatenate(verts) * unit, np.concatenate(faces), rgb, info


def _matrix(text):
    """3MF transform 'm00 m01 m02 m10 ... m32' (row vectors) as a 4x4 matrix for [x y z 1] @ M."""
    m = np.eye(4)
    if text:
        n = [float(x) for x in text.split()]
        if len(n) == 12:
            m[:, :3] = np.array(n).reshape(4, 3)
    return m


def _filament_colours(z, names):
    for n in ("Metadata/project_settings.config", "Metadata/Slic3r_PE.config"):
        if n in names:
            text = z.read(n).decode("utf-8", "ignore")
            try:
                cols = json.loads(text).get("filament_colour")
            except json.JSONDecodeError:
                m = re.search(r"filament_colour\s*=\s*(.+)", text)
                cols = m.group(1).split(";") if m else None
            if cols:
                return [_hex_rgb(c) for c in cols if _hex_rgb(c) is not None]
    return []


def _object_extruders(z, names):
    """Per-object extruder from the slicer's model_settings (Bambu/Orca/Creality); keyed like emit()."""
    out = {}
    if "Metadata/model_settings.config" not in names:
        return out
    text = z.read("Metadata/model_settings.config").decode("utf-8", "ignore")
    for m in re.finditer(r'<object id="(\d+)">(.*?)</object>', text, re.S):
        e = re.search(r'key="extruder" value="(\d+)"', m.group(2))
        if e:
            out[("3D/3dmodel.model", m.group(1))] = int(e.group(1))
    return out


def _hex_rgb(h):
    h = str(h).strip().lstrip("#")
    if len(h) not in (6, 8) or not re.fullmatch(r"[0-9A-Fa-f]+", h):
        return None
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _triangle_colours(d, obj, tri_el, filament, extruder):
    """Colours per triangle: painted filament (paint_color / mmu_segmentation), else a material colour
    (basematerials / colorgroup), else the object's filament, else plain grey."""
    n = len(tri_el)
    groups = {}
    for bm in d.iter(f"{{{NS_CORE}}}basematerials"):
        groups[bm.get("id")] = [_hex_rgb(b.get("displaycolor")) for b in bm]
    for cg in d.iter(f"{{{NS_MAT}}}colorgroup"):
        groups[cg.get("id")] = [_hex_rgb(c.get("color")) for c in cg]

    def fil(i):
        i = max(1, int(i))
        return filament[i - 1] if 0 < i <= len(filament) else None

    base = fil(extruder) if filament else None
    opid, opidx = obj.get("pid"), obj.get("pindex", "0")
    if base is None and opid in groups:
        g = groups[opid]
        base = g[int(opidx)] if int(opidx) < len(g) else None
    out = np.tile(np.array(base or UNCOLOURED, np.uint8), (n, 1))
    coloured, painted = base is not None, False
    for k, e in enumerate(tri_el):
        code = e.get("paint_color") or e.get("{http://schemas.slic3r.org/3mf/2017/06}mmu_segmentation")
        if code and filament:
            state = _paint_state(code)
            if state:
                c = fil(state)
                if c is not None:
                    out[k] = c
                    painted = coloured = True
                    continue
        pid = e.get("pid") or opid
        if pid in groups:
            g = groups[pid]
            idx = int(e.get("p1", opidx or 0))
            if idx < len(g) and g[idx] is not None:
                out[k] = g[idx]
                coloured = True
    return out, painted, coloured


def _paint_state(code):
    """Decode a PrusaSlicer/Bambu/Orca/Creality paint code (a TriangleSelector tree written as hex nibbles,
    read from the end) and return the filament that covers most of the triangle (0 = not painted)."""
    try:
        nibbles = iter([int(ch, 16) for ch in reversed(code.strip())])
    except ValueError:
        return 0
    weight = {}

    def node(w):
        c = next(nibbles)
        split = c & 0b11
        if split == 0:
            st = c >> 2
            if st == 3:
                st = next(nibbles) + 3
            weight[st] = weight.get(st, 0.0) + w
            return
        for _ in range(split + 1):
            node(w / (split + 1))

    try:
        node(1.0)
    except StopIteration:
        pass
    if not weight:
        return 0
    return max(weight, key=weight.get)


# ------------------------------------------------------------------------------------------ size
def _simplify(v, f, rgb, target):
    """Too many triangles for comfortable editing: reduce, then carry colours over by nearest triangle."""
    import fast_simplification
    from scipy.spatial import cKDTree
    v2, f2 = fast_simplification.simplify(np.asarray(v, np.float32), np.asarray(f, np.int32),
                                          target_reduction=1.0 - target / len(f))
    src_c = v[f].mean(axis=1)
    _, idx = cKDTree(src_c).query(v2[f2].mean(axis=1), k=1)
    return v2.astype(float), f2.astype(np.int64), np.asarray(rgb)[idx]

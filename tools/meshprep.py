"""Turn a raw AI mesh (GLB from TRELLIS.2 / Pixal3D) into a printable solid in millimetres.

    load_textured(glb)        -> mesh + one colour per triangle (sampled from the texture)
    prepare(mesh, colours, height_mm, ...) -> PrintModel: watertight solid on Z=0, front facing -Y,
                                              colours carried over, plus a report of checks

Repair is done by voxelising: the model is filled as a grid of small cubes (finer than the nozzle),
small holes are sealed, the inside filled, the bottom cut flat, and a smooth closed surface rebuilt
(marching cubes). This always gives one watertight solid, whatever the AI mesh looked like.
"""
from dataclasses import dataclass, field

import numpy as np
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree

BUILD_LIMIT_MM = 290.0        # K2 Pro 300 mm, minus a margin
NOZZLE_MM = 0.4
FRAGILE_MM = 1.2              # thinner than ~3 lines: prints, but breaks easily
UNPRINTABLE_MM = 0.8          # thinner than 2 lines: likely missing or broken in the print
SEAL_STEPS_MM = (2.0, 4.0, 8.0)        # hole sizes tried when filling the inside
MAX_SEAL_MM = SEAL_STEPS_MM[-1]


@dataclass
class PrintModel:
    vertices: np.ndarray      # (N,3) mm
    faces: np.ndarray         # (M,3)
    face_rgb: np.ndarray      # (M,3) uint8, colour from the texture
    report: dict = field(default_factory=dict)

    def trimesh(self):
        return trimesh.Trimesh(self.vertices, self.faces, process=False)


# ---------------------------------------------------------------------------------------------
def load_textured(path):
    """GLB -> one Trimesh (glTF axes, Y up) and a uint8 RGB colour per face from its texture."""
    scene = trimesh.load(path, force="scene")
    meshes, colours = [], []
    for name, geom in scene.geometry.items():
        transform = scene.graph.get(name)[0] if name in scene.graph.nodes else np.eye(4)
        g = geom.copy()
        g.apply_transform(transform)
        meshes.append(g)
        colours.append(_face_colours(geom))
    mesh = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    return trimesh.Trimesh(mesh.vertices, mesh.faces, process=False), np.concatenate(colours)


def _face_colours(geom):
    visual = geom.visual
    n = len(geom.faces)
    if isinstance(visual, trimesh.visual.TextureVisuals) and visual.uv is not None:
        mat = visual.material
        image = getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)
        if image is not None:
            tex = np.asarray(image.convert("RGB"))
            h, w = tex.shape[:2]
            uv = visual.uv[geom.faces]                                  # (M,3,2)
            samples = np.concatenate([uv, uv.mean(axis=1, keepdims=True)], axis=1)  # 3 corners + centre
            x = np.clip((samples[..., 0] % 1.0) * (w - 1), 0, w - 1).round().astype(int)
            y = np.clip((1.0 - samples[..., 1] % 1.0) * (h - 1), 0, h - 1).round().astype(int)
            rgb = tex[y, x].astype(float)                               # (M,4,3)
            # the centre counts double: corners sit on UV-island borders more often
            out = (rgb[:, :3].sum(axis=1) + 2 * rgb[:, 3]) / 5
            factor = getattr(mat, "baseColorFactor", None)
            if factor is not None:
                out *= np.asarray(factor[:3], float) / (255.0 if np.max(factor) > 1 else 1.0)
            return np.clip(out, 0, 255).astype(np.uint8)
    if hasattr(visual, "face_colors") and visual.kind is not None:
        return np.asarray(visual.face_colors)[:, :3].astype(np.uint8)
    return np.full((n, 3), 200, np.uint8)


# ---------------------------------------------------------------------------------------------
def prepare(mesh, face_rgb, height_mm, *, y_up=True, pitch_mm=None, cut_mm=None, target_faces=250_000,
            close_mm=0.9, keep_surface=False, log=print):
    """Scale, orient and rebuild the mesh as one watertight solid standing on Z=0.

    keep_surface: a file she imported that is already a closed solid standing on a flat bottom keeps its
    exact surface (sharp edges, fine detail) instead of being rebuilt from voxels; the checks still run."""
    src = mesh.copy()
    if y_up:                                   # glTF: Y up, front +Z  ->  printer: Z up, front -Y
        src.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    levelled = _level(src)                     # photo models come tilted by the camera's angle
    src.apply_translation(-src.bounds.mean(axis=0))
    scale = height_mm / src.extents[2]
    src.apply_scale(scale)
    src.apply_translation([0, 0, -src.bounds[0, 2]])
    size = src.extents
    report = {"height_mm": round(float(size[2]), 1), "width_mm": round(float(size[0]), 1),
              "depth_mm": round(float(size[1]), 1), "levelled_deg": round(levelled, 1), "warnings": []}
    if max(size) > BUILD_LIMIT_MM:
        report["warnings"].append(f"Too big for the K2 Pro: {max(size):.0f} mm on its longest side (max {BUILD_LIMIT_MM:.0f}).")

    # --- drop tiny loose fragments before voxelising (they would become floating specks)
    face_rgb = np.asarray(face_rgb)
    comp = trimesh.graph.connected_component_labels(src.face_adjacency, node_count=len(src.faces))
    if comp.max() > 0:
        tri = src.triangles
        diag = np.zeros(comp.max() + 1)
        for c in range(comp.max() + 1):
            pts = tri[comp == c].reshape(-1, 3)
            diag[c] = np.linalg.norm(pts.max(0) - pts.min(0))
        keep_comp = diag >= 0.04 * diag.max()
        mask = keep_comp[comp]
        report["fragments_removed"] = int((~keep_comp).sum())
        src = src.submesh([np.where(mask)[0]], append=True)
        face_rgb = face_rgb[mask]

    # --- voxelise: surface cubes -> seal small holes -> fill inside
    pitch = pitch_mm or float(np.clip(max(size) / 420.0, 0.15, 0.5))
    log(f"  voxelising at {pitch:.2f} mm ...")
    surface, lo = _voxelize(src, pitch)
    pad = int(np.ceil(MAX_SEAL_MM / 2 / pitch)) + 4   # room for the hole sealing to grow outward
    grid = np.pad(surface, pad)
    del surface
    origin = lo - pad * pitch
    solid, seal_mm = _fill_solid(grid, pitch, log)
    report["holes_sealed_up_to_mm"] = seal_mm

    # --- flat bottom: remove the lowest layer(s) so the model stands on a flat face
    filled_layers = np.where(solid.any(axis=(0, 1)))[0]
    footprint_mm2 = float(solid.any(axis=2).sum() * pitch * pitch)
    keep = False
    if keep_surface and src.is_volume:
        natural = float(solid[:, :, filled_layers[0]].sum() * pitch * pitch)
        keep = natural >= max(40.0, 0.08 * footprint_mm2)
    report["kept_surface"] = keep
    cut = cut_mm if cut_mm is not None else max(0.6, 0.006 * size[2])
    cut_layers = max(1, int(round(cut / pitch)))
    # adaptive: an uneven underside (photo models) gets cut a little deeper until the base has a real
    # footprint (60% of the widest layer near the bottom), at most ~4% of the height
    if cut_mm is None:
        z0 = filled_layers[0]
        max_layers = max(cut_layers, int(round(0.04 * size[2] / pitch)))
        areas = solid[:, :, z0:z0 + max_layers + 1].sum(axis=(0, 1))
        enough = np.where(areas >= 0.6 * areas.max())[0]
        if len(enough):
            cut_layers = max(cut_layers, int(enough[0]))
    if keep:                                   # it already stands flat: nothing to cut
        cut_layers = 0
    report["bottom_cut_mm"] = round(cut_layers * pitch, 2)
    solid[:, :, : filled_layers[0] + cut_layers] = False
    contact_mm2 = float(solid[:, :, filled_layers[0] + cut_layers].sum() * pitch * pitch)
    report["flat_bottom_mm2"] = round(contact_mm2, 1)
    if contact_mm2 < max(40.0, 0.08 * footprint_mm2):
        report["warnings"].append(f"Small contact with the bed ({contact_mm2:.0f} mm²): it may tip over or come loose. "
                                  "A base, a brim or supports are recommended.")

    # --- keep the main solid; separate solids would print as loose pieces
    labels, n = ndimage.label(solid)
    if n > 1:
        counts = np.bincount(labels.ravel())[1:]
        big = np.where(counts >= 0.002 * counts.max())[0] + 1
        report["separate_pieces"] = int(len(big))
        if len(big) > 1:
            report["warnings"].append(f"The model is {len(big)} separate pieces that don't touch: they will print "
                                      "loose or need supports.")
        solid = np.isin(labels, big)

    # --- printability: parts thinner than a few nozzle widths
    report.update(_thin_parts(solid, pitch, origin, size[2]))
    if report["unprintable_mm3"] > 1:
        report["warnings"].append(f"Some parts are thinner than {UNPRINTABLE_MM} mm ({report['thin_where']}): "
                                  "they may not print. Make the model bigger or the parts thicker.")
    elif report["fragile_mm3"] > 5:
        report["warnings"].append(f"Some parts are thin ({report['thin_where']}): they will print but break easily.")

    if keep:
        out = src.copy()
        out.apply_translation([0, 0, -out.bounds[0, 2]])
        return _finish(out, np.asarray(face_rgb), report, pitch, scale)

    # --- rebuild a smooth closed surface
    log("  rebuilding the surface ...")
    from skimage import measure
    smooth = ndimage.gaussian_filter(solid.astype(np.float32), sigma=0.7)
    verts, faces, _, _ = measure.marching_cubes(smooth, level=0.5)
    verts = verts * pitch + origin
    out = trimesh.Trimesh(verts, faces[:, ::-1], process=True)
    if not out.is_volume:
        out.fix_normals()
    # remove the grid's contour ripples; Taubin smoothing keeps the volume (vertices move, topology doesn't)
    trimesh.smoothing.filter_taubin(out, lamb=0.5, nu=-0.53, iterations=12)
    out = _simplify(out, target_faces, pitch, log)

    # --- carry the colours over, before the model is lowered onto the bed (both still in src's frame)
    idx = _colour_source(src, out)
    out.apply_translation([0, 0, -out.bounds[0, 2]])
    return _finish(out, np.asarray(face_rgb)[idx], report, pitch, scale)


def _finish(out, rgb, report, pitch, scale):
    size = out.extents                         # the real printed size, after the bottom cut
    report.update(height_mm=round(float(size[2]), 1), width_mm=round(float(size[0]), 1),
                  depth_mm=round(float(size[1]), 1),
                  watertight=bool(out.is_watertight), faces=int(len(out.faces)),
                  volume_cm3=round(float(out.volume) / 1000.0, 1) if out.is_watertight else None,
                  pitch_mm=round(pitch, 3), scale=round(float(scale), 4))
    return PrintModel(np.asarray(out.vertices), np.asarray(out.faces), rgb, report)


def _colour_source(src, out, k=16):
    """For each rebuilt triangle, the original triangle its colour comes from: the nearest one that faces
    the same way. The AI models are often double-skinned, with an inward-facing inner layer carrying junk
    texture colours right under the visible surface; taking simply the nearest triangle picked that layer
    about half the time, which painted tan and pink blotches over the whole model. The rebuilt surface
    faces outward, so the visible skin is the one whose normal agrees with it."""
    tree = cKDTree(src.triangles_center)
    dist, cand = tree.query(out.triangles_center, k=k)
    agree = np.einsum("nkd,nd->nk", src.face_normals[cand], out.face_normals) > 0.2
    first = np.argmax(agree, axis=1)                 # nearest agreeing candidate (k results are sorted)
    pick = cand[np.arange(len(cand)), first]
    none = ~agree.any(axis=1)
    pick[none] = cand[none, 0]                       # no agreeing triangle nearby: fall back to the nearest
    return pick


def _voxelize(mesh, pitch, chunk=4000):
    """Surface voxels, a few thousand triangles at a time. trimesh's voxelized() subdivides the whole mesh
    at once and peaked at 24 GB on a 12 cm figure; this stays at a few hundred MB.
    Voxel (i, j, k) is centred at lo + (i, j, k) * pitch."""
    from trimesh.remesh import subdivide_to_size
    lo = mesh.bounds[0] - pitch
    shape = np.ceil((mesh.bounds[1] + pitch - lo) / pitch).astype(int) + 1
    grid = np.zeros(shape, dtype=bool)
    verts, faces = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    for start in range(0, len(faces), chunk):
        part = faces[start:start + chunk]
        used = np.unique(part)
        remap = np.zeros(len(verts), dtype=np.int64)
        remap[used] = np.arange(len(used))
        v, _ = subdivide_to_size(verts[used], remap[part], max_edge=pitch * 0.5, max_iter=60)
        idx = np.clip(np.round((v - lo) / pitch).astype(np.int64), 0, shape - 1)
        grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return grid, lo


def _level(mesh, min_deg=1.0, max_deg=40.0):
    """Stand the model on its base. Pixal3D builds photo models in the front photo's camera, so they come
    tilted by however much the phone looked down. Take the largest flat face of the convex hull that points
    roughly down (the base's underside) and turn the model so it points straight down. Tilts outside
    1-40 degrees are left alone, so a model is never laid on its side. Returns the correction in degrees."""
    hull = mesh.convex_hull
    candidates = [(hull.area_faces[idx].sum(), n) for idx, n in zip(hull.facets, hull.facets_normal) if n[2] < -0.5]
    if not candidates:
        return 0.0
    _, n = max(candidates, key=lambda t: t[0])
    tilt = float(np.degrees(np.arccos(np.clip(-n[2], -1.0, 1.0))))
    if not (min_deg <= tilt <= max_deg):
        return 0.0
    axis = np.cross(n, [0.0, 0.0, -1.0])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.radians(tilt), axis / np.linalg.norm(axis),
                                                                 mesh.centroid))
    return tilt


def _fill_solid(surface, pitch, log):
    """Inside of a surface that may have holes: grow the surface by r to seal holes up to ~2r, flood the
    outside from the grid border, grow that outside back by r; everything else is solid. If the result is
    still a thin shell (a hole bigger than 2r), retry with a larger r."""
    # memory: integer chamfer distances (int32) instead of float64 Euclidean ones, and every working
    # array is dropped as soon as it has been used (a 500^3 grid would otherwise hold several GB at once)
    shell_volume = int(surface.sum())
    solid = surface
    for seal_mm in SEAL_STEPS_MM:
        r = max(1, int(round(seal_mm / 2 / pitch)))
        sealed = ndimage.distance_transform_cdt(~surface, metric="chessboard") <= r
        labels, _ = ndimage.label(~sealed)
        del sealed
        border = np.unique(np.concatenate([labels[[0, -1]].ravel(), labels[:, [0, -1]].ravel(),
                                           labels[:, :, [0, -1]].ravel()]))
        outside_core = np.isin(labels, border[border > 0])
        del labels
        outside = ndimage.distance_transform_cdt(~outside_core, metric="chessboard") <= r
        del outside_core
        solid = ~outside | surface
        del outside
        if int(solid.sum()) > 3 * shell_volume:   # clearly filled, not just the shell
            return solid, seal_mm
        log(f"  still hollow after sealing {seal_mm:.0f} mm holes; trying larger")
    log("  big opening (often an open bottom): filling by visibility instead")
    return _fill_by_visibility(surface), -1.0


def _fill_by_visibility(surface):
    """Inside test for models with a big opening (photo models usually have no bottom): a voxel is outside
    when it can see the edge of the grid, unblocked by the surface, in at least two of the six axis
    directions. The interior sees out through the opening in at most one direction and is filled; air
    between legs or under a belly sees out sideways in several and stays empty."""
    escapes = np.zeros(surface.shape, dtype=np.uint8)
    for axis in range(3):
        blocked_ahead = np.logical_or.accumulate(surface, axis=axis)              # surface somewhere before
        escapes += ~blocked_ahead
        flipped = np.flip(surface, axis=axis)
        escapes += np.flip(~np.logical_or.accumulate(flipped, axis=axis), axis=axis)  # surface somewhere after
        del blocked_ahead, flipped
    return (escapes < 2) | surface


def _ball(r):
    z, y, x = np.ogrid[-r:r + 1, -r:r + 1, -r:r + 1]
    return (x * x + y * y + z * z) <= r * r


def _thin_parts(solid, pitch, origin, height):
    """Local thickness: depth (distance to the outside) of the deepest point nearby. A part is thinner
    than t where no point within t/2 lies deeper than t/2 inside the model."""
    out = {}
    depth = ndimage.distance_transform_edt(solid).astype(np.float32)
    depth *= np.float32(pitch)
    thin_any = np.zeros_like(solid)
    for key, mm in (("unprintable_mm3", UNPRINTABLE_MM), ("fragile_mm3", FRAGILE_MM)):
        k = 2 * int(np.ceil(mm / 2 / pitch)) + 1
        deepest = ndimage.maximum_filter(depth, size=k)
        thin = solid & (deepest < mm / 2)
        labels, n = ndimage.label(thin)            # ignore single stray voxels from the grid
        if n:
            sizes = np.bincount(labels.ravel())
            thin = thin & (sizes[labels] >= 8)
        out[key] = round(float(thin.sum() * pitch ** 3), 1)
        if key == "fragile_mm3":
            thin_any = thin
    where = "none"
    if thin_any.any():
        zz = np.where(thin_any.any(axis=(0, 1)))[0]
        zs = (zz * pitch + origin[2]) / max(height, 1e-6)
        bands = []
        for lo, hi, name in ((0.66, 9, "top"), (0.33, 0.66, "middle"), (-9, 0.33, "bottom")):
            if np.any((zs >= lo) & (zs < hi)):
                bands.append(name)
        where = "near the " + " and ".join(bands)
    out["thin_where"] = where
    return out


def _simplify(mesh, target, pitch, log):
    """Fewer triangles with manifold3d, which always returns a valid solid. The tolerance (how far the
    surface may move) grows until the triangle count is near the target, capped at a third of a voxel."""
    import manifold3d as mf
    man = mf.Manifold(mf.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                              tri_verts=np.asarray(mesh.faces, np.uint32)))
    if man.status() != mf.Error.NoError:
        log(f"  simplify skipped: {man.status()}")
        return mesh
    best = man
    for tol in (0.03, 0.06, 0.1):
        if tol > pitch / 3 + 1e-9 or best.num_tri() <= target:
            break
        best = man.simplify(tol)
    m = best.to_mesh()
    out = trimesh.Trimesh(m.vert_properties[:, :3], m.tri_verts, process=False)
    return out if out.is_watertight else mesh

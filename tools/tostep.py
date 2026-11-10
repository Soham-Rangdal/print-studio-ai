"""Mesh -> solid body (STEP) for CAD: Fusion, SolidWorks, FreeCAD, Onshape.

A mesh is only triangles. A CAD solid (B-rep) is made of real surfaces with real edges. This rebuilds one:

  1. planes   - neighbouring triangles on the same plane become one planar face, holes and all
  2. cylinders- the strips a CAD program cuts a hole, boss or fillet into are fitted back into one true
                cylinder (axis + radius), with true circles / arcs where it meets the planes
  3. the rest - anything else (organic shapes, spheres, free-form curves) stays as small flat faces, which
                is still a valid closed solid in CAD: it can be cut, joined, shelled, and get new features

Every face is built on its own; OpenCascade's sewing joins them where their edges coincide, the shell is
closed into a solid, and coplanar / collinear leftovers are unified. If the exact rebuild doesn't close
into a valid solid, it falls back to planes only, and then to plain triangles, and says so.

    convert(vertices_mm, faces, out_path, ...) -> report dict
"""
import math
import time

import numpy as np
import trimesh

from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon,
                                BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakeWire,
                                BRepBuilderAPI_Sewing)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Geom import Geom_CylindricalSurface
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Shape, ShapeFix_Shell, ShapeFix_Solid
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.gp import gp_Ax2, gp_Ax3, gp_Circ, gp_Dir, gp_Pln, gp_Pnt

PLANE_DEG = 0.5            # triangles within this angle (and on the plane) are one planar face
STRIP_MIN_DEG, STRIP_MAX_DEG = 0.3, 30.0   # neighbouring strips of a tessellated cylinder turn by this much
MAX_FACES_BUILT = 12_000   # beyond this CAD programs crawl (and sewing takes minutes): organic meshes are lightened


class ConvertProblem(Exception):
    pass


# ============================================================================== entry
def convert(vertices, faces, out_path, *, name="part", fit_cylinders=True, max_faces=MAX_FACES_BUILT, log=print):
    t0 = time.time()
    raw = trimesh.Trimesh(np.asarray(vertices, float), np.asarray(faces, np.int64), process=True)
    ref_volume = abs(float(raw.volume)) if raw.is_watertight else None   # before clean-up opens hairlines
    mesh = _clean(vertices, faces)
    report = {"triangles_in": int(len(faces)), "watertight_in": bool(raw.is_watertight)}
    if not raw.is_watertight:
        trimesh.repair.fill_holes(mesh)
        report["holes_filled"] = bool(mesh.is_watertight)
    diag = float(np.linalg.norm(mesh.extents))
    tol = max(1e-4 * diag, 1e-3)

    planes = _plane_regions(mesh, tol)
    n_regions = int(planes.max()) + 1
    if n_regions > max_faces:                     # organic: thousands of tiny regions -> lighten first
        target = max(2000, int(len(mesh.faces) * max_faces / n_regions * 0.9))
        log(f"  lightening {len(mesh.faces)} -> ~{target} triangles")
        mesh = _lighten(mesh, target)
        planes = _plane_regions(mesh, tol)
        report["lightened_to"] = int(len(mesh.faces))

    cyl = _cylinder_regions(mesh, planes, tol) if fit_cylinders else []
    attempts = [("exact", cyl), ("planes", [])] if cyl else [("planes", [])]
    shape, level = None, None
    for level, cylinders in attempts + [("triangles", None)]:
        try:
            shape = _build(mesh, planes, cylinders, tol, log)
            if _valid_solid(shape, ref_volume, 0.03 if "lightened_to" in report else 0.01):
                break
            log(f"  '{level}' rebuild did not close into a valid solid; trying a simpler one")
        except Exception as e:  # noqa: BLE001
            log(f"  '{level}' rebuild failed: {e}")
        shape = None
    if shape is None:
        raise ConvertProblem("This mesh couldn't be made into a closed solid (it may have holes, overlaps or "
                             "loose parts). Run it through 'Make it printable' first, then convert that.")

    _write_step(shape, out_path, name)
    counts = _face_types(shape)
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    report.update(level=level, faces=sum(counts.values()), planes=counts.get("plane", 0),
                  cylinders=counts.get("cylinder", 0), other=counts.get("other", 0),
                  cylinders_fitted=len(cyl) if level == "exact" else 0,
                  volume_cm3=round(abs(props.Mass()) / 1000.0, 3),
                  mesh_volume_cm3=round(ref_volume / 1000.0, 3) if ref_volume else None,
                  size_mm=[round(float(x), 3) for x in mesh.extents], seconds=round(time.time() - t0, 1))
    return report


# ============================================================================== mesh side
def _clean(vertices, faces):
    m = trimesh.Trimesh(np.asarray(vertices, float), np.asarray(faces, np.int64), process=True)
    m.update_faces(m.nondegenerate_faces(height=1e-9))
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    m.merge_vertices(digits_vertex=6)
    trimesh.repair.fix_normals(m)
    if len(m.faces) == 0:
        raise ConvertProblem("The mesh has no surfaces.")
    return m


def _lighten(mesh, target):
    import fast_simplification
    v, f = fast_simplification.simplify(np.asarray(mesh.vertices, np.float32), np.asarray(mesh.faces, np.int32),
                                        target_reduction=max(0.0, 1.0 - target / len(mesh.faces)))
    return _clean(v.astype(float), f)


def _plane_regions(mesh, tol):
    """Label triangles by planar region: grow from the biggest triangles, joining neighbours whose normal
    is within PLANE_DEG of the region's and whose corners lie on its plane."""
    n = mesh.face_normals
    cen = mesh.triangles_center
    tri = mesh.triangles
    adj = [[] for _ in range(len(mesh.faces))]
    for a, b in mesh.face_adjacency:
        adj[a].append(b)
        adj[b].append(a)
    label = np.full(len(mesh.faces), -1, np.int64)
    cos_t = math.cos(math.radians(PLANE_DEG))
    order = np.argsort(-mesh.area_faces)
    r = 0
    for seed in order:
        if label[seed] >= 0:
            continue
        nn, d = n[seed], float(n[seed] @ cen[seed])
        label[seed] = r
        stack = [seed]
        while stack:
            i = stack.pop()
            for j in adj[i]:
                if label[j] < 0 and n[j] @ nn > cos_t and np.abs(tri[j] @ nn - d).max() < tol:
                    label[j] = r
                    stack.append(j)
        r += 1
    return label


def _region_info(mesh, labels):
    n_r = labels.max() + 1
    area = np.bincount(labels, weights=mesh.area_faces, minlength=n_r)
    nsum = np.zeros((n_r, 3))
    np.add.at(nsum, labels, mesh.face_normals * mesh.area_faces[:, None])
    normal = nsum / (np.linalg.norm(nsum, axis=1, keepdims=True) + 1e-20)
    return area, normal


def _cylinder_regions(mesh, planes, tol):
    """Groups of planar strips that together are one cylinder (a tessellated hole, boss or fillet).
    Returns dicts with axis, centre, radius, u/v range and the triangles they cover."""
    area, normal = _region_info(mesh, planes)
    n_r = len(area)
    # region adjacency + the angle between neighbours
    fa = mesh.face_adjacency
    ra, rb = planes[fa[:, 0]], planes[fa[:, 1]]
    keep = ra != rb
    pairs = np.unique(np.sort(np.c_[ra[keep], rb[keep]], axis=1), axis=0)
    radj = [[] for _ in range(n_r)]
    lo, hi = math.cos(math.radians(STRIP_MAX_DEG)), math.cos(math.radians(STRIP_MIN_DEG))
    for a, b in pairs:
        c = normal[a] @ normal[b]
        if lo < c < hi:
            radj[a].append(b)
            radj[b].append(a)
    verts_of = [[] for _ in range(n_r)]
    for fi, r in enumerate(planes):
        verts_of[r].append(fi)
    used = np.zeros(n_r, bool)
    out = []
    V = mesh.vertices
    F = mesh.faces
    for seed in np.argsort(area):
        if used[seed] or not radj[seed]:
            continue
        group = {seed}
        frontier = [seed]
        axis = None
        while frontier:
            r = frontier.pop()
            for q in radj[r]:
                if q in group or used[q]:
                    continue
                if area[q] > 4 * area[seed]:          # a big flat face: the curve ends here (a slot's
                    continue                           # wall must not join its two round ends)
                if axis is None:
                    ax = np.cross(normal[r], normal[q])
                    if np.linalg.norm(ax) < 1e-9:
                        continue
                    axis = ax / np.linalg.norm(ax)
                if abs(normal[q] @ axis) < 0.01:
                    group.add(q)
                    frontier.append(q)
        if len(group) < 6 or axis is None:          # a real tessellated cylinder has many strips
            continue
        g = np.array(sorted(group))
        # a flat wall that meets the curve smoothly (a slot's side) joins the group by angle: fit on the
        # narrow strips only, then keep just the regions that sit on that circle
        strips = g[area[g] <= 2.5 * np.median(area[g])]
        if len(strips) < 3:
            continue
        _, _, vt = np.linalg.svd(normal[strips])
        axis = vt[-1] / np.linalg.norm(vt[-1])
        fit = _fit_cylinder(V[np.unique(F[np.concatenate([verts_of[r] for r in strips])])], axis)
        if fit is None:
            continue
        centre, radius, _ = fit
        ok_tol = max(tol, 2e-3 * radius)

        def dev(r):
            p = V[np.unique(F[verts_of[r]])] - centre
            radial = p - np.outer(p @ axis, axis)
            return float(np.abs(np.linalg.norm(radial, axis=1) - radius).max())
        g = np.array([r for r in g if dev(r) <= ok_tol])
        if len(g) < 6:
            continue
        fidx = np.concatenate([verts_of[r] for r in g])
        vid = np.unique(F[fidx])
        fit = _fit_cylinder(V[vid], axis)
        if fit is None:
            continue
        centre, radius, resid = fit
        if resid > ok_tol or radius > 10 * float(np.linalg.norm(mesh.extents)):
            continue
        cyl = _cylinder_extent(V, F, fidx, vid, axis, centre, radius, planes, g, tol)
        if cyl is None:
            continue
        used[g] = True
        cyl.update(regions=set(int(x) for x in g), faces=fidx)
        out.append(cyl)
    return out


def _fit_cylinder(pts, axis):
    """Circle fit of the points projected along the axis (Kasa least squares)."""
    a = axis
    u = np.cross(a, [1, 0, 0] if abs(a[0]) < 0.9 else [0, 1, 0])
    u /= np.linalg.norm(u)
    w = np.cross(a, u)
    x, y = pts @ u, pts @ w
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    try:
        (cx, cy, c), *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    r2 = c + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    resid = float(np.abs(np.hypot(x - cx, y - cy) - r).max())
    centre = cx * u + cy * w            # a point on the axis (in the plane through the origin)
    return centre, r, resid


def _cylinder_extent(V, F, fidx, vid, axis, centre, radius, planes, group, tol):
    """The cylinder's patch in (angle u, height v). Exact rebuild only for patches that are a rectangle in
    (u, v): a hole or boss cut by planes square to its axis, or a fillet between two faces. Others stay
    as strips."""
    a = axis
    ref = np.cross(a, [1, 0, 0] if abs(a[0]) < 0.9 else [0, 1, 0])
    ref /= np.linalg.norm(ref)
    p = V[vid] - centre
    v = p @ a
    radial = p - np.outer(v, a)
    ang = np.arctan2(radial @ np.cross(a, ref), radial @ ref)
    vmin, vmax = float(v.min()), float(v.max())
    if vmax - vmin < tol * 5:
        return None
    # angular coverage: full ring, or one contiguous arc
    srt = np.sort(ang)
    gaps = np.diff(np.r_[srt, srt[0] + 2 * np.pi])
    big = int(np.argmax(gaps))
    full = gaps[big] < math.radians(STRIP_MAX_DEG) * 1.5
    # boundary vertices of the group must sit on the end rings (or on the two end lines of an arc)
    fset = set(int(x) for x in fidx)
    edges = {}
    for fi in fidx:
        a0, b0, c0 = F[fi]
        for e in ((a0, b0), (b0, c0), (c0, a0)):
            key = (min(e), max(e))
            edges[key] = edges.get(key, 0) + 1
    border = np.unique([x for e, c in edges.items() if c == 1 for x in e])
    pos = {int(k): i for i, k in enumerate(vid)}
    bv = v[[pos[int(x)] for x in border]] if len(border) else np.array([])
    bang = ang[[pos[int(x)] for x in border]] if len(border) else np.array([])
    on_ends = (np.abs(bv - vmin) < tol * 3) | (np.abs(bv - vmax) < tol * 3)
    if full:
        u0, u1 = 0.0, 2 * np.pi
        if not on_ends.all():
            return None
    else:
        u0 = float(srt[(big + 1) % len(srt)])
        u1 = float(srt[big])
        if u1 < u0:
            u1 += 2 * np.pi
        span = u1 - u0
        rel = (bang - u0) % (2 * np.pi)
        on_sides = (np.abs(rel) < 1e-3) | (np.abs(rel - span) < 1e-3) | (np.abs(rel - 2 * np.pi) < 1e-3)
        if not (on_ends | on_sides).all() or span < math.radians(30):
            return None
    origin = centre + vmin * a          # axis point at the bottom ring
    return {"axis": a, "ref": ref, "origin": origin, "radius": radius, "u0": u0, "u1": u1,
            "height": vmax - vmin, "full": bool(full)}


# ============================================================================== B-rep side
def _pnt(p):
    return gp_Pnt(float(p[0]), float(p[1]), float(p[2]))


def _build(mesh, planes, cylinders, tol, log):
    V, F = mesh.vertices, mesh.faces
    sew = BRepBuilderAPI_Sewing(tol * 2)
    n_faces = 0
    if cylinders is None:                               # plain triangles
        keep = mesh.area_faces > 1e-12                  # a zero-area sliver can't be a face; sewing closes it
        for a, b, c in F[keep]:
            poly = BRepBuilderAPI_MakePolygon(_pnt(V[a]), _pnt(V[b]), _pnt(V[c]), True)
            sew.Add(BRepBuilderAPI_MakeFace(poly.Wire(), True).Face())
            n_faces += 1
    else:
        in_cyl = {}
        for ci, c in enumerate(cylinders):
            for r in c["regions"]:
                in_cyl[r] = ci
            sew.Add(_cylinder_face(c))
            n_faces += 1
        area, normal = _region_info(mesh, planes)
        owner = {}                                       # directed edge -> triangle
        for fi, (a, b, c) in enumerate(F.tolist()):
            owner[(a, b)] = owner[(b, c)] = owner[(c, a)] = fi
        members = [[] for _ in range(len(area))]
        for fi, r in enumerate(planes):
            members[r].append(fi)
        for r, fl in enumerate(members):
            if r in in_cyl or not fl:
                continue
            face = _plane_face(V, F, np.array(fl), planes, normal[r], cylinders, in_cyl, owner, tol)
            if face is None:                             # couldn't trace it: its triangles instead
                for fi in fl:
                    a, b, c = F[fi]
                    poly = BRepBuilderAPI_MakePolygon(_pnt(V[a]), _pnt(V[b]), _pnt(V[c]), True)
                    sew.Add(BRepBuilderAPI_MakeFace(poly.Wire(), True).Face())
            else:
                sew.Add(face)
            n_faces += 1
    log(f"  sewing {n_faces} faces ...")
    sew.Perform()
    sewn = sew.SewedShape()
    shells = []
    exp = TopExp_Explorer(sewn, TopAbs_SHELL)
    while exp.More():
        shells.append(TopoDS.Shell_s(exp.Current()))
        exp.Next()
    if not shells:
        raise ConvertProblem("sewing produced no shell")
    solids = []
    for sh in shells:
        fix = ShapeFix_Shell(sh)
        fix.Perform()
        ms = BRepBuilderAPI_MakeSolid(fix.Shell())
        sf = ShapeFix_Solid(ms.Solid())
        sf.Perform()
        solids.append(sf.Solid())
    if len(solids) == 1:
        shape = solids[0]
    else:
        comp = TopoDS_Compound()
        bld = BRep_Builder()
        bld.MakeCompound(comp)
        for s in solids:
            bld.Add(comp, s)
        shape = comp
    u = ShapeUpgrade_UnifySameDomain(shape, True, True, True)
    u.SetLinearTolerance(tol)
    u.SetAngularTolerance(math.radians(PLANE_DEG))
    u.Build()
    fx = ShapeFix_Shape(u.Shape())              # last: tiny edges and tolerances left by sewing / merging
    fx.Perform()
    return _as_solids(fx.Shape())


def _as_solids(shape):
    """Make sure the result is solid bodies, not just closed shells: CAD opens a shell as a surface."""
    solids = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    if not solids:
        exp = TopExp_Explorer(shape, TopAbs_SHELL)
        while exp.More():
            sf = ShapeFix_Solid(BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(exp.Current())).Solid())
            sf.Perform()
            solids.append(sf.Solid())
            exp.Next()
    if len(solids) == 1:
        return solids[0]
    comp = TopoDS_Compound()
    bld = BRep_Builder()
    bld.MakeCompound(comp)
    for so in solids:
        bld.Add(comp, so)
    return comp


def _cylinder_face(c):
    ax3 = gp_Ax3(_pnt(c["origin"]), gp_Dir(*map(float, c["axis"])), gp_Dir(*map(float, c["ref"])))
    surf = Geom_CylindricalSurface(ax3, float(c["radius"]))
    mf = BRepBuilderAPI_MakeFace(surf, float(c["u0"]), float(c["u1"]), 0.0, float(c["height"]), 1e-7)
    return mf.Face()


def _plane_face(V, F, fl, planes, normal, cylinders, in_cyl, owner, tol):
    """One planar face from a region's boundary loops; runs along an exact cylinder become arcs/circles.
    Corners are shared vertices with a real tolerance: STL stores 32-bit coordinates, so a point "on" a
    circle can be a millionth of a millimetre off it, more than OpenCascade's default allows."""
    loops = _boundary_loops(F, fl)
    if not loops:
        return None
    vcache, bld = {}, BRep_Builder()

    def vert(i):
        if i not in vcache:
            vx = BRepBuilderAPI_MakeVertex(_pnt(V[i])).Vertex()
            bld.UpdateVertex(vx, tol)
            vcache[i] = vx
        return vcache[i]
    wires = []
    for loop in loops:
        edges = []
        k = len(loop)
        nb = []
        for i in range(k):
            a, b = loop[i], loop[(i + 1) % k]
            other = owner.get((b, a))
            nb.append(in_cyl.get(int(planes[other]), -1) if other is not None else -1)
        # rotate so a run starts at index 0
        if len(set(nb)) > 1:
            s = next(i for i in range(k) if nb[i] != nb[i - 1])
            loop, nb = loop[s:] + loop[:s], nb[s:] + nb[:s]
        i = 0
        while i < k:
            j = i
            while j + 1 < k and nb[j + 1] == nb[i]:
                j += 1
            run = loop[i:j + 2] if j + 1 < k else loop[i:] + loop[:1]
            ci = nb[i]
            arc = _arc_edge(V, run, cylinders[ci], normal, vert) if ci >= 0 else None
            if arc is not None:
                edges.append(arc)
            else:
                for p, q in zip(run[:-1], run[1:]):
                    if p != q and np.linalg.norm(V[p] - V[q]) > 1e-9:
                        edges.append(BRepBuilderAPI_MakeEdge(vert(p), vert(q)).Edge())
            i = j + 1
        mw = BRepBuilderAPI_MakeWire()
        for e in edges:
            mw.Add(e)
        if not mw.IsDone():
            return None
        wires.append((mw.Wire(), _loop_area(V, loop, normal)))
    wires.sort(key=lambda w: -abs(w[1]))
    origin = V[F[fl[0], 0]]
    pln = gp_Pln(_pnt(origin), gp_Dir(*map(float, normal)))
    mf = BRepBuilderAPI_MakeFace(pln, wires[0][0], True)
    if not mf.IsDone():
        return None
    for w, _ in wires[1:]:
        mf.Add(w)
    fix = ShapeFix_Face(mf.Face())
    fix.FixOrientation()
    fix.Perform()
    return fix.Face()


def _arc_edge(V, run, c, normal, vert):
    """A boundary run lying on an exact cylinder's end ring: one circle arc (or the whole circle)."""
    a = c["axis"]
    if abs(float(normal @ a)) < 0.999:          # plane not square to the axis: a straight side line
        return None
    p0 = V[run[0]]
    centre = c["origin"] + float((p0 - c["origin"]) @ a) * a
    circ = gp_Circ(gp_Ax2(_pnt(centre), gp_Dir(*map(float, a)), gp_Dir(*map(float, c["ref"]))), float(c["radius"]))
    closed = run[0] == run[-1]
    if closed:
        return BRepBuilderAPI_MakeEdge(circ).Edge()
    p1, p2 = V[run[0]], V[run[-1]]
    mid = V[run[len(run) // 2]]

    def angle(p):
        d = p - centre
        return math.atan2(float(d @ np.cross(a, c["ref"])), float(d @ c["ref"]))
    t1, t2, tm = angle(p1), angle(p2), angle(mid)
    span = (t2 - t1) % (2 * np.pi)
    if ((tm - t1) % (2 * np.pi)) <= span:           # counter-clockwise from p1 passes the middle
        mk = BRepBuilderAPI_MakeEdge(circ, vert(run[0]), vert(run[-1]))
    else:
        mk = BRepBuilderAPI_MakeEdge(circ, vert(run[-1]), vert(run[0]))
    return mk.Edge() if mk.IsDone() else None


def _boundary_loops(F, fl):
    """Closed vertex loops around a set of triangles, following the triangles' winding."""
    directed = set()
    for fi in fl:
        a, b, c = (int(x) for x in F[fi])
        directed.update(((a, b), (b, c), (c, a)))
    nxt = {}
    for a, b in directed:
        if (b, a) not in directed:
            nxt.setdefault(a, []).append(b)
    loops = []
    while nxt:
        start = next(iter(nxt))
        loop = [start]
        cur = start
        for _ in range(len(directed) + 1):
            outs = nxt.get(cur)
            if not outs:
                break
            b = outs.pop()
            if not outs:
                del nxt[cur]
            if b == start:
                break
            loop.append(b)
            cur = b
        else:
            return None
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def _loop_area(V, loop, normal):
    p = V[loop]
    return float(np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0) @ normal) / 2


def _valid_solid(shape, ref_volume, rel=0.01):
    """Valid B-rep, and the same volume as the mesh (within 1%): a wrongly fitted cylinder or a face that
    went missing changes the volume, so this catches rebuilds that look fine but aren't."""
    if shape is None or shape.IsNull():
        return False
    if not BRepCheck_Analyzer(shape).IsValid():
        return False
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    vol = abs(props.Mass())
    if vol <= 0:
        return False
    if ref_volume:
        return abs(vol - ref_volume) <= rel * ref_volume
    return True


def _face_types(shape):
    out = {}
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        t = BRepAdaptor_Surface(TopoDS.Face_s(exp.Current())).GetType()
        k = "plane" if t == GeomAbs_Plane else "cylinder" if t == GeomAbs_Cylinder else "other"
        out[k] = out.get(k, 0) + 1
        exp.Next()
    return out


def _write_step(shape, path, name):
    w = STEPControl_Writer()
    Interface_Static.SetCVal_s("write.step.schema", "AP214")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    Interface_Static.SetCVal_s("write.step.product.name", name)
    if w.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone or w.Write(str(path)) != IFSelect_RetDone:
        raise ConvertProblem("The STEP file couldn't be written.")

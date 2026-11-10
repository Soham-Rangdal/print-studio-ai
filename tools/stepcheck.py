"""Read a STEP file back on its own and report what a CAD program will see: solids, validity, volume, and
how many faces are planes / cylinders / other. Optionally render it with faces coloured by type
(planes blue, cylinders orange, other grey), for a quick visual check of a conversion.

    python stepcheck.py part.step [preview.png]
"""
import sys

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

COLOURS = {"plane": (70, 120, 200), "cylinder": (230, 140, 50), "other": (160, 160, 160)}


def read(path):
    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != IFSelect_RetDone:
        raise RuntimeError("not a readable STEP file")
    r.TransferRoots()
    return r.OneShape()


def check(path):
    shape = read(path)
    solids = 0
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        solids += 1
        exp.Next()
    kinds = {}
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        t = BRepAdaptor_Surface(TopoDS.Face_s(exp.Current())).GetType()
        k = "plane" if t == GeomAbs_Plane else "cylinder" if t == GeomAbs_Cylinder else "other"
        kinds[k] = kinds.get(k, 0) + 1
        exp.Next()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return {"solids": solids, "valid": BRepCheck_Analyzer(shape).IsValid(), "faces": kinds,
            "volume_cm3": round(abs(props.Mass()) / 1000, 3)}, shape


def preview(shape, png, size=520):
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    import render
    BRepMesh_IncrementalMesh(shape, 0.05, False, 0.2, True)
    V, F, C = [], [], []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        t = BRepAdaptor_Surface(face).GetType()
        col = COLOURS["plane" if t == GeomAbs_Plane else "cylinder" if t == GeomAbs_Cylinder else "other"]
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            base = sum(len(v) for v in V)
            pts = []
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                pts.append((p.X(), p.Y(), p.Z()))
            V.append(np.array(pts))
            rev = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                F.append((base + a - 1, base + c - 1, base + b - 1) if rev else (base + a - 1, base + b - 1, base + c - 1))
                C.append(col)
        exp.Next()
    v = np.vstack(V)
    img = render.turnaround(v, np.array(F), np.array(C, np.uint8), size=size // 2)
    img.save(png)


if __name__ == "__main__":
    info, shp = check(sys.argv[1])
    print(info)
    if len(sys.argv) > 2:
        preview(shp, sys.argv[2])

"""Write a 3MF where every triangle carries its filament number as slicer colour paint.

One solid object (so the slicer builds the colour volumes itself, as with hand painting). Each triangle
gets the paint code in both formats OrcaSlicer-family slicers read: `paint_color` (Bambu / Orca /
Creality Print) and `slic3rpe:mmu_segmentation` (PrusaSlicer). Codes for an unsplit triangle:
filament 1 = "4", 2 = "8", 3 = "0C", 4 = "1C" (state 0 = unpainted). Filament n maps to CFS slot n.

Confirmed against a project saved by her Creality Print 7.3.1 (templates\\k2pro_template.3mf): the same codes,
in `paint_color`, inside 3D/Objects/object_1.model. write_creality_project() builds a native project from that
template; write_3mf() is the plain fallback.
"""
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path

import numpy as np

PAINT_CODES = {0: "4", 1: "8", 2: "0C", 3: "1C", 4: "2C", 5: "3C", 6: "4C", 7: "5C"}

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
 <Relationship Target="/Metadata/thumbnail.png" Id="rel1" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
</Relationships>"""


def write_3mf(path, vertices, faces, filament_per_face, name="Print Studio model", thumbnail_png=None):
    v = np.asarray(vertices, float)
    f = np.asarray(faces, int)
    lab = np.asarray(filament_per_face, int)
    buf = io.StringIO()
    w = buf.write
    w('<?xml version="1.0" encoding="UTF-8"?>\n')
    w('<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
      'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">\n')
    w(f' <metadata name="Title">{_xml(name)}</metadata>\n <metadata name="Application">Print Studio</metadata>\n')
    w(' <resources>\n  <object id="1" type="model">\n   <mesh>\n    <vertices>\n')
    w("".join(f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>\n' for x, y, z in v))
    w('    </vertices>\n    <triangles>\n')
    codes = [PAINT_CODES.get(int(i), "4") for i in lab]
    w("".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}" paint_color="{p}" slic3rpe:mmu_segmentation="{p}"/>\n'
              for (a, b, c), p in zip(f, codes)))
    w('    </triangles>\n   </mesh>\n  </object>\n </resources>\n')
    w(' <build>\n  <item objectid="1" printable="1"/>\n </build>\n</model>\n')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS if thumbnail_png else RELS.replace(
            ' <Relationship Target="/Metadata/thumbnail.png"', ' <!--').replace('thumbnail"/>', 'thumbnail"/-->'))
        z.writestr("3D/3dmodel.model", buf.getvalue())
        if thumbnail_png:
            z.writestr("Metadata/thumbnail.png", thumbnail_png)
    return path


TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "k2pro_template.3mf"


def write_creality_project(path, vertices, faces, filament_per_face, palette, name="Print Studio model",
                           thumbnail_png=None, template=TEMPLATE):
    """A native Creality Print project, built on a project saved by her own Creality Print: the K2 Pro and
    four Hyper PLA filaments come from the template, the mesh, paint, name, thumbnail and filament colours
    are ours. Opens without the 'not from Creality Print' dialog, colours already on filaments 1-4.
    Falls back to the plain 3MF when no template has been saved."""
    template = Path(template)
    if not template.exists():
        return write_3mf(path, vertices, faces, filament_per_face, name, thumbnail_png)
    src = zipfile.ZipFile(template)
    v = np.asarray(vertices, float)
    f = np.asarray(faces, int)
    lab = np.asarray(filament_per_face, int)
    # Creality keeps the object centred on its own origin and places it on the bed with the build transform
    centre = (v.max(0) + v.min(0)) / 2
    v = v - centre
    half_h = (v[:, 2].max() - v[:, 2].min()) / 2
    bed_x, bed_y = 150.0, 150.0
    today = date.today().isoformat()

    head = src.read("3D/Objects/object_1.model").decode("utf-8")
    head = head[: head.index("<vertices>")]                     # template's model header, object tag, <mesh>
    buf = io.StringIO()
    w = buf.write
    w(head + "<vertices>\n")
    w("".join(f'      <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>\n' for x, y, z in v))
    w("     </vertices>\n     <triangles>\n")
    codes = [PAINT_CODES.get(int(i), "4") for i in lab]
    w("".join(f'      <triangle v1="{a}" v2="{b}" v3="{c}" paint_color="{p}"/>\n' for (a, b, c), p in zip(f, codes)))
    w("     </triangles>\n    </mesh>\n   </object>\n  </resources>\n  <build/>\n</model>\n")

    main = src.read("3D/3dmodel.model").decode("utf-8")
    main = re.sub(r'(<metadata name="Title">)[^<]*(</metadata>)', rf"\g<1>{_xml(name)}\g<2>", main)
    main = re.sub(r'(<metadata name="(?:CreationDate|ModificationDate)">)[^<]*(</metadata>)', rf"\g<1>{today}\g<2>", main)
    main = re.sub(r'(<item [^>]*transform=")[^"]*(")', rf"\g<1>1 0 0 0 1 0 0 0 1 {bed_x} {bed_y} {half_h:.6f}\g<2>", main)

    settings = src.read("Metadata/model_settings.config").decode("utf-8")
    settings = re.sub(r'(<metadata key="name" value=")[^"]*(")', rf"\g<1>{_xml(name)}\g<2>", settings)
    settings = re.sub(r'\s*<metadata key="source_[a-z_]+" value="[^"]*"/>', "", settings)
    settings = re.sub(r'(transform="1 0 0 0 1 0 0 0 1 )[^"]*(")', rf"\g<1>{bed_x} {bed_y} {half_h}\g<2>", settings)

    project = json.loads(src.read("Metadata/project_settings.config"))
    n = len(project.get("filament_colour", [])) or 4
    colours = [c.upper() for c in list(palette)[:n]]
    project["filament_colour"] = colours + project["filament_colour"][len(colours):]

    creality = src.read("Metadata/creality.config").decode("utf-8")
    creality = re.sub(r'(key="CreationDate" value=")[^"]*(")', rf"\g<1>{today}\g<2>", creality)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            name_in = item.filename
            if name_in == "3D/Objects/object_1.model":
                z.writestr(name_in, buf.getvalue())
            elif name_in == "3D/3dmodel.model":
                z.writestr(name_in, main)
            elif name_in == "Metadata/model_settings.config":
                z.writestr(name_in, settings)
            elif name_in == "Metadata/project_settings.config":
                z.writestr(name_in, json.dumps(project, indent=4))
            elif name_in == "Metadata/creality.config":
                z.writestr(name_in, creality)
            elif thumbnail_png and name_in in ("Metadata/plate_1.png", "Metadata/plate_no_light_1.png", "Metadata/top_1.png"):
                z.writestr(name_in, thumbnail_png)
            elif thumbnail_png and name_in == "Metadata/plate_1_small.png":
                z.writestr(name_in, _small(thumbnail_png))
            else:
                z.writestr(item, src.read(name_in))
    return path


def _small(png, size=128):
    from PIL import Image
    out = io.BytesIO()
    Image.open(io.BytesIO(png)).resize((size, size)).save(out, "PNG")
    return out.getvalue()


def _xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

"""Small CPU renderer for previews: shaded triangles with per-face colours, painter's algorithm.

No OpenGL or GPU needed, so it runs while the GPU worker is busy. Printer coordinates: Z up, the
model's front facing -Y.
"""
import numpy as np
from PIL import Image, ImageDraw

VIEWS = {  # yaw around Z (degrees), pitch (degrees, positive looks down)
    "front": (0, 8), "right": (90, 8), "back": (180, 8), "left": (270, 8), "iso": (35, 25),
}


def _rotation(yaw_deg, pitch_deg):
    y, p = np.radians(yaw_deg), np.radians(pitch_deg)
    rz = np.array([[np.cos(y), -np.sin(y), 0], [np.sin(y), np.cos(y), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    return rx @ rz


def render(vertices, faces, face_rgb, view="front", size=640, background=(244, 245, 247)):
    """vertices (N,3) mm, faces (M,3), face_rgb (M,3) uint8 -> PIL image."""
    yaw, pitch = VIEWS[view] if isinstance(view, str) else view
    # camera looks along +Y in its own frame; rotate the model instead of the camera
    v = vertices @ _rotation(-yaw, 0).T
    v = v @ np.array([[1, 0, 0], [0, np.cos(np.radians(pitch)), np.sin(np.radians(pitch))],
                      [0, -np.sin(np.radians(pitch)), np.cos(np.radians(pitch))]]).T
    tri = v[faces]                                     # (M,3,3)
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    visible = normals[:, 1] < 0                        # facing the camera (camera at -Y)
    to_light = np.array([-0.35, -0.8, 0.5])            # towards a light in front, left, above
    to_light /= np.linalg.norm(to_light)
    shade = 0.35 + 0.65 * np.clip(normals @ to_light, 0, 1)
    tri, shade, rgb = tri[visible], shade[visible], np.asarray(face_rgb)[visible].astype(float)
    order = np.argsort(-tri[:, :, 1].mean(axis=1))     # far to near
    xz = tri[:, :, [0, 2]]
    lo, hi = xz.reshape(-1, 2).min(0), xz.reshape(-1, 2).max(0)
    scale = (size * 0.88) / max(hi - lo)
    offset = (size - (hi - lo) * scale) / 2
    px = (xz - lo) * scale + offset
    px[:, :, 1] = size - px[:, :, 1]
    img = Image.new("RGB", (size, size), background)
    draw = ImageDraw.Draw(img)
    colours = np.clip(rgb * shade[:, None], 0, 255).astype(np.uint8)
    for i in order:
        draw.polygon([tuple(p) for p in px[i]], fill=tuple(int(c) for c in colours[i]))
    return img


def turnaround(vertices, faces, face_rgb, views=("front", "right", "back", "iso"), size=480):
    tiles = [render(vertices, faces, face_rgb, v, size) for v in views]
    sheet = Image.new("RGB", (size * len(tiles), size), (244, 245, 247))
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * size, 0))
    return sheet

"""Map a model's colours to the (at most 4) filaments loaded in the CFS.

    suggest_palette(face_rgb, areas, k=4)        -> the k main colours of the model (to suggest filaments)
    assign_filaments(faces, face_rgb, areas, palette_hex) -> filament index (0..k-1) per triangle, cleaned up

Colours are compared in CIE Lab (close to how people see colour differences), weighted by triangle
area. After the nearest-filament choice, speckles are removed: each triangle takes the majority
filament of its neighbours a few times, and colour islands smaller than `min_island_mm2` are merged
into the surrounding colour (they would be too small to print cleanly and waste filament changes).
"""
import numpy as np
import trimesh
from scipy import sparse
from skimage import color


def hex_to_rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.uint8)


def rgb_to_hex(rgb):
    return "#" + "".join(f"{int(c):02X}" for c in rgb)


def to_lab(rgb):
    return color.rgb2lab(np.asarray(rgb, float).reshape(-1, 1, 3) / 255.0).reshape(-1, 3)


def suggest_palette(face_rgb, areas, k=4, seed=0, groups=8, min_share=0.015):
    """The k most useful, clearly different colours of the model, with their share of the surface.

    Plain k-means over a photo model returns k shades of its lighting (a cream cow came back as four
    browns). Instead: find `groups` colour groups (lightness counts less than hue, since lighting is
    baked into the colours), drop groups under `min_share` of the surface, then pick greedily: the
    biggest group first, then each time the group farthest from those already picked, weighted by its size.
    Shares are reported for the full model mapped onto the chosen k."""
    from sklearn.cluster import KMeans
    lab = to_lab(face_rgb)
    weight = np.array([0.6, 1.0, 1.0])
    km = KMeans(n_clusters=groups, n_init=4, random_state=seed).fit(lab * weight, sample_weight=areas)
    share = np.bincount(km.labels_, weights=areas, minlength=groups) / areas.sum()
    centres = km.cluster_centers_ / weight
    keep = [i for i in np.argsort(-share) if share[i] >= min_share]
    chosen = [keep[0]]
    while len(chosen) < min(k, len(keep)):
        best, best_score = None, -1.0
        for i in keep:
            if i in chosen:
                continue
            d = min(np.linalg.norm((centres[i] - centres[j]) * weight) for j in chosen)
            score = d * np.sqrt(share[i])
            if score > best_score:
                best, best_score = i, score
        chosen.append(best)
    rgb = np.clip(color.lab2rgb(centres[chosen].reshape(-1, 1, 3)).reshape(-1, 3) * 255, 0, 255)
    hexes = [rgb_to_hex(c) for c in rgb]
    pal = to_lab(np.array([hex_to_rgb(h) for h in hexes]))
    nearest = (((lab[:, None, :] - pal[None]) * weight) ** 2).sum(-1).argmin(1)
    final_share = np.bincount(nearest, weights=areas, minlength=len(hexes)) / areas.sum()
    order = np.argsort(-final_share)
    return [(hexes[i], round(float(final_share[i]), 3)) for i in order]


def assign_filaments(faces, face_rgb, areas, palette_hex, *, smooth_iters=3, min_island_mm2=6.0,
                     lightness_weight=1.0):
    pal_lab = to_lab(np.array([hex_to_rgb(h) for h in palette_hex]))
    lab = to_lab(face_rgb)
    # baked-in lighting shifts lightness much more than hue: weighing lightness less keeps a shaded
    # cream surface cream instead of turning it brown
    w = np.array([lightness_weight, 1.0, 1.0])
    dist = (((lab[:, None, :] - pal_lab[None, :, :]) * w) ** 2).sum(-1)
    label = dist.argmin(1)
    k = len(palette_hex)

    adjacency = trimesh.graph.face_adjacency(faces)
    n = len(faces)
    rows = np.concatenate([adjacency[:, 0], adjacency[:, 1]])
    cols = np.concatenate([adjacency[:, 1], adjacency[:, 0]])
    A = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))

    # majority smoothing: neighbours' votes (area-weighted) plus a bonus for the face's own colour
    for _ in range(smooth_iters):
        onehot = sparse.csr_matrix((areas, (np.arange(n), label)), shape=(n, k))
        votes = (A @ onehot).toarray() + 1.5 * onehot.toarray()
        label = votes.argmax(1)

    # merge islands that are too small to print cleanly
    for _ in range(3):
        same = label[adjacency[:, 0]] == label[adjacency[:, 1]]
        comp = trimesh.graph.connected_component_labels(adjacency[same], node_count=n)
        comp_area = np.bincount(comp, weights=areas)
        small = comp_area[comp] < min_island_mm2
        if not small.any():
            break
        onehot = sparse.csr_matrix((areas * ~small, (np.arange(n), label)), shape=(n, k))
        votes = (A @ onehot).toarray()
        has_vote = votes.sum(1) > 0
        fix = small & has_vote
        label[fix] = votes[fix].argmax(1)

    share = np.bincount(label, weights=areas, minlength=k) / areas.sum()
    return label, [round(float(s), 3) for s in share]

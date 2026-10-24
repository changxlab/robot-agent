"""Simulated farm used in SIM mode: camera frames, video frames, lidar point clouds and an
occupancy map, all following the simulated B2 pose.

Camera frames are crops of real plant photographs (``sim_images/``, see ATTRIBUTION.md) chosen
and framed from the camera pose; lidar scans and maps come from the 3D world below, which is
also rendered as a camera fallback when no photos are installed.

World frame (metres, Z up, origin = where the simulated B2 starts, facing +X): a fenced plot
of crop rows running along X at y = ±0.5, ±1.5, ... ±5.5, so the robot starts in a lane.
Rows alternate lettuce, tomato and maize. A shed stands in the north-east corner, a few trees
inside the fence and a tree line far outside it. Everything is deterministic for a given pose
and time, so repeated captures of the same scene match.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

PHOTO_DIR = Path(__file__).with_name("sim_images")

ROW_SPAN_X = (-7.5, 5.6)
ROW_YS = tuple(s * (0.5 + k) for k in range(6) for s in (-1.0, 1.0))
PLANT_STEP = 0.35
FENCE_X, FENCE_Y = 9.0, 8.5
SHED = (6.6, 8.6, 5.0, 8.0, 2.6)  # x0, x1, y0, y1, height
NEAR_TREES = ((-8.2, 7.6, 3.8, 1.6), (-8.0, -7.4, 4.4, 1.9), (8.0, -7.3, 3.4, 1.4))  # x, y, h, r
MAP_RES, MAP_SIZE, MAP_ORIGIN = 0.05, 400, -10.0

# BGR colours
SOIL = np.array([58, 84, 112], np.float32)
SOIL_WET = np.array([40, 58, 80], np.float32)
GRASS = np.array([52, 128, 78], np.float32)
SKY_TOP = np.array([214, 160, 98], np.float32)
SKY_HORIZON = np.array([236, 222, 200], np.float32)
HAZE = np.array([205, 205, 190], np.float32)
SUN = np.array([0.45, -0.35, 0.82])


def crop_of(row_y: float) -> str:
    return ("lettuce", "tomato", "maize")[int(abs(row_y) - 0.5) % 3]


# ---------- world geometry ----------

@dataclass
class Leaf:
    p0: np.ndarray
    p1: np.ndarray  # quadratic Bezier control point
    p2: np.ndarray
    width: float
    color: tuple[float, float, float]


@dataclass
class Plant:
    x: float
    y: float
    crop: str
    leaves: list[Leaf]
    stalks: list[tuple[np.ndarray, np.ndarray, float, tuple[float, float, float]]]
    fruit: list[tuple[np.ndarray, float, tuple[float, float, float]]]
    phase: float
    height: float


def _jitter(rng, color, amount=14.0):
    return tuple(float(np.clip(c + rng.normal(0, amount), 0, 255)) for c in color)


def _lettuce(rng, x, y, s):
    leaves = []
    n = int(rng.integers(11, 15))
    for i in range(n):
        inner = i >= n * 0.6
        a = rng.uniform(0, 2 * math.pi)
        r = (0.07 if inner else 0.15) * s * rng.uniform(0.85, 1.2)
        z = (0.13 if inner else 0.08) * s * rng.uniform(0.8, 1.2)
        base = np.array([x, y, 0.02])
        tip = base + [r * math.cos(a), r * math.sin(a), z * 0.6]
        ctrl = base + [r * 0.5 * math.cos(a), r * 0.5 * math.sin(a), z * 1.25]
        color = (95, 205, 150) if inner else (62, 170, 98)
        leaves.append(Leaf(base, ctrl, tip, (0.085 if inner else 0.11) * s, _jitter(rng, color)))
    return leaves, [], [], 0.16 * s


def _tomato(rng, x, y, s):
    h = 0.62 * s * rng.uniform(0.85, 1.15)
    stem = (np.array([x, y, 0.0]), np.array([x, y, h]), 0.018, (40, 92, 70))
    leaves, fruit = [], []
    for i in range(int(rng.integers(12, 17))):
        z = h * rng.uniform(0.18, 1.0)
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.12, 0.2) * s
        base = np.array([x, y, z])
        tip = base + [r * math.cos(a), r * math.sin(a), rng.uniform(-0.08, 0.02)]
        ctrl = base + [0.55 * r * math.cos(a), 0.55 * r * math.sin(a), 0.06]
        leaves.append(Leaf(base, ctrl, tip, 0.075 * s, _jitter(rng, (42, 118, 52), 10)))
    for _ in range(int(rng.integers(2, 7))):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(0.04, 0.13)
        ripe = rng.random() < 0.65
        color = (38, 52, 205) if ripe else (60, 170, 150)
        fruit.append((np.array([x + r * math.cos(a), y + r * math.sin(a),
                                h * rng.uniform(0.25, 0.7)]), rng.uniform(0.025, 0.04),
                      _jitter(rng, color, 10)))
    return leaves, [stem], fruit, h


def _maize(rng, x, y, s):
    h = 1.35 * s * rng.uniform(0.85, 1.15)
    stalk = (np.array([x, y, 0.0]), np.array([x, y, h]), 0.028, (60, 150, 120))
    leaves = []
    for i in range(int(rng.integers(8, 11))):
        z = h * (0.15 + 0.75 * i / 10) + rng.uniform(-0.04, 0.04)
        a = rng.uniform(0, 2 * math.pi)
        length = rng.uniform(0.45, 0.7) * s * (1.0 - 0.35 * i / 10)
        base = np.array([x, y, z])
        tip = base + [length * math.cos(a), length * math.sin(a), -0.12 - 0.15 * rng.random()]
        ctrl = base + [0.45 * length * math.cos(a), 0.45 * length * math.sin(a), 0.2]
        leaves.append(Leaf(base, ctrl, tip, 0.06 * s, _jitter(rng, (58, 150, 96), 12)))
    tassel = [(np.array([x, y, h]), np.array([x + rng.uniform(-.08, .08), y + rng.uniform(-.08, .08),
                                                h + rng.uniform(0.12, 0.2)]), 0.008, (90, 190, 215))
              for _ in range(4)]
    return leaves, [stalk, *tassel], [], h + 0.15


@lru_cache(maxsize=1)
def plants() -> tuple[Plant, ...]:
    rng = np.random.default_rng(20261024)
    out = []
    for row_y in ROW_YS:
        crop = crop_of(row_y)
        maker = {"lettuce": _lettuce, "tomato": _tomato, "maize": _maize}[crop]
        for x in np.arange(ROW_SPAN_X[0], ROW_SPAN_X[1], PLANT_STEP):
            if rng.random() < 0.05:  # gaps where seedlings failed
                continue
            px, py = x + rng.uniform(-0.04, 0.04), row_y + rng.uniform(-0.04, 0.04)
            leaves, stalks, fruit, h = maker(rng, px, py, rng.uniform(0.8, 1.15))
            out.append(Plant(px, py, crop, leaves, stalks, fruit, rng.uniform(0, 2 * math.pi), h))
    return tuple(out)


@lru_cache(maxsize=1)
def far_trees() -> np.ndarray:
    """Tree line well outside the fence: rows of (x, y, height, crown radius, shade)."""
    rng = np.random.default_rng(7)
    a = rng.uniform(0, 2 * math.pi, 140)
    d = rng.uniform(26, 42, 140)
    return np.stack([d * np.cos(a), d * np.sin(a), rng.uniform(5, 10, 140),
                     rng.uniform(2.0, 4.0, 140), rng.uniform(0.7, 1.1, 140)], 1)


def fence_posts() -> list[tuple[float, float]]:
    posts = []
    for x in np.arange(-FENCE_X, FENCE_X + 0.01, 2.0):
        posts += [(x, -FENCE_Y), (x, FENCE_Y)]
    for y in np.arange(-FENCE_Y + 2.125, FENCE_Y - 0.1, 2.125):
        posts += [(-FENCE_X, y), (FENCE_X, y)]
    return posts


# ---------- noise ----------

@lru_cache(maxsize=1)
def _noise_tile() -> np.ndarray:
    import cv2

    rng = np.random.default_rng(3)
    tile = np.zeros((256, 256), np.float32)
    for size, weight in ((8, 0.5), (32, 0.3), (128, 0.15), (256, 0.05)):
        layer = rng.random((size, size)).astype(np.float32)
        layer = np.tile(layer, (3, 3))  # wrap so resizing stays seamless
        big = cv2.resize(layer, (768, 768), interpolation=cv2.INTER_CUBIC)[256:512, 256:512]
        tile += weight * big
    return (tile - tile.min()) / (np.ptp(tile) or 1)


def _sample(tile: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    n = tile.shape[0]
    return tile[np.mod(v.astype(np.int64), n), np.mod(u.astype(np.int64), n)]


# ---------- camera ----------

@dataclass
class Camera:
    x: float
    y: float
    z: float
    yaw: float
    pitch: float  # radians, positive looks down
    width: int = 640
    height: int = 480
    hfov_deg: float = 90.0

    def __post_init__(self):
        cy, sy, cp, sp = math.cos(self.yaw), math.sin(self.yaw), math.cos(self.pitch), math.sin(self.pitch)
        self.c = np.array([self.x, self.y, self.z])
        self.f = np.array([cy * cp, sy * cp, -sp])
        self.r = np.array([sy, -cy, 0.0])
        self.u = np.cross(self.r, self.f)
        self.fx = self.width / 2 / math.tan(math.radians(self.hfov_deg) / 2)
        self.cx, self.cy = self.width / 2, self.height / 2

    def to_cam(self, p: np.ndarray) -> np.ndarray:
        d = np.asarray(p, np.float64) - self.c
        return np.stack([d @ self.r, d @ self.u, d @ self.f], -1)

    def project(self, pc: np.ndarray) -> np.ndarray:
        """Camera-frame points -> pixel coordinates (callers drop points behind the camera)."""
        z = np.maximum(pc[..., 2], 1e-6)
        return np.stack([self.cx + self.fx * pc[..., 0] / z, self.cy - self.fx * pc[..., 1] / z], -1)


NEAR = 0.12


def _clip_segment(a: np.ndarray, b: np.ndarray):
    if a[2] < NEAR and b[2] < NEAR:
        return None
    if a[2] < NEAR or b[2] < NEAR:
        t = (NEAR - a[2]) / (b[2] - a[2])
        m = a + t * (b - a)
        a, b = (m, b) if a[2] < NEAR else (a, m)
    return a, b


def _shade(color, k):
    return tuple(float(np.clip(c * k, 0, 255)) for c in color)


def _background(cam: Camera, t: float) -> np.ndarray:
    """Sky and ground (soil, beds, lanes, grass outside the fence) for every pixel."""
    h, w = cam.height, cam.width
    uu, vv = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    xs, ys = (uu - cam.cx) / cam.fx, (cam.cy - vv) / cam.fx
    d = (cam.f[None, None, :] + xs[..., None] * cam.r[None, None, :]
         + ys[..., None] * cam.u[None, None, :])
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    tile = _noise_tile()

    elev = np.clip(d[..., 2], -1, 1)
    sky_k = np.clip(elev / 0.45, 0, 1)[..., None] ** 0.6
    img = SKY_HORIZON * (1 - sky_k) + SKY_TOP * sky_k
    az = np.arctan2(d[..., 1], d[..., 0])
    cloud = _sample(tile, az * 160 + t * 3, np.clip(elev, 0, 1) * 900)
    cloud = np.clip((cloud - 0.52) * 3.2, 0, 1)[..., None] * np.clip(elev / 0.05, 0, 1)[..., None]
    img = img * (1 - 0.75 * cloud) + 250 * 0.75 * cloud

    ground = d[..., 2] < -1e-4
    dist = np.where(ground, -cam.z / np.minimum(d[..., 2], -1e-4), 0.0)
    gx, gy = cam.x + dist * d[..., 0], cam.y + dist * d[..., 1]
    fade = np.exp(-dist / 6.0)[..., None]  # fine texture would alias far away
    coarse = _sample(tile, gx * 9, gy * 9)[..., None]
    fine = _sample(tile, gx * 60 + 37, gy * 60 + 11)[..., None]
    tex = 0.75 + 0.35 * coarse + fade * 0.35 * (fine - 0.5)

    row_d = np.min(np.abs(gy[..., None] - np.array(ROW_YS)[None, None, :]), -1)
    in_rows = (gx > ROW_SPAN_X[0] - 0.3) & (gx < ROW_SPAN_X[1] + 0.3)
    bed = (np.clip(1 - row_d / 0.32, 0, 1) * in_rows)[..., None]
    lane = (np.clip((row_d - 0.3) / 0.15, 0, 1) * in_rows)[..., None]
    soil = SOIL * (1 - bed) + SOIL_WET * bed
    soil = soil * (1 + 0.12 * lane * (fine - 0.3))
    inside = ((np.abs(gx) < FENCE_X) & (np.abs(gy) < FENCE_Y))[..., None]
    grass = GRASS * (0.8 + 0.4 * _sample(tile, gx * 20, gy * 20)[..., None])
    # Weeds along the fence line and tufts in the lanes.
    edge = np.clip(1 - (np.minimum(FENCE_X - np.abs(gx), FENCE_Y - np.abs(gy))) / 0.6, 0, 1)[..., None]
    tufts = (np.clip((_sample(tile, gx * 30 + 5, gy * 30 + 9) - 0.78) * 6, 0, 1)[..., None]
             * lane * 0.8)
    soil = soil * (1 - np.maximum(edge * 0.8, tufts)) + grass * np.maximum(edge * 0.8, tufts)
    ground_col = np.where(inside, soil, grass) * tex
    haze = 1 - np.exp(-dist / 55.0)[..., None]
    ground_col = ground_col * (1 - haze) + HAZE * haze
    horizon = ground[..., None] & (dist[..., None] < 400)
    img = np.where(horizon, ground_col, img)
    return img.astype(np.float32)


def _draw_primitives(img, cam: Camera, prims) -> None:
    import cv2

    prims.sort(key=lambda p: -p[0])
    for depth, kind, data in prims:
        if kind == "poly":
            pts, color = data
            cv2.fillPoly(img, [pts], color, cv2.LINE_AA)
        elif kind == "leaf":
            pts, rib, color = data
            cv2.fillPoly(img, [pts], color, cv2.LINE_AA)
            if len(pts) > 8 and cv2.arcLength(pts.astype(np.float32), True) > 60:
                cv2.polylines(img, [pts], True, _shade(color, 0.72), 1, cv2.LINE_AA)
                cv2.polylines(img, [rib], False, _shade(color, 1.25), 1, cv2.LINE_AA)
        elif kind == "line":
            a, b, thick, color = data
            cv2.line(img, a, b, color, thick, cv2.LINE_AA)
        elif kind == "disc":
            centre, radius, color, highlight = data
            cv2.circle(img, centre, radius, color, -1, cv2.LINE_AA)
            if highlight and radius >= 4:
                hl = (centre[0] - radius // 3, centre[1] - radius // 3)
                cv2.circle(img, hl, max(1, radius // 3), _shade(color, 1.6), -1, cv2.LINE_AA)


def _leaf_prim(cam: Camera, leaf: Leaf, sway: np.ndarray):
    s = np.linspace(0, 1, 9)[:, None]
    p1, p2 = leaf.p1 + sway * 0.4, leaf.p2 + sway
    mid = (1 - s) ** 2 * leaf.p0 + 2 * (1 - s) * s * p1 + s ** 2 * p2
    tangent = 2 * (1 - s) * (p1 - leaf.p0) + 2 * s * (p2 - p1)
    pc_mid = cam.to_cam(mid)
    if np.any(pc_mid[:, 2] < NEAR):
        return None
    # Leaf blade: widen perpendicular to the tangent and the view ray.
    view = mid - cam.c
    side = np.cross(tangent, view)
    side /= np.linalg.norm(side, axis=1, keepdims=True) + 1e-9
    half = leaf.width / 2 * np.sin(np.pi * s[:, 0]) ** 0.7
    left, right = mid + side * half[:, None], mid - side * half[:, None]
    outline = np.concatenate([left, right[::-1]])
    pc = cam.to_cam(outline)
    if np.any(pc[:, 2] < NEAR):
        return None
    px = cam.project(pc)
    if np.all((px[:, 0] < -50) | (px[:, 0] > cam.width + 50)) or \
            np.all((px[:, 1] < -50) | (px[:, 1] > cam.height + 50)):
        return None
    normal = np.cross(tangent[4], side[4])
    light = 0.62 + 0.5 * abs(float(normal @ SUN) / (np.linalg.norm(normal) + 1e-9))
    rib = cam.project(pc_mid).round().astype(np.int32)
    return (float(pc_mid[:, 2].mean()), "leaf",
            (px.round().astype(np.int32), rib, _shade(leaf.color, light)))


def _segment_prim(cam: Camera, a, b, width, color, min_px=1):
    seg = _clip_segment(*cam.to_cam(np.stack([a, b])))
    if seg is None:
        return None
    pa, pb = cam.project(np.stack(seg))
    depth = float((seg[0][2] + seg[1][2]) / 2)
    if max(abs(pa[0]), abs(pb[0])) > 1e5 or max(abs(pa[1]), abs(pb[1])) > 1e5:
        return None
    thick = max(min_px, int(round(cam.fx * width / max(depth, NEAR))))
    return (depth, "line", (tuple(pa.round().astype(int)), tuple(pb.round().astype(int)),
                            min(thick, 200), color))


def _disc_prim(cam: Camera, centre, radius, color, highlight=True):
    pc = cam.to_cam(np.asarray(centre)[None])[0]
    if pc[2] < NEAR + radius:
        return None
    px = cam.project(pc[None])[0]
    r = int(round(cam.fx * radius / pc[2]))
    if r < 1 or px[0] < -r or px[0] > cam.width + r or px[1] < -r or px[1] > cam.height + r:
        return None
    return (float(pc[2]), "disc", (tuple(px.round().astype(int)), r, color, highlight))


def _box_faces(cam: Camera, x0, x1, y0, y1, z0, z1, wall, roof):
    corners = {
        "x0": [(x0, y0), (x0, y1)], "x1": [(x1, y1), (x1, y0)],
        "y0": [(x1, y0), (x0, y0)], "y1": [(x0, y1), (x1, y1)],
    }
    normals = {"x0": (-1, 0, 0), "x1": (1, 0, 0), "y0": (0, -1, 0), "y1": (0, 1, 0)}
    prims = []
    faces = [(np.array([[*a, z0], [*b, z0], [*b, z1], [*a, z1]], float), normals[k], wall)
             for k, (a, b) in corners.items()]
    faces.append((np.array([[x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float),
                  (0, 0, 1), roof))
    for quad, normal, color in faces:
        n = np.array(normal, float)
        if n @ (cam.c - quad.mean(0)) <= 0:
            continue
        pc = cam.to_cam(quad)
        if np.any(pc[:, 2] < NEAR):
            continue
        light = 0.55 + 0.45 * max(0.0, float(n @ SUN))
        depth = float(np.linalg.norm(quad.mean(0) - cam.c))
        prims.append((depth, "poly", (cam.project(pc).round().astype(np.int32),
                                      _shade(color, light))))
    return prims


def render(cam: Camera, t: float = 0.0) -> np.ndarray:
    """Render the farm from ``cam`` at time ``t`` seconds (wind sway, drifting clouds)."""
    import cv2

    img = _background(cam, t)
    prims: list = []

    for x, y, h, r, shade in far_trees():
        trunk = _segment_prim(cam, (x, y, 0), (x, y, h * 0.5), 0.35, (40, 55, 70))
        if trunk:
            prims.append(trunk)
        for k, (dx, dy, dz, rk) in enumerate(((0, 0, 0.62, 1.0), (0.5, 0.3, 0.5, 0.75),
                                              (-0.4, -0.2, 0.75, 0.7))):
            disc = _disc_prim(cam, (x + dx * r, y + dy * r, h * dz), r * rk,
                              _shade((50, 105, 58), shade * (0.85 + 0.12 * k)), highlight=False)
            if disc:
                prims.append(disc)
    for x, y, h, r in NEAR_TREES:
        trunk = _segment_prim(cam, (x, y, 0), (x, y, h * 0.6), 0.22, (45, 65, 85))
        if trunk:
            prims.append(trunk)
        for k, (dx, dy, dz, rk) in enumerate(((0, 0, 0.75, 1.0), (0.45, 0.3, 0.62, 0.7),
                                              (-0.4, -0.35, 0.85, 0.65), (0.1, -0.5, 0.95, 0.55))):
            disc = _disc_prim(cam, (x + dx * r, y + dy * r, h * dz), r * rk,
                              _shade((48, 120, 60), 0.85 + 0.1 * k), highlight=False)
            if disc:
                prims.append(disc)
    x0, x1, y0, y1, sh = SHED
    prims += _box_faces(cam, x0, x1, y0, y1, 0.0, sh, (52, 62, 150), (120, 122, 128))
    posts = fence_posts()
    for px, py in posts:
        post = _segment_prim(cam, (px, py, 0), (px, py, 1.2), 0.08, (70, 100, 130))
        if post:
            prims.append(post)
    for (ax, ay), (bx, by) in zip(posts, posts[2:]):
        if abs(ax - bx) + abs(ay - by) > 2.2:
            continue
        for z in (0.45, 0.95):
            wire = _segment_prim(cam, (ax, ay, z), (bx, by, z), 0.006, (150, 150, 145))
            if wire:
                prims.append(wire)

    wind = np.array([math.cos(0.3), math.sin(0.3), 0.0])
    for plant in plants():
        rel = np.array([plant.x - cam.x, plant.y - cam.y])
        dist = float(np.hypot(*rel))
        if dist > 30 or rel @ cam.f[:2] < -0.6:
            continue
        lod = 1 if dist < 9 else 2
        sway_amp = 0.012 * math.sin(t * 1.7 + plant.phase) + 0.006 * math.sin(t * 3.1 + plant.phase)
        for stalk in plant.stalks:
            seg = _segment_prim(cam, stalk[0], stalk[1] + wind * sway_amp * 2, stalk[2], stalk[3])
            if seg:
                prims.append(seg)
        for leaf in plant.leaves[::lod]:
            sway = wind * sway_amp * (1 + 2 * leaf.p2[2])
            prim = _leaf_prim(cam, leaf, sway)
            if prim:
                prims.append(prim)
        for centre, radius, color in plant.fruit:
            disc = _disc_prim(cam, centre + wind * sway_amp, radius, color)
            if disc:
                prims.append((disc[0] - 0.05, *disc[1:]))

    canvas = np.ascontiguousarray(np.clip(img, 0, 255).astype(np.uint8))
    _draw_primitives(canvas, cam, prims)
    return finish(canvas, seed=int(t * 1000) & 0xFFFF)


def finish(img: np.ndarray, seed: int = 0) -> np.ndarray:
    """Lens softness, vignetting and sensor noise so frames look like a real camera."""
    import cv2

    img = cv2.GaussianBlur(img, (0, 0), 0.7).astype(np.float32)
    h, w = img.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    r2 = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
    img *= (1 - 0.22 * r2)[..., None]
    img += np.random.default_rng(seed).normal(0, 3.0, img.shape).astype(np.float32)
    return np.clip(img, 0, 255).astype(np.uint8)


# ---------- robot cameras ----------

def robot_pose() -> tuple[float, float, float, bool]:
    """(x, y, yaw, standing) of the simulated B2."""
    from .base import SimBase

    base = SimBase()
    x, y = base.data["position"][:2]
    return float(x), float(y), float(base.data["yaw"]), base.data["mode"] not in (5, 7)


def camera_for(name: str) -> tuple[Camera, str]:
    """Simulated camera rig at the current B2 pose; returns (camera, style)."""
    x, y, yaw, standing = robot_pose()
    z = 0.55 if standing else 0.32
    fwd = np.array([math.cos(yaw), math.sin(yaw)])
    if name == "b2_back":
        return Camera(x - 0.45 * fwd[0], y - 0.45 * fwd[1], z, yaw + math.pi, math.radians(10)), "rgb"
    if name.startswith("realsense") or "arm" in name:
        # Wrist camera on the Piper arm, looking down at the crop row beside the lane.
        side = np.array([-fwd[1], fwd[0]]) * 0.3
        return Camera(x + 0.5 * fwd[0] + side[0], y + 0.5 * fwd[1] + side[1], z + 0.55,
                      yaw + 0.55, math.radians(52), 640, 360, 69.0), "arm"
    if name == "icamera":
        return Camera(x + 0.3 * fwd[0], y + 0.3 * fwd[1], z + 0.15, yaw, math.radians(16),
                      752, 480, 50.0), "ndvi"
    if name == "b2_front":
        return Camera(x + 0.45 * fwd[0], y + 0.45 * fwd[1], z, yaw, math.radians(10)), "rgb"
    return Camera(x + 0.3 * fwd[0], y + 0.3 * fwd[1], z + 0.35, yaw, math.radians(18),
                  640, 480, 70.0), "rgb"


def _ndvi(frame: np.ndarray) -> np.ndarray:
    """Pseudo multispectral vegetation index (NDVI-like) as a red-yellow-green false colour."""
    import cv2

    b, g, r = (frame[..., i].astype(np.float32) for i in range(3))
    nir = 0.25 * r + 1.6 * np.maximum(g - 0.6 * r - 0.25 * b, 0) + 0.3 * b
    ndvi = (nir - r) / (nir + r + 1e-3)
    idx = np.clip((ndvi + 0.4) / 1.1 * 255, 0, 255).astype(np.uint8)
    stops = np.array([[38, 48, 165], [70, 180, 245], [140, 230, 250], [80, 200, 120],
                      [30, 120, 26]], np.float32)  # BGR red -> yellow -> green
    xs = np.linspace(0, 255, len(stops))
    lut = np.stack([np.interp(np.arange(256), xs, stops[:, c]) for c in range(3)], -1)
    out = lut[idx].astype(np.uint8)
    out = cv2.GaussianBlur(out, (0, 0), 1.2)
    out[::4, :] = (out[::4, :] * 0.9).astype(np.uint8)  # mosaic grid texture of the sensor
    out[:, ::4] = (out[:, ::4] * 0.9).astype(np.uint8)
    return out


def _gripper(img: np.ndarray, t: float) -> None:
    import cv2

    h, w = img.shape[:2]
    gap = int(w * (0.16 + 0.01 * math.sin(t)))
    for sign in (-1, 1):
        cx = w // 2 + sign * gap
        pts = np.array([[cx - 34, h], [cx - 22, int(h * 0.78)], [cx + 22, int(h * 0.78)],
                        [cx + 34, h]], np.int32)
        cv2.fillPoly(img, [pts], (55, 58, 62), cv2.LINE_AA)
        cv2.polylines(img, [pts], True, (95, 98, 104), 2, cv2.LINE_AA)


@lru_cache(maxsize=None)
def photos(kind: str) -> tuple[Path, ...]:
    """Real plant photos of one kind ("field" or "closeup") used for simulated camera frames."""
    return tuple(sorted((PHOTO_DIR / kind).glob("*.jpg")))


@lru_cache(maxsize=16)
def _load_photo(path: Path) -> np.ndarray:
    import cv2

    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read simulation photo {path}")
    return img


def photo_view(cam: Camera, kind: str, t: float = 0.0) -> np.ndarray | None:
    """What ``cam`` sees, as a crop of a real plant photo; None when no photos are installed.

    The photo is picked from the camera heading (90 degree sectors) and the 2 m grid cell the
    camera is in, so turning or walking changes the view. Within a cell the remaining heading
    pans the crop, the distance walked zooms in, a lower camera looks further down, and ``t``
    adds the slight sway of a camera on a walking robot.
    """
    files = photos(kind)
    if not files:
        return None
    import cv2

    turns = (cam.yaw % (2 * math.pi)) / (math.pi / 2)
    sector = int(round(turns)) % 4
    pan = turns - round(turns)  # -0.5 .. 0.5
    heading = sector * math.pi / 2
    along = cam.x * math.cos(heading) + cam.y * math.sin(heading)
    across = cam.y * math.cos(heading) - cam.x * math.sin(heading)
    cell, walked = divmod(along + 1.0, 2.0)
    img = _load_photo(files[(sector + 4 * int(cell) + 7 * round(across / 2.0)) % len(files)])

    h, w = img.shape[:2]
    aspect = cam.width / cam.height
    cw = w * 0.86 * (1.0 - 0.15 * walked)
    ch = cw / aspect
    if ch > h * 0.96:
        ch = h * 0.96
        cw = ch * aspect
    low = max(-1.0, min(1.0, (0.55 - cam.z) / 0.25 + (math.degrees(cam.pitch) - 10.0) / 40.0))
    cx = w / 2 + pan * (w - cw) + 0.012 * w * math.sin(0.9 * t)
    cy = h / 2 + 0.5 * low * (h - ch) + 0.008 * h * math.sin(1.7 * t + 0.6)
    s = cam.width / cw
    m = np.float32([[s, 0, cam.width / 2 - s * cx], [0, s, cam.height / 2 - s * cy]])
    view = cv2.warpAffine(img, m, (cam.width, cam.height), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT)
    return finish(view, seed=int(t * 1000) & 0xFFFF)


def camera_frame(name: str, t: float = 0.0, stamp: str = "") -> np.ndarray:
    """One simulated frame from the named robot camera."""
    import cv2

    cam, style = camera_for(name)
    frame = photo_view(cam, "closeup" if style == "arm" else "field", t)
    if frame is None:
        frame = render(cam, t)
    if style == "arm":
        _gripper(frame, t)
    if style == "ndvi":
        frame = _ndvi(frame)
    label = f"SIM  {name}  {stamp}".strip()
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    overlay = frame.copy()
    cv2.rectangle(overlay, (8, 8), (20 + tw, 18 + th), (20, 40, 20), -1)
    frame = cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)
    cv2.putText(frame, label, (14, 13 + th), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (210, 245, 210), 1,
                cv2.LINE_AA)
    return frame


# ---------- point clouds ----------

def _pack_rgb(bgr: np.ndarray) -> np.ndarray:
    c = np.clip(bgr, 0, 255).astype(np.uint32)
    return (c[:, 2] << 16) | (c[:, 1] << 8) | c[:, 0]


def farm_cloud(seed: int = 1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Whole-plot point cloud: (xyz float32 Nx3, BGR float32 Nx3, intensity float32 N)."""
    rng = np.random.default_rng(seed)
    pts, cols, inten = [], [], []

    def add(p, c, i):
        pts.append(np.asarray(p, np.float32))
        cols.append(np.asarray(c, np.float32))
        inten.append(np.asarray(i, np.float32))

    # Ground: soil inside the fence with raised beds, grass outside.
    n = 90000
    g = np.stack([rng.uniform(-11, 11, n), rng.uniform(-10.5, 10.5, n)], 1)
    row_d = np.min(np.abs(g[:, 1:2] - np.array(ROW_YS)[None]), 1)
    in_rows = (g[:, 0] > ROW_SPAN_X[0] - 0.3) & (g[:, 0] < ROW_SPAN_X[1] + 0.3)
    bed = np.clip(1 - row_d / 0.32, 0, 1) * in_rows
    z = 0.02 * np.sin(g[:, 0] * 0.7) + 0.015 * np.cos(g[:, 1] * 0.9) + 0.06 * bed
    z += rng.normal(0, 0.008, n)
    inside = (np.abs(g[:, 0]) < FENCE_X) & (np.abs(g[:, 1]) < FENCE_Y)
    soil = SOIL[None] * (1 - bed[:, None]) + SOIL_WET[None] * bed[:, None]
    col = np.where(inside[:, None], soil, GRASS[None]) * rng.uniform(0.8, 1.2, (n, 1))
    add(np.column_stack([g, z]), col, np.where(inside, 18 + 10 * bed, 35) + rng.normal(0, 3, n))

    # Crops: sample points along every leaf, stalk and fruit.
    for plant in plants():
        for leaf in plant.leaves:
            s = rng.random((14, 1))
            mid = (1 - s) ** 2 * leaf.p0 + 2 * (1 - s) * s * leaf.p1 + s ** 2 * leaf.p2
            off = rng.normal(0, leaf.width / 4, (14, 3)) * [1, 1, 0.3]
            add(mid + off, np.tile(leaf.color, (14, 1)) * rng.uniform(0.85, 1.15, (14, 1)),
                rng.normal(70, 6, 14))
        for a, b, width, color in plant.stalks:
            k = max(4, int(np.linalg.norm(b - a) / 0.03))
            s = rng.random((k, 1))
            add(a + s * (b - a) + rng.normal(0, width / 3, (k, 3)) * [1, 1, 0],
                np.tile(color, (k, 1)), rng.normal(60, 5, k))
        for centre, radius, color in plant.fruit:
            v = rng.normal(size=(20, 3))
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            add(centre + v * radius, np.tile(color, (20, 1)), rng.normal(95, 5, 20))

    # Fence posts and wires.
    posts = fence_posts()
    for px, py in posts:
        zz = rng.uniform(0, 1.2, 40)
        add(np.column_stack([px + rng.normal(0, .03, 40), py + rng.normal(0, .03, 40), zz]),
            np.tile((70, 100, 130), (40, 1)), rng.normal(120, 8, 40))
    for (ax, ay), (bx, by) in zip(posts, posts[2:]):
        if abs(ax - bx) + abs(ay - by) > 2.2:
            continue
        for wz in (0.45, 0.95):
            s = rng.random(40)
            add(np.column_stack([ax + s * (bx - ax), ay + s * (by - ay), np.full(40, wz)]),
                np.tile((150, 150, 145), (40, 1)), rng.normal(160, 8, 40))

    # Shed walls and roof.
    x0, x1, y0, y1, sh = SHED
    m = 6000
    face = rng.integers(0, 5, m)
    u, v = rng.random(m), rng.random(m)
    sx = np.select([face == 0, face == 1, face == 2, face == 3],
                   [np.full(m, x0), np.full(m, x1), x0 + u * (x1 - x0), x0 + u * (x1 - x0)],
                   x0 + u * (x1 - x0))
    sy = np.select([face == 0, face == 1, face == 2, face == 3],
                   [y0 + u * (y1 - y0), y0 + u * (y1 - y0), np.full(m, y0), np.full(m, y1)],
                   y0 + v * (y1 - y0))
    sz = np.where(face == 4, sh, v * sh)
    add(np.column_stack([sx, sy, sz]),
        np.where((face == 4)[:, None], [[120, 122, 128]], [[52, 62, 150]]),
        np.where(face == 4, 140, 90) + rng.normal(0, 5, m))

    # Trees: trunks and crowns.
    for x, y, h, r in NEAR_TREES:
        k = 1500
        v = rng.normal(size=(k, 3))
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        crown = np.array([x, y, h * 0.8]) + v * r * rng.uniform(0.75, 1.0, (k, 1)) * [1, 1, 0.8]
        add(crown, np.tile((48, 120, 60), (k, 1)) * rng.uniform(0.8, 1.15, (k, 1)),
            rng.normal(55, 6, k))
        zz = rng.uniform(0, h * 0.6, 120)
        a = rng.uniform(0, 2 * math.pi, 120)
        add(np.column_stack([x + 0.11 * np.cos(a), y + 0.11 * np.sin(a), zz]),
            np.tile((45, 65, 85), (120, 1)), rng.normal(80, 5, 120))

    return (np.concatenate(pts).astype(np.float32), np.concatenate(cols).astype(np.float32),
            np.concatenate(inten).astype(np.float32))


def lidar_scan(x: float, y: float, yaw: float, max_range: float = 15.0,
               seed: int = 2) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """What the B2 lidar sees from (x, y, yaw), in the robot frame: the farm cloud cropped to
    ``max_range``, thinned with distance and with range noise, plus a ring artefact near it."""
    pts, cols, inten = farm_cloud()
    rng = np.random.default_rng(seed)
    rel = pts[:, :2] - [x, y]
    dist = np.hypot(rel[:, 0], rel[:, 1])
    keep = (dist < max_range) & (dist > 0.6) & (rng.random(len(pts)) < np.clip(3.0 / (dist + 1e-3), 0.15, 1))
    c, s = math.cos(-yaw), math.sin(-yaw)
    local = np.column_stack([rel[keep, 0] * c - rel[keep, 1] * s,
                             rel[keep, 0] * s + rel[keep, 1] * c, pts[keep, 2] - 0.55])
    local += rng.normal(0, 0.01, local.shape) * (dist[keep, None] / 5)
    return local.astype(np.float32), cols[keep], inten[keep]


def write_pcd(path, xyz: np.ndarray, bgr: np.ndarray | None = None,
              intensity: np.ndarray | None = None) -> int:
    """Binary PCD (v0.7) readable by PCL, Open3D, CloudCompare and the web UI viewer."""
    n = len(xyz)
    fields, sizes, types = ["x", "y", "z"], [4, 4, 4], ["F", "F", "F"]
    dtype = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    if bgr is not None:
        fields.append("rgb"); sizes.append(4); types.append("U"); dtype.append(("rgb", "<u4"))
    if intensity is not None:
        fields.append("intensity"); sizes.append(4); types.append("F"); dtype.append(("intensity", "<f4"))
    rec = np.empty(n, dtype=dtype)
    rec["x"], rec["y"], rec["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    if bgr is not None:
        rec["rgb"] = _pack_rgb(bgr)
    if intensity is not None:
        rec["intensity"] = intensity
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\n"
        f"FIELDS {' '.join(fields)}\nSIZE {' '.join(map(str, sizes))}\n"
        f"TYPE {' '.join(types)}\nCOUNT {' '.join('1' for _ in fields)}\n"
        f"WIDTH {n}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {n}\nDATA binary\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode())
        f.write(rec.tobytes())
    return n


# ---------- occupancy map ----------

def occupancy_map(robot_xy: tuple[float, float] | None = None) -> np.ndarray:
    """nav2-style occupancy grid (0 occupied, 254 free, 205 unknown) of the plot, 0.05 m cells,
    origin (-10, -10) - matching the map YAML written by `./robot map save` in SIM mode."""
    import cv2

    img = np.full((MAP_SIZE, MAP_SIZE), 205, np.uint8)

    def px(x, y):
        return (int(round((x - MAP_ORIGIN) / MAP_RES)), MAP_SIZE - 1 - int(round((y - MAP_ORIGIN) / MAP_RES)))

    cv2.rectangle(img, px(-FENCE_X - 0.6, FENCE_Y + 0.6), px(FENCE_X + 0.6, -FENCE_Y - 0.6), 254, -1)
    cv2.rectangle(img, px(-FENCE_X, FENCE_Y), px(FENCE_X, -FENCE_Y), 0, 2)
    for plant in plants():
        r = {"lettuce": 0.14, "tomato": 0.2, "maize": 0.17}[plant.crop]
        cv2.circle(img, px(plant.x, plant.y), max(1, int(r / MAP_RES)), 0, -1)
    x0, x1, y0, y1, _ = SHED
    cv2.rectangle(img, px(x0, y1), px(x1, y0), 0, -1)
    for x, y, _, _ in NEAR_TREES:
        cv2.circle(img, px(x, y), 4, 0, -1)
    if robot_xy is not None:
        cv2.circle(img, px(*robot_xy), 6, 100, -1)
    return img

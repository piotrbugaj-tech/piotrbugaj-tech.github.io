"""Procedural interior/exterior scenes with exact ground truth.

The renderer ray-casts a box-shaped room (walls, floor, ceiling, furniture,
window with exterior view) in linear RGB and then simulates a bracketing
camera: exposure, sensor noise, clipping, tone curve (CRF), lens distortion,
vignetting, lateral chromatic aberration, tripod/handheld shake and a moving
object (ghost).  Everything that the processing pipeline must undo is known,
so stages can be tested against ground truth.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def kelvin_to_rgb(kelvin: float) -> np.ndarray:
    """Approximate linear-sRGB colour of a black body, normalised to G=1."""
    # Tanner Helland approximation (display sRGB) linearised.
    t = kelvin / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
        b = 255.0
    rgb = np.clip(np.array([r, g, b]) / 255.0, 1e-4, 1.0)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    # normalise so that 6500K is neutral
    ref = np.array([1.0, 0.9547, 0.9228])  # value of the approximation at ~6500K, linear
    lin = lin / ref
    return (lin / lin[1]).astype(np.float32)


def _hash_noise(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    h = np.sin(x * 127.1 + y * 311.7 + seed * 74.7) * 43758.5453
    return h - np.floor(h)


def value_noise(x: np.ndarray, y: np.ndarray, seed: int = 0) -> np.ndarray:
    xi, yi = np.floor(x), np.floor(y)
    xf, yf = x - xi, y - yi
    u = xf * xf * (3 - 2 * xf)
    v = yf * yf * (3 - 2 * yf)
    a = _hash_noise(xi, yi, seed)
    b = _hash_noise(xi + 1, yi, seed)
    c = _hash_noise(xi, yi + 1, seed)
    d = _hash_noise(xi + 1, yi + 1, seed)
    return (a + (b - a) * u) + ((c + (d - c) * u) - (a + (b - a) * u)) * v


def fbm(x: np.ndarray, y: np.ndarray, octaves: int = 4, seed: int = 0) -> np.ndarray:
    acc = np.zeros_like(x, dtype=np.float32)
    amp, freq, norm = 0.5, 1.0, 0.0
    for o in range(octaves):
        acc += amp * value_noise(x * freq, y * freq, seed + o * 17).astype(np.float32)
        norm += amp
        amp *= 0.5
        freq *= 2.03
    return acc / norm


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def srgb_oetf(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def camera_crf(x: np.ndarray) -> np.ndarray:
    """A typical in-camera JPEG tone curve: sRGB gamma plus a gentle S-curve."""
    y = srgb_oetf(x)
    s = y + 0.12 * y * (1 - y) * (2 * y - 1) * 2.0  # mild contrast around mid-tones
    return np.clip(s, 0.0, 1.0)


# ---------------------------------------------------------------------------
# scene description
# ---------------------------------------------------------------------------


@dataclass
class Box:
    lo: tuple
    hi: tuple
    albedo: tuple
    texture: str = "fabric"  # fabric | wood | plain | tv
    emissive: float = 0.0


@dataclass
class Sphere:
    center: tuple
    radius: float
    albedo: tuple
    emissive: float = 0.0
    emissive_kelvin: float = 2700.0
    texture: str = "leaf"


@dataclass
class Light:
    pos: tuple
    intensity: float
    kelvin: float = 2700.0
    downward: bool = False


@dataclass
class SceneSpec:
    name: str = "living_room"
    kind: str = "interior"  # interior | exterior
    room: tuple = (5.0, 2.7, 6.0)  # width (x), height (y), depth (z)
    window_wall: str = "back"  # back | right
    window_rect: tuple = (-1.7, 0.85, 0.5, 2.3)  # (u0, v0, u1, v1) on the wall plane
    mullions: tuple = (1, 1)  # vertical, horizontal bars
    wall_albedo: tuple = (0.80, 0.80, 0.80)
    accent_wall: str = ""  # "left" -> coloured left wall
    accent_albedo: tuple = (0.42, 0.55, 0.45)
    ceiling_albedo: tuple = (0.86, 0.86, 0.86)
    floor_albedo: tuple = (0.50, 0.34, 0.20)
    sky_lum: float = 9.0
    ground_lum: float = 2.5
    sun_elevation_deg: float = 32.0
    sun_azimuth_deg: float = 15.0  # 0 = straight through a back-wall window
    sun_strength: float = 9.0
    sun_kelvin: float = 5200.0
    sky_kelvin: float = 8000.0
    ambient: float = 0.05
    boxes: list = field(default_factory=list)
    spheres: list = field(default_factory=list)
    lights: list = field(default_factory=list)
    door: bool = True
    pictures: bool = True
    rug: bool = True
    seed: int = 1


@dataclass
class CameraSpec:
    width: int = 2400
    height: int = 1600
    hfov_deg: float = 84.0
    pos: tuple = (0.35, 1.45, 0.35)
    yaw_deg: float = -6.0
    pitch_deg: float = -7.0  # negative = looking down -> verticals converge downward
    roll_deg: float = 1.2
    k1: float = 0.06  # barrel distortion (r_u = r_d (1 + k1 r_n^2))
    vignetting: float = 0.35  # relative fall-off at the corner
    ca: float = 0.0012  # lateral CA: R scaled by (1+ca), B by (1-ca)
    supersample: int = 2


def default_living_room(seed: int = 1) -> SceneSpec:
    s = SceneSpec(name="living_room", seed=seed)
    s.boxes = [
        Box((-2.3, 0.0, 3.2), (-0.6, 0.45, 4.1), (0.20, 0.23, 0.28), "fabric"),  # sofa seat
        Box((-2.3, 0.45, 3.85), (-0.6, 0.85, 4.1), (0.20, 0.23, 0.28), "fabric"),  # sofa back
        Box((-0.3, 0.0, 3.0), (0.7, 0.42, 3.6), (0.32, 0.20, 0.11), "wood"),  # coffee table
        Box((1.55, 0.0, 4.8), (2.45, 0.9, 5.95), (0.82, 0.82, 0.80), "plain"),  # cabinet
        Box((1.7, 1.25, 5.97), (2.3, 1.62, 6.0), (0.02, 0.02, 0.02), "tv"),  # TV on back wall
    ]
    s.spheres = [
        Sphere((2.0, 1.05, 5.4), 0.18, (0.9, 0.85, 0.7), emissive=6.0, emissive_kelvin=2700, texture="plain"),
        Sphere((-2.1, 0.65, 5.4), 0.35, (0.09, 0.28, 0.07), texture="leaf"),
        Sphere((-2.1, 1.05, 5.45), 0.28, (0.10, 0.30, 0.08), texture="leaf"),
    ]
    s.lights = [
        Light((2.0, 1.05, 5.4), 0.30, 2700),
        Light((-0.8, 2.62, 2.5), 0.45, 3000, downward=True),
        Light((1.2, 2.62, 4.0), 0.45, 3000, downward=True),
    ]
    return s


def default_bedroom(seed: int = 2) -> SceneSpec:
    s = SceneSpec(name="bedroom", room=(4.2, 2.6, 5.0), window_wall="right",
                  window_rect=(1.6, 0.9, 3.6, 2.25), mullions=(1, 0), seed=seed,
                  sky_lum=7.0, sun_strength=0.0, accent_wall="left", ambient=0.04)
    s.boxes = [
        Box((-1.2, 0.0, 2.6), (0.9, 0.55, 4.8), (0.85, 0.84, 0.82), "fabric"),  # bed
        Box((-1.2, 0.55, 4.6), (0.9, 1.2, 4.98), (0.30, 0.22, 0.15), "wood"),  # headboard
        Box((1.2, 0.0, 4.3), (1.7, 0.55, 4.8), (0.35, 0.24, 0.14), "wood"),  # night stand
    ]
    s.spheres = [Sphere((1.45, 0.75, 4.55), 0.13, (0.9, 0.85, 0.7), emissive=5.0, emissive_kelvin=2700, texture="plain")]
    s.lights = [Light((1.45, 0.75, 4.55), 0.18, 2700), Light((0.0, 2.55, 2.5), 0.35, 2900, downward=True)]
    return s


def default_kitchen(seed: int = 3) -> SceneSpec:
    s = SceneSpec(name="kitchen", room=(5.5, 2.75, 5.5), window_rect=(-2.2, 1.0, -0.4, 2.3),
                  mullions=(2, 1), seed=seed, sky_lum=12.0, sun_strength=12.0, sun_azimuth_deg=-20,
                  floor_albedo=(0.62, 0.62, 0.60), ambient=0.03)
    s.boxes = [
        Box((-2.75, 0.0, 4.9), (2.75, 0.9, 5.5), (0.88, 0.88, 0.86), "plain"),  # counters
        Box((-2.75, 0.9, 4.9), (2.75, 0.94, 5.5), (0.20, 0.20, 0.21), "plain"),  # worktop
        Box((0.2, 1.5, 5.15), (2.75, 2.3, 5.5), (0.88, 0.88, 0.86), "plain"),  # upper cabinets
        Box((-0.9, 0.0, 2.6), (0.9, 0.92, 3.6), (0.80, 0.80, 0.78), "plain"),  # island
        Box((-0.95, 0.92, 2.55), (0.95, 0.96, 3.65), (0.36, 0.23, 0.12), "wood"),  # island top
    ]
    s.spheres = [Sphere((-0.5, 2.1, 3.1), 0.12, (0.9, 0.9, 0.8), emissive=7.0, emissive_kelvin=2700, texture="plain"),
                 Sphere((0.5, 2.1, 3.1), 0.12, (0.9, 0.9, 0.8), emissive=7.0, emissive_kelvin=2700, texture="plain")]
    s.lights = [Light((-0.5, 2.0, 3.1), 0.25, 2700), Light((0.5, 2.0, 3.1), 0.25, 2700),
                Light((1.5, 2.65, 1.5), 0.4, 3200, downward=True)]
    return s


# ---------------------------------------------------------------------------
# exterior environment (seen through windows, or for exterior shots)
# ---------------------------------------------------------------------------


class Environment:
    def __init__(self, spec: SceneSpec):
        self.spec = spec
        rng = np.random.default_rng(spec.seed + 100)
        self.sky_col = kelvin_to_rgb(spec.sky_kelvin)
        self.sun_col = kelvin_to_rgb(spec.sun_kelvin)
        n = 64
        self.bld_h = rng.uniform(0.04, 0.30, n).astype(np.float32)
        self.bld_col = rng.choice(np.array([[0.62, 0.55, 0.45], [0.55, 0.30, 0.22], [0.60, 0.60, 0.62],
                                            [0.78, 0.74, 0.66], [0.45, 0.47, 0.50]], np.float32), n)
        self.has_tree = rng.random(n) < 0.45
        el = math.radians(spec.sun_elevation_deg)
        az = math.radians(spec.sun_azimuth_deg)
        # sun direction (pointing towards the sun) in room coordinates
        if spec.window_wall == "right":
            self.sun_dir = np.array([math.cos(el) * math.cos(az), math.sin(el), math.cos(el) * math.sin(az)], np.float32)
        else:
            self.sun_dir = np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)], np.float32)
        # average sky/ground radiance for cheap window-light integration
        self.sky_avg = (self.sky_col * spec.sky_lum * np.array([0.85, 0.92, 1.0], np.float32)).astype(np.float32)
        self.ground_avg = (np.array([0.35, 0.38, 0.28], np.float32) * spec.ground_lum).astype(np.float32)

    def radiance(self, d: np.ndarray) -> np.ndarray:
        """Exterior radiance for unit directions d (N,3)."""
        s = self.spec
        dx, dy, dz = d[:, 0], d[:, 1], d[:, 2]
        az = np.arctan2(dx, dz) if s.window_wall != "right" else np.arctan2(dz, dx)
        el = np.arcsin(np.clip(dy, -1, 1))
        idx = np.floor((az + math.pi) / (2 * math.pi) * 64 * 4).astype(np.int64) % 64
        h = self.bld_h[idx]
        # tree crowns: smooth, independent of the building blocks
        presence = smoothstep(0.42, 0.58, fbm(az * 5.0 + 11.0, np.zeros_like(az), 3, s.seed + 4))
        crown = 0.10 + 0.16 * fbm(az * 22.0, el * 6.0, 4, s.seed + 5)
        tree_h = np.where(presence > 0.5, crown * (0.6 + 0.4 * presence), 0.0)
        out = np.zeros((d.shape[0], 3), np.float32)
        # sky
        t = smoothstep(-0.05, 0.9, el)
        horizon = np.array([0.95, 0.97, 1.0], np.float32)
        zenith = np.array([0.38, 0.55, 0.95], np.float32)
        sky = (horizon[None] * (1 - t[:, None]) + zenith[None] * t[:, None]) * s.sky_lum
        # clouds
        safe = np.maximum(dy, 0.05)
        cu, cv = dx / safe, dz / safe
        cl = fbm(cu * 1.3 + 3.0, cv * 1.3, 5, s.seed + 9)
        cloud = smoothstep(0.52, 0.72, cl) * smoothstep(0.02, 0.25, el)
        sky = sky * (1 - cloud[:, None]) + (s.sky_lum * 1.25 * cloud[:, None]) * np.array([1.0, 1.0, 1.0], np.float32)
        # sun glow
        cosang = d @ self.sun_dir
        sky += (s.sky_lum * 2.0 * np.power(np.clip(cosang, 0, 1), 64))[:, None]
        is_sky = (el > tree_h) & (el > h)
        out[is_sky] = sky[is_sky]
        # trees
        is_tree = (~is_sky) & (el > h) & (el > 0)
        leaf = 0.6 + 0.4 * fbm(az * 60, el * 60, 3, s.seed + 11)
        tree_col = np.array([0.10, 0.22, 0.06], np.float32)[None] * leaf[:, None] * s.ground_lum * 2.2
        out[is_tree] = tree_col[is_tree]
        # buildings with window grid
        is_bld = (~is_sky) & (~is_tree) & (el >= 0)
        col = self.bld_col[idx]
        gx = np.mod(az * 40, 1.0)
        gy = np.mod(el * 40, 1.0)
        win = (gx > 0.3) & (gx < 0.7) & (gy > 0.35) & (gy < 0.75)
        shade = 0.85 + 0.15 * fbm(az * 90, el * 90, 2, s.seed + 13)
        bcol = col * shade[:, None] * s.ground_lum * 1.6
        bcol[win] *= 0.35
        out[is_bld] = bcol[is_bld]
        # ground: lawn near, road further
        is_gnd = el < 0
        g = fbm(dx / np.maximum(-dy, 0.05) * 3, dz / np.maximum(-dy, 0.05) * 3, 4, s.seed + 21)
        lawn = np.array([0.16, 0.30, 0.08], np.float32)[None] * (0.7 + 0.6 * g[:, None]) * s.ground_lum * 1.6
        out[is_gnd] = lawn[is_gnd]
        return out


# ---------------------------------------------------------------------------
# room renderer
# ---------------------------------------------------------------------------


def _rot(yaw, pitch, roll):
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rx = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]])  # positive pitch -> look up
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return (ry @ rx @ rz).astype(np.float32)


def camera_rays(cam: CameraSpec, w: int, h: int, distort: bool = True):
    f = (w / 2) / math.tan(math.radians(cam.hfov_deg) / 2)
    u, v = np.meshgrid(np.arange(w, dtype=np.float32) + 0.5, np.arange(h, dtype=np.float32) + 0.5)
    x = (u - w / 2) / f
    y = -(v - h / 2) / f
    if distort and cam.k1:
        rmax2 = ((w / 2) ** 2 + (h / 2) ** 2) / f ** 2
        r2 = (x * x + y * y) / rmax2
        s = 1 + cam.k1 * r2
        x, y = x * s, y * s
    d = np.stack([x, y, np.ones_like(x)], -1).reshape(-1, 3)
    R = _rot(math.radians(cam.yaw_deg), math.radians(cam.pitch_deg), math.radians(cam.roll_deg))
    d = d @ R.T
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    return d.astype(np.float32), f


class Renderer:
    def __init__(self, spec: SceneSpec, neutral_lights: bool = False):
        self.s = spec
        self.env = Environment(spec)
        self.neutral = neutral_lights
        W, H, D = spec.room
        self.W, self.H, self.D = W, H, D
        # window geometry
        u0, v0, u1, v1 = spec.window_rect
        self.win = (u0, v0, u1, v1)
        if spec.window_wall == "back":
            self.win_normal = np.array([0, 0, 1], np.float32)
        else:
            self.win_normal = np.array([1, 0, 0], np.float32)
        self.frame_w = 0.06

    # -- window helpers ----------------------------------------------------
    def _win_uv(self, p):
        if self.s.window_wall == "back":
            return p[:, 0], p[:, 1]
        return p[:, 2], p[:, 1]

    def window_glass(self, uu, vv, soft=0.0):
        """1 where (u,v) on the window wall plane is glass (not frame/mullion)."""
        u0, v0, u1, v1 = self.win
        fw = self.frame_w
        inside = (uu > u0 + fw) & (uu < u1 - fw) & (vv > v0 + fw) & (vv < v1 - fw)
        nv, nh = self.s.mullions
        for i in range(1, nv + 1):
            uc = u0 + (u1 - u0) * i / (nv + 1)
            inside &= np.abs(uu - uc) > fw / 2
        for i in range(1, nh + 1):
            vc = v0 + (v1 - v0) * (0.62 if nh == 1 else i / (nh + 1))
            inside &= np.abs(vv - vc) > fw / 2
        return inside

    def window_any(self, uu, vv):
        u0, v0, u1, v1 = self.win
        return (uu >= u0) & (uu <= u1) & (vv >= v0) & (vv <= v1)

    # -- lighting ------------------------------------------------------------
    def _light_col(self, kelvin):
        return np.ones(3, np.float32) if self.neutral else kelvin_to_rgb(kelvin)

    def irradiance(self, p, n):
        s = self.s
        N = p.shape[0]
        E = np.zeros((N, 3), np.float32)
        # window area light: grid of samples on the glass
        u0, v0, u1, v1 = self.win
        nu, nv = 6, 4
        area = (u1 - u0) * (v1 - v0) * 0.85 / (nu * nv)
        sky = self.env.sky_avg if not self.neutral else np.full(3, self.env.sky_avg.mean(), np.float32)
        gnd = self.env.ground_avg if not self.neutral else np.full(3, self.env.ground_avg.mean(), np.float32)
        for i in range(nu):
            for j in range(nv):
                uc = u0 + (i + 0.5) / nu * (u1 - u0)
                vc = v0 + (j + 0.5) / nv * (v1 - v0)
                if s.window_wall == "back":
                    q = np.array([uc, vc, self.D], np.float32)
                else:
                    q = np.array([self.W / 2, vc, uc], np.float32)
                vvec = q[None] - p
                r2 = np.maximum((vvec * vvec).sum(1), 1e-3)
                w = vvec / np.sqrt(r2)[:, None]
                cos_p = np.clip((w * n).sum(1), 0, None)
                cos_w = np.clip(w @ self.win_normal, 0, None)
                up = smoothstep(-0.15, 0.15, w[:, 1])[:, None]
                L = gnd[None] * (1 - up) + sky[None] * up
                E += L * (cos_p * cos_w * area / r2)[:, None]
        # direct sun through the glass
        if s.sun_strength > 0:
            sd = self.env.sun_dir
            nd = float(sd @ self.win_normal)
            if nd > 1e-3:
                if s.window_wall == "back":
                    t = (self.D - p[:, 2]) / sd[2]
                else:
                    t = (self.W / 2 - p[:, 0]) / sd[0]
                hit = p + t[:, None] * sd[None]
                uu, vv = self._win_uv(hit)
                glass = self.window_glass(uu, vv).astype(np.float32)
                glass = cv2.GaussianBlur(glass.reshape(-1, 1), (1, 1), 0).ravel() if False else glass
                cosn = np.clip(n @ sd, 0, None)
                sc = self._light_col(s.sun_kelvin) if self.neutral else self.env.sun_col
                E += (s.sun_strength * glass * cosn * (t > 0))[:, None] * sc[None]
        # point lights
        for L in s.lights:
            q = np.array(L.pos, np.float32)
            vvec = q[None] - p
            r2 = np.maximum((vvec * vvec).sum(1), 2e-2)
            w = vvec / np.sqrt(r2)[:, None]
            cos_p = np.clip((w * n).sum(1), 0, None)
            if L.downward:
                cos_l = np.clip(-w[:, 1], 0, None) ** 1.5
            else:
                cos_l = 1.0
            E += (L.intensity * cos_p * cos_l / r2)[:, None] * self._light_col(L.kelvin)[None]
        # ambient (inter-reflections) with a crude corner occlusion term
        amb_col = (sky * 0.6 + np.array([1.0, 0.8, 0.6], np.float32) * 0.4 * (0 if self.neutral else 1)
                   + (np.ones(3, np.float32) * 0.4 if self.neutral else 0))
        amb_col = amb_col / amb_col.mean()
        dmin = np.minimum.reduce([p[:, 0] + self.W / 2, self.W / 2 - p[:, 0], p[:, 1], self.H - p[:, 1],
                                  self.D - p[:, 2]])
        ao = 1 - 0.45 * np.exp(-np.maximum(dmin, 0) / 0.18)
        E += (s.ambient * ao)[:, None] * amb_col[None] * 1.0
        return E

    # -- textures ----------------------------------------------------------
    def wall_albedo(self, which, p):
        s = self.s
        a = np.array(s.wall_albedo, np.float32)
        if which == s.accent_wall:
            a = np.array(s.accent_albedo, np.float32)
        if which == "ceiling":
            a = np.array(s.ceiling_albedo, np.float32)
        out = np.repeat(a[None], p.shape[0], 0)
        n = fbm(p[:, 0] * 9 + p[:, 2] * 7, p[:, 1] * 9 + p[:, 2] * 3, 3, s.seed + 31)
        out *= (0.985 + 0.03 * n)[:, None]
        if which in ("left", "right", "back"):
            base = p[:, 1] < 0.10  # baseboard
            out[base] = 0.88
        return out

    def floor_albedo(self, p):
        s = self.s
        a = np.array(s.floor_albedo, np.float32)
        plank = np.floor(p[:, 0] / 0.19)
        var = _hash_noise(plank, np.floor(p[:, 2] / 1.3 + plank * 0.37), s.seed)
        grain = fbm(p[:, 0] * 40, p[:, 2] * 3, 3, s.seed + 41)
        out = a[None] * (0.82 + 0.25 * var[:, None]) * (0.9 + 0.2 * grain[:, None])
        seam = np.mod(p[:, 0], 0.19) < 0.004
        out[seam] *= 0.6
        if s.rug:
            rug = (np.abs(p[:, 0] - 0.0) < 1.3) & (p[:, 2] > 2.4) & (p[:, 2] < 4.3)
            pat = 0.5 + 0.5 * np.sin(p[:, 0] * 14) * np.sin(p[:, 2] * 14)
            rc = np.array([0.55, 0.18, 0.15], np.float32)[None] * (0.6 + 0.4 * pat[:, None])
            out[rug] = rc[rug]
        return out

    def box_albedo(self, b: Box, p):
        a = np.array(b.albedo, np.float32)
        out = np.repeat(a[None], p.shape[0], 0)
        if b.texture == "fabric":
            out *= (0.85 + 0.3 * fbm(p[:, 0] * 60 + p[:, 2] * 20, p[:, 1] * 60, 2, 7))[:, None]
        elif b.texture == "wood":
            out *= (0.8 + 0.4 * fbm(p[:, 0] * 30, p[:, 2] * 4 + p[:, 1] * 4, 3, 9))[:, None]
        return out

    # -- main render -------------------------------------------------------
    def render(self, cam: CameraSpec, distort: bool = True, chunk: int = 400_000):
        ss = max(1, cam.supersample)
        w, h = cam.width * ss, cam.height * ss
        dirs, f = camera_rays(cam, w, h, distort)
        o = np.array(cam.pos, np.float32)
        img = np.zeros((dirs.shape[0], 3), np.float32)
        lab = np.zeros(dirs.shape[0], np.uint8)  # labels, see LABELS
        for a in range(0, dirs.shape[0], chunk):
            d = dirs[a:a + chunk]
            c, l = self._shade(o, d)
            img[a:a + chunk] = c
            lab[a:a + chunk] = l
        img = img.reshape(h, w, 3)
        lab = lab.reshape(h, w)
        if ss > 1:
            img = cv2.resize(img, (cam.width, cam.height), interpolation=cv2.INTER_AREA)
            lab = lab[ss // 2::ss, ss // 2::ss]
        return img, lab

    def _shade(self, o, d):
        s = self.s
        W, H, D = self.W, self.H, self.D
        n = d.shape[0]
        # exit point of the room box (camera is inside)
        with np.errstate(divide="ignore", invalid="ignore"):
            tx = np.where(d[:, 0] > 0, (W / 2 - o[0]) / d[:, 0], (-W / 2 - o[0]) / d[:, 0])
            ty = np.where(d[:, 1] > 0, (H - o[1]) / d[:, 1], (0 - o[1]) / d[:, 1])
            tz = np.where(d[:, 2] > 0, (D - o[2]) / d[:, 2], (0 - o[2]) / d[:, 2])
        tx = np.where(np.isfinite(tx), tx, 1e9)
        ty = np.where(np.isfinite(ty), ty, 1e9)
        tz = np.where(np.isfinite(tz), tz, 1e9)
        t = np.minimum(np.minimum(tx, ty), tz)
        axis = np.argmin(np.stack([tx, ty, tz], 1), 1)
        hit_kind = np.zeros(n, np.int32)  # 0 room, 1 box, 2 sphere
        hit_id = np.full(n, -1, np.int32)
        normal = np.zeros((n, 3), np.float32)
        # boxes
        for bi, b in enumerate(s.boxes):
            lo = np.array(b.lo, np.float32)
            hi = np.array(b.hi, np.float32)
            with np.errstate(divide="ignore", invalid="ignore"):
                inv = 1.0 / d
                t1 = (lo[None] - o[None]) * inv
                t2 = (hi[None] - o[None]) * inv
            tmin = np.nanmax(np.minimum(t1, t2), 1)
            tmax = np.nanmin(np.maximum(t1, t2), 1)
            ok = (tmax >= tmin) & (tmin > 1e-4) & (tmin < t)
            if ok.any():
                t = np.where(ok, tmin, t)
                hit_kind[ok] = 1
                hit_id[ok] = bi
                ent = np.argmax(np.minimum(t1, t2)[ok], 1)
                nn = np.zeros((ok.sum(), 3), np.float32)
                nn[np.arange(ok.sum()), ent] = -np.sign(d[ok][np.arange(ok.sum()), ent])
                normal[ok] = nn
        for si, sp in enumerate(s.spheres):
            c = np.array(sp.center, np.float32)
            oc = o - c
            bq = d @ oc
            cq = oc @ oc - sp.radius ** 2
            disc = bq * bq - cq
            ok = disc > 0
            ts = -bq - np.sqrt(np.maximum(disc, 0))
            ok &= (ts > 1e-4) & (ts < t)
            if ok.any():
                t = np.where(ok, ts, t)
                hit_kind[ok] = 2
                hit_id[ok] = si
                pp = o[None] + ts[ok][:, None] * d[ok]
                normal[ok] = (pp - c[None]) / sp.radius
        p = o[None] + t[:, None] * d
        col = np.zeros((n, 3), np.float32)
        labels = np.zeros(n, np.uint8)
        room = hit_kind == 0
        # room surfaces
        sides = {}
        sides["left"] = room & (axis == 0) & (d[:, 0] < 0)
        sides["right"] = room & (axis == 0) & (d[:, 0] > 0)
        sides["floor"] = room & (axis == 1) & (d[:, 1] < 0)
        sides["ceiling"] = room & (axis == 1) & (d[:, 1] > 0)
        sides["back"] = room & (axis == 2) & (d[:, 2] > 0)
        sides["front"] = room & (axis == 2) & (d[:, 2] < 0)
        nrm = {"left": (1, 0, 0), "right": (-1, 0, 0), "floor": (0, 1, 0), "ceiling": (0, -1, 0),
               "back": (0, 0, -1), "front": (0, 0, 1)}
        for k, m in sides.items():
            normal[m] = np.array(nrm[k], np.float32)
        # window glass -> exterior radiance
        wall = sides[s.window_wall]
        uu, vv = self._win_uv(p)
        glass = wall & self.window_glass(uu, vv)
        frame = wall & self.window_any(uu, vv) & ~glass
        col[glass] = self.env.radiance(d[glass])
        # albedo
        alb = np.zeros((n, 3), np.float32)
        for k in ("left", "right", "back", "front", "ceiling"):
            m = sides[k]
            if m.any():
                alb[m] = self.wall_albedo(k, p[m])
                labels[m] = LABELS["ceiling"] if k == "ceiling" else (LABELS["accent"] if k == s.accent_wall else LABELS["wall"])
        if sides["floor"].any():
            alb[sides["floor"]] = self.floor_albedo(p[sides["floor"]])
            labels[sides["floor"]] = LABELS["floor"]
        alb[frame] = 0.86
        labels[frame] = LABELS["frame"]
        labels[glass] = LABELS["window"]
        # door on the left wall
        if s.door:
            dm = sides["left"] & (p[:, 2] > 1.2) & (p[:, 2] < 2.1) & (p[:, 1] < 2.05)
            alb[dm] = 0.88
            fr = dm & ((p[:, 2] < 1.26) | (p[:, 2] > 2.04) | (p[:, 1] > 1.99))
            alb[fr] = 0.70
            labels[dm] = LABELS["frame"]
        # pictures
        if s.pictures:
            other = "left" if s.window_wall == "right" else "right"
            pm = sides[other] & (np.abs(p[:, 2] - 3.0) < 0.55) & (np.abs(p[:, 1] - 1.6) < 0.38)
            if pm.any():
                art = np.stack([fbm(p[pm, 2] * 6, p[pm, 1] * 6, 3, 51), fbm(p[pm, 2] * 5, p[pm, 1] * 5, 3, 52),
                                fbm(p[pm, 2] * 4, p[pm, 1] * 4, 3, 53)], 1)
                alb[pm] = 0.15 + 0.7 * art
                inner = (np.abs(p[pm, 2] - 3.0) < 0.50) & (np.abs(p[pm, 1] - 1.6) < 0.33)
                tmp = alb[pm]
                tmp[~inner] = 0.05
                alb[pm] = tmp
                labels[pm] = LABELS["object"]
        em = np.zeros((n, 3), np.float32)
        for bi, b in enumerate(s.boxes):
            m = (hit_kind == 1) & (hit_id == bi)
            if m.any():
                alb[m] = self.box_albedo(b, p[m])
                labels[m] = LABELS["object"]
        for si, sp in enumerate(s.spheres):
            m = (hit_kind == 2) & (hit_id == si)
            if m.any():
                a = np.array(sp.albedo, np.float32)
                if sp.texture == "leaf":
                    a = a[None] * (0.6 + 0.8 * fbm(p[m, 0] * 40, p[m, 1] * 40 + p[m, 2] * 20, 3, 61))[:, None]
                alb[m] = a
                labels[m] = LABELS["object"]
                if sp.emissive > 0:
                    em[m] = sp.emissive * self._light_col(sp.emissive_kelvin)
                    labels[m] = LABELS["lamp"]
        shade = ~glass
        if shade.any():
            E = self.irradiance(p[shade], normal[shade])
            col[shade] = alb[shade] * E / math.pi + em[shade]
        # TV screen: glossy black with faint reflection
        return col, labels


LABELS = {"none": 0, "wall": 1, "ceiling": 2, "floor": 3, "window": 4, "frame": 5, "object": 6, "lamp": 7,
          "accent": 8, "sky": 9}


# ---------------------------------------------------------------------------
# exterior scene (house facade) for sky replacement / twilight tests
# ---------------------------------------------------------------------------


def render_exterior(width=2400, height=1600, seed=5, pitch_deg=4.0, roll_deg=-0.8, supersample=2):
    """Simple two-storey house facade, lawn, trees and sky.  Returns radiance and labels."""
    rng = np.random.default_rng(seed)
    ss = supersample
    w, h = width * ss, height * ss
    cam = CameraSpec(width=w, height=h, hfov_deg=70, pos=(0, 1.6, 0), yaw_deg=0, pitch_deg=pitch_deg,
                     roll_deg=roll_deg, k1=0.0, supersample=1)
    d, f = camera_rays(cam, w, h, distort=False)
    o = np.array(cam.pos, np.float32)
    spec = SceneSpec(seed=seed, sky_lum=10.0, ground_lum=3.0)
    env = Environment(spec)
    n = d.shape[0]
    col = np.zeros((n, 3), np.float32)
    lab = np.zeros(n, np.uint8)
    # facade plane z = 14, x in [-7, 7], y in [0, 6.5] + gable roof
    zf = 14.0
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (zf - o[2]) / d[:, 2]
    p = o[None] + t[:, None] * d
    in_wall = (t > 0) & (np.abs(p[:, 0]) < 7) & (p[:, 1] >= 0) & (p[:, 1] < 6.0)
    roof_h = 6.0 + 2.8 * (1 - np.abs(p[:, 0]) / 7.5)
    in_roof = (t > 0) & (np.abs(p[:, 0]) < 7.5) & (p[:, 1] >= 6.0) & (p[:, 1] < roof_h)
    sun = np.array([0.45, 0.55, -0.70], np.float32)
    sun /= np.linalg.norm(sun)
    light = 3.0 * max(0.0, float(-sun[2])) + 0.9
    siding = 0.80 + 0.06 * (np.mod(p[:, 1], 0.2) < 0.02)
    wall_col = np.array([0.78, 0.74, 0.66], np.float32)[None] * siding[:, None] * light
    col[in_wall] = wall_col[in_wall]
    lab[in_wall] = LABELS["wall"]
    # windows: 2 floors x 4
    winm = np.zeros(n, bool)
    for fy in (1.0, 3.8):
        for fx in (-5.0, -2.5, 1.5, 4.0):
            m = in_wall & (np.abs(p[:, 0] - fx) < 0.6) & (p[:, 1] > fy) & (p[:, 1] < fy + 1.5)
            winm |= m
    glass_col = np.array([0.10, 0.12, 0.15], np.float32) * light + 0.15 * env.sky_avg * 0.1
    col[winm] = glass_col
    trim = np.zeros(n, bool)
    for fy in (1.0, 3.8):
        for fx in (-5.0, -2.5, 1.5, 4.0):
            m = in_wall & (np.abs(np.abs(p[:, 0] - fx) - 0.63) < 0.05) & (p[:, 1] > fy - 0.05) & (p[:, 1] < fy + 1.55)
            m |= in_wall & (np.abs(p[:, 0] - fx) < 0.68) & ((np.abs(p[:, 1] - fy + 0.03) < 0.05) | (np.abs(p[:, 1] - fy - 1.53) < 0.05))
            trim |= m
    col[trim] = 0.92 * light
    lab[winm] = LABELS["frame"]
    door = in_wall & (np.abs(p[:, 0] + 0.6) < 0.55) & (p[:, 1] < 2.2)
    col[door] = np.array([0.25, 0.12, 0.08], np.float32) * light
    col[in_roof] = np.array([0.18, 0.17, 0.18], np.float32)[None] * (0.8 + 0.4 * fbm(p[in_roof, 0] * 8, p[in_roof, 1] * 20, 2, 3))[:, None] * light
    lab[in_roof] = LABELS["object"]
    # ground plane
    with np.errstate(divide="ignore", invalid="ignore"):
        tg = -o[1] / d[:, 1]
    pg = o[None] + tg[:, None] * d
    gnd = (d[:, 1] < 0) & ~(in_wall | in_roof) & (tg > 0)
    gnd_n = fbm(pg[:, 0] * 2, pg[:, 2] * 2, 4, seed + 1)
    path = (np.abs(pg[:, 0] + 0.6) < 0.7) & (pg[:, 2] < zf)
    lawn_dry = np.array([0.30, 0.32, 0.12], np.float32)
    gcol = lawn_dry[None] * (0.6 + 0.6 * gnd_n[:, None]) * light
    gcol[path] = 0.55 * light
    col[gnd] = gcol[gnd]
    lab[gnd] = LABELS["floor"]
    # trees left and right (spheres of foliage)
    for cx, cy, cz, r in ((-10, 4.5, 16, 3.2), (10.5, 4.0, 17, 3.0), (-8.5, 2.0, 12, 1.4)):
        c = np.array([cx, cy, cz], np.float32)
        oc = o - c
        bq = d @ oc
        cq = oc @ oc - r * r
        disc = bq * bq - cq
        ts = -bq - np.sqrt(np.maximum(disc, 0))
        jitter = fbm(d[:, 0] * 160, d[:, 1] * 160, 3, seed + 7)
        ok = (disc > 0) & (ts > 0) & (jitter > 0.35 - 0.1 * (disc / r ** 2 > 0.3))
        leaf = np.array([0.10, 0.25, 0.07], np.float32)[None] * (0.5 + jitter[:, None]) * light
        col[ok] = leaf[ok]
        lab[ok] = LABELS["object"]
    sky = (lab == 0) & (d[:, 1] > -0.02)
    col[sky] = env.radiance(d[sky])
    lab[sky] = LABELS["sky"]
    img = col.reshape(h, w, 3)
    lab = lab.reshape(h, w)
    if ss > 1:
        img = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
        lab = lab[ss // 2::ss, ss // 2::ss]
    return img, lab


# ---------------------------------------------------------------------------
# optics + capture simulation
# ---------------------------------------------------------------------------


def apply_optics(img: np.ndarray, cam: CameraSpec) -> np.ndarray:
    h, w = img.shape[:2]
    out = img.copy()
    if cam.ca:
        cx, cy = w / 2, h / 2
        u, v = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        for ch, sc in ((0, 1 + cam.ca), (2, 1 - cam.ca)):
            mx = cx + (u - cx) / sc
            my = cy + (v - cy) / sc
            out[..., ch] = cv2.remap(img[..., ch], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    if cam.vignetting:
        u, v = np.meshgrid(np.linspace(-1, 1, w, dtype=np.float32), np.linspace(-1, 1, h, dtype=np.float32))
        r2 = (u * u * w * w + v * v * h * h) / (w * w + h * h)
        out *= (1 - cam.vignetting * r2 ** 1.0)[..., None]
    return out


def shake_homography(rng, w, h, handheld: bool):
    if handheld:
        tx, ty = rng.normal(0, 6, 2)
        ang = rng.normal(0, 0.25)
        sc = 1 + rng.normal(0, 0.002)
    else:
        tx, ty = rng.normal(0, 0.8, 2)
        ang = rng.normal(0, 0.02)
        sc = 1.0
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, sc)
    M[:, 2] += (tx, ty)
    return np.vstack([M, [0, 0, 1]]).astype(np.float64)


def capture(radiance: np.ndarray, exposure: float, rng, iso: int = 100, full_well: float = 6000.0,
            read_noise: float = 0.0012, crf: str = "camera", bits: int = 8) -> np.ndarray:
    """Expose linear radiance, add sensor noise, clip, apply tone curve, quantise."""
    gain = iso / 100.0
    x = radiance * exposure
    # shot noise (Gaussian approximation of Poisson) + read noise, then clipping
    var = np.maximum(x, 0) * gain / full_well + (read_noise * gain) ** 2
    x = x + rng.standard_normal(x.shape, dtype=np.float32) * np.sqrt(var).astype(np.float32)
    x = np.clip(x, 0.0, 1.0)
    if crf == "camera":
        y = camera_crf(x)
    elif crf == "srgb":
        y = srgb_oetf(x)
    else:  # linear
        y = x
    if bits == 8:
        return np.clip(np.round(y * 255), 0, 255).astype(np.uint8)
    return np.clip(np.round(y * 65535), 0, 65535).astype(np.uint16)


# ---------------------------------------------------------------------------
# series writer
# ---------------------------------------------------------------------------


@dataclass
class SeriesSpec:
    evs: tuple = (-4, -2, 0, 2, 4)
    base_shutter: float = 1 / 30
    fnumber: float = 8.0
    iso: int = 100
    focal_mm: float = 16.0
    handheld: bool = False
    ghost: bool = False
    fmt: str = "jpg"  # jpg | tif16
    exif: bool = True
    start: str = "2026-05-12T10:00:00"
    mid_exposure: float = 2.4  # exposure multiplier of the EV 0 frame
    focal35: float = 20.0  # 35 mm equivalent focal length written to EXIF


def _rational(x: float):
    from fractions import Fraction
    fr = Fraction(x).limit_denominator(100000)
    return (fr.numerator, fr.denominator)


def write_exif_jpeg(path: str, meta: dict):
    import piexif
    exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}
    exif["0th"][piexif.ImageIFD.Make] = b"SynthCam"
    exif["0th"][piexif.ImageIFD.Model] = b"SC-1 Mark II"
    exif["0th"][piexif.ImageIFD.Orientation] = 1
    exif["0th"][piexif.ImageIFD.DateTime] = meta["datetime"].encode()
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = meta["datetime"].encode()
    exif["Exif"][piexif.ExifIFD.SubSecTimeOriginal] = meta["subsec"].encode()
    exif["Exif"][piexif.ExifIFD.ExposureTime] = _rational(meta["exposure_time"])
    exif["Exif"][piexif.ExifIFD.FNumber] = _rational(meta["fnumber"])
    exif["Exif"][piexif.ExifIFD.ISOSpeedRatings] = meta["iso"]
    exif["Exif"][piexif.ExifIFD.ExposureBiasValue] = (int(round(meta["ev"] * 100)), 100) if meta["ev"] >= 0 else (int(round(meta["ev"] * 100)), 100)
    exif["Exif"][piexif.ExifIFD.FocalLength] = _rational(meta["focal"])
    exif["Exif"][piexif.ExifIFD.LensModel] = b"Synth 16-35mm f/4"
    exif["Exif"][piexif.ExifIFD.FocalLengthIn35mmFilm] = int(round(meta.get("focal35", meta["focal"])))
    piexif.insert(piexif.dump(exif), path)


def write_tiff16(path: str, img16: np.ndarray, meta: dict | None):
    import tifffile
    extratags = []
    if meta:
        n, d = _rational(meta["exposure_time"])
        fn, fd = _rational(meta["fnumber"])
        fl, fld = _rational(meta["focal"])
        extratags = [
            (271, "s", 0, "SynthCam", True),
            (272, "s", 0, "SC-1 Mark II", True),
            (306, "s", 0, meta["datetime"], True),
            (33434, "2I", 1, (n, d), True),
            (33437, "2I", 1, (fn, fd), True),
            (34855, "H", 1, meta["iso"], True),
            (37386, "2I", 1, (fl, fld), True),
            (36867, "s", 0, meta["datetime"], True),
        ]
    tifffile.imwrite(path, img16, photometric="rgb", extratags=extratags, compression="zlib")


def write_series(radiance: np.ndarray, out_dir: str, prefix: str, series: SeriesSpec, rng,
                 ghost_fn=None, start_index: int = 0):
    """Write one bracket series; returns per-frame metadata (incl. GT homographies)."""
    os.makedirs(out_dir, exist_ok=True)
    h, w = radiance.shape[:2]
    t0 = datetime.fromisoformat(series.start)
    frames = []
    t = t0
    for i, ev in enumerate(series.evs):
        Hm = np.eye(3) if i == len(series.evs) // 2 else shake_homography(rng, w, h, series.handheld)
        rad = radiance
        if ghost_fn is not None:
            rad = ghost_fn(rad.copy(), i)
        if not np.allclose(Hm, np.eye(3)):
            rad = cv2.warpPerspective(rad, Hm, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        expo = series.mid_exposure * 2.0 ** ev
        shutter = series.base_shutter * 2.0 ** ev
        meta = {"datetime": t.strftime("%Y:%m:%d %H:%M:%S"), "subsec": f"{int(t.microsecond / 1e4):02d}",
                "exposure_time": shutter, "fnumber": series.fnumber, "iso": series.iso, "ev": ev,
                "focal": series.focal_mm, "focal35": series.focal35}
        name = f"{prefix}_{start_index + i:04d}"
        if series.fmt == "jpg":
            img = capture(rad, expo, rng, iso=series.iso, crf="camera", bits=8)
            path = os.path.join(out_dir, name + ".jpg")
            cv2.imwrite(path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 93])
            if series.exif:
                write_exif_jpeg(path, meta)
        else:
            img = capture(rad, expo, rng, iso=series.iso, crf="linear", bits=16)
            path = os.path.join(out_dir, name + ".tif")
            write_tiff16(path, img, meta if series.exif else None)
        frames.append({"file": os.path.basename(path), "ev": ev, "exposure_time": shutter,
                       "homography": Hm.tolist(), "datetime": meta["datetime"]})
        t = t + timedelta(seconds=shutter + 0.35)
    return frames


def moving_object(center_xs, cy, rx, ry, color=(0.05, 0.07, 0.12)):
    def fn(rad, i):
        h, w = rad.shape[:2]
        cx = center_xs[i % len(center_xs)]
        mask = np.zeros((h, w), np.float32)
        cv2.ellipse(mask, (int(cx * w), int(cy * h)), (int(rx * w), int(ry * h)), 0, 0, 360, 1.0, -1)
        cv2.circle(mask, (int(cx * w), int((cy - ry * 1.25) * h)), int(rx * w * 0.6), 1.0, -1)
        mask = cv2.GaussianBlur(mask, (0, 0), 1.5)[..., None]
        return rad * (1 - mask) + np.array(color, np.float32)[None, None] * mask
    return fn


def tonemap_reference(lin: np.ndarray, labels: np.ndarray, interior_white: float, exterior_mid: float) -> np.ndarray:
    """'Ideal edit' used as synthetic ground truth: neutral lights, straight camera,
    interior exposed so walls are bright, exterior exposed separately and blended
    through the exact window mask.  Output is display sRGB float in [0,1]."""
    win = (labels == LABELS["window"]).astype(np.float32)
    win = cv2.GaussianBlur(win, (0, 0), 1.2)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    wall = np.isin(labels, [LABELS["wall"], LABELS["ceiling"]])
    k_in = interior_white / max(np.percentile(lum[wall], 90), 1e-6) if wall.any() else 1.0
    ext = labels == LABELS["window"]
    k_out = exterior_mid / max(np.median(lum[ext]), 1e-6) if ext.any() else k_in
    a = lin * k_in
    b = lin * k_out

    def curve(x):
        x = np.maximum(x, 0)
        y = x * (1 + x / 4.0) / (1 + x)  # Reinhard with white point 2
        return srgb_oetf(np.clip(y, 0, 1))
    out = curve(a) * (1 - win[..., None]) + curve(b) * win[..., None]
    return np.clip(out, 0, 1)


SCENES = {
    "living_room": dict(scene=default_living_room, series=SeriesSpec(evs=(-4, -2, 0, 2, 4)),
                        cam=CameraSpec()),
    "bedroom": dict(scene=default_bedroom, series=SeriesSpec(evs=(-2, 0, 2), handheld=True, ghost=True, fmt="tif16",
                                                             start="2026-05-12T10:05:00", mid_exposure=2.6),
                    cam=CameraSpec(yaw_deg=10, pitch_deg=5.0, roll_deg=-0.8, k1=0.04, hfov_deg=80)),
    "kitchen": dict(scene=default_kitchen, series=SeriesSpec(evs=(-3, -2, -1, 0, 1, 2, 3), start="2026-05-12T10:09:00",
                                                             mid_exposure=2.0),
                    cam=CameraSpec(yaw_deg=-4, pitch_deg=-9.0, roll_deg=0.5, k1=0.08, hfov_deg=88)),
}


def generate_dataset(out_root: str, width: int = 2400, height: int = 1600, scenes=None, seed: int = 7,
                     extras: bool = True, supersample: int = 2) -> dict:
    """Generate synthetic bracket series + ground truth into out_root.

    out_root/input/  -> all frames of all series in one folder (to test grouping)
    out_root/gt/<scene>/ -> radiance, labels, ideal reference, params
    """
    rng = np.random.default_rng(seed)
    inp = os.path.join(out_root, "input")
    os.makedirs(inp, exist_ok=True)
    manifest = {"series": [], "extras": {}}
    scenes = scenes or list(SCENES)
    idx = 0
    for name in scenes:
        cfg = SCENES[name]
        spec = cfg["scene"]()
        cam = CameraSpec(**{**asdict(cfg["cam"]), "width": width, "height": height, "supersample": supersample})
        series = cfg["series"]
        rad, lab = Renderer(spec).render(cam)
        rad = apply_optics(rad, cam)
        # ground truth: neutral lights, ideal (level) camera without lens defects
        cam_gt = CameraSpec(**{**asdict(cam), "pitch_deg": 0.0, "roll_deg": 0.0, "k1": 0.0, "ca": 0.0,
                               "vignetting": 0.0})
        rad_gt, lab_gt = Renderer(spec, neutral_lights=True).render(cam_gt, distort=False)
        rad_tilt, lab_tilt = Renderer(spec, neutral_lights=False).render(
            CameraSpec(**{**asdict(cam), "k1": 0.0, "ca": 0.0, "vignetting": 0.0}), distort=False)
        ghost = moving_object([0.30, 0.38, 0.46, 0.54, 0.62], 0.62, 0.035, 0.10) if series.ghost else None
        frames = write_series(rad, inp, f"IMG", series, rng, ghost_fn=ghost, start_index=idx)
        idx += len(series.evs)
        gdir = os.path.join(out_root, "gt", name)
        os.makedirs(gdir, exist_ok=True)
        import tifffile
        tifffile.imwrite(os.path.join(gdir, "radiance_capture.tif"), rad.astype(np.float32), compression="zlib")
        tifffile.imwrite(os.path.join(gdir, "radiance_ideal.tif"), rad_gt.astype(np.float32), compression="zlib")
        cv2.imwrite(os.path.join(gdir, "labels_capture.png"), lab)
        cv2.imwrite(os.path.join(gdir, "labels_ideal.png"), lab_gt)
        cv2.imwrite(os.path.join(gdir, "labels_tilted_undistorted.png"), lab_tilt)
        ref = tonemap_reference(rad_gt, lab_gt, interior_white=0.92, exterior_mid=0.42)
        cv2.imwrite(os.path.join(gdir, "reference_ideal.png"),
                    cv2.cvtColor((ref * 255 + 0.5).astype(np.uint8), cv2.COLOR_RGB2BGR))
        params = {"scene": asdict(spec), "camera": asdict(cam), "series": asdict(series), "frames": frames}
        with open(os.path.join(gdir, "params.json"), "w") as fh:
            json.dump(params, fh, indent=1, default=str)
        manifest["series"].append({"name": name, "files": [f["file"] for f in frames]})
    if extras:
        # exterior: 3 brackets for sky / twilight modules
        ext, ext_lab = render_exterior(width, height, supersample=supersample)
        ser = SeriesSpec(evs=(-2, 0, 2), start="2026-05-12T10:20:00", mid_exposure=0.25, base_shutter=1 / 250)
        frames = write_series(ext, inp, "IMG", ser, rng, start_index=idx)
        idx += 3
        gdir = os.path.join(out_root, "gt", "exterior")
        os.makedirs(gdir, exist_ok=True)
        cv2.imwrite(os.path.join(gdir, "labels_capture.png"), ext_lab)
        manifest["series"].append({"name": "exterior", "files": [f["file"] for f in frames]})
        # single exposure (no bracketing) of the living room, slightly underexposed
        spec = default_living_room(seed=11)
        cam = CameraSpec(width=width, height=height, supersample=supersample, yaw_deg=8, pitch_deg=-3, roll_deg=0.4)
        rad, _ = Renderer(spec).render(cam)
        rad = apply_optics(rad, cam)
        ser = SeriesSpec(evs=(0,), start="2026-05-12T10:30:00", mid_exposure=1.5)
        frames = write_series(rad, inp, "IMG", ser, rng, start_index=idx)
        idx += 1
        manifest["series"].append({"name": "single", "files": [f["file"] for f in frames]})
        # incomplete series (2 of 3 frames) without EXIF
        ser = SeriesSpec(evs=(-2, 0), start="2026-05-12T10:40:00", exif=False)
        frames = write_series(rad, inp, "NOEXIF", ser, rng, start_index=0)
        manifest["extras"]["noexif_incomplete"] = [f["file"] for f in frames]
        # corrupted file
        bad = os.path.join(inp, "IMG_9999.jpg")
        with open(os.path.join(inp, frames[0]["file"]), "rb") as fh:
            data = fh.read()
        with open(bad, "wb") as fh:
            fh.write(data[: len(data) // 7])
        manifest["extras"]["corrupt"] = ["IMG_9999.jpg"]
    with open(os.path.join(out_root, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest

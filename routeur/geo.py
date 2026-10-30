"""Géographie : géodésie, masque terre + zones interdites, contrôle de navigabilité des segments.

Le masque est un ensemble de tuiles raster : une tuile grossière sur toute la zone et des tuiles fines
(départ, Guadeloupe) consultées en priorité. Une cellule vraie = non navigable (terre, marge de
sécurité, zone interdite). Source des côtes : GSHHG 2.3.7 pleine résolution (Wessel & Smith).
"""
from __future__ import annotations

import json
import logging
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

log = logging.getLogger("routeur.geo")

EARTH_NM = 3440.065


# --- géodésie (sphère) ------------------------------------------------------------------------

def haversine_nm(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_NM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Cap initial orthodromique (degrés vrais)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(y, x)) + 360) % 360


def rhumb_destination(lat, lon, heading_deg, dist_nm):
    """Point atteint en suivant un cap constant (loxodromie), comme un bateau VR entre deux ordres."""
    lat = np.asarray(lat, float)
    h = np.radians(heading_deg)
    d = np.asarray(dist_nm, float) / EARTH_NM
    p1 = np.radians(lat)
    dp = d * np.cos(h)
    p2 = np.clip(p1 + dp, -np.radians(89.9), np.radians(89.9))
    dpsi = np.log(np.tan(np.pi / 4 + p2 / 2) / np.tan(np.pi / 4 + p1 / 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        q = np.where(np.abs(dpsi) > 1e-12, (p2 - p1) / dpsi, np.cos(p1))
    dl = d * np.sin(h) / q
    return np.degrees(p2), np.asarray(lon, float) + np.degrees(dl)


def rhumb_bearing_distance(lat1, lon1, lat2, lon2):
    """Cap loxodromique (degrés) et distance (nm) entre deux points."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    dpsi = np.log(np.tan(np.pi / 4 + p2 / 2) / np.tan(np.pi / 4 + p1 / 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        q = np.where(np.abs(dpsi) > 1e-12, (p2 - p1) / dpsi, np.cos(p1))
    brg = (np.degrees(np.arctan2(dl, dpsi)) + 360) % 360
    dist = np.sqrt((p2 - p1) ** 2 + (q * dl) ** 2) * EARTH_NM
    return brg, dist


# --- lecture GSHHG ---------------------------------------------------------------------------

def read_gshhs(zip_path: Path, member: str, bbox: dict, levels=(1,)):
    """Polygones GSHHS (format binaire v2) qui recoupent la zone, en (lon, lat) degrés, lon continue."""
    polys = []
    with zipfile.ZipFile(zip_path) as z:
        buf = z.read(member)
    off = 0
    n_total = len(buf)
    while off + 44 <= n_total:
        pid, n, flag, west, east, south, north, area, area_full, container, ancestor = struct.unpack_from(">11i", buf, off)
        off += 44
        level = flag & 255
        pts_bytes = n * 8
        if level in levels:
            w, e, s, nn = west * 1e-6, east * 1e-6, south * 1e-6, north * 1e-6
            near = any(w + k <= bbox["lon_max"] + 1 and e + k >= bbox["lon_min"] - 1 for k in (-360, 0, 360))
            if s <= bbox["lat_max"] and nn >= bbox["lat_min"] and near:
                pts = np.frombuffer(buf, ">i4", count=2 * n, offset=off).reshape(n, 2) * 1e-6
                lon = np.degrees(np.unwrap(np.radians(pts[:, 0])))
                # Longitudes rendues continues, puis décalées de ±360° pour recouper la zone.
                for k in (-360.0, 0.0, 360.0):
                    if lon.min() + k <= bbox["lon_max"] and lon.max() + k >= bbox["lon_min"]:
                        polys.append(np.column_stack([lon + k, pts[:, 1]]))
        off += pts_bytes
    return polys


def read_forbidden(geojson_path: Path) -> list[tuple[str, np.ndarray]]:
    d = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    out = []
    for f in d["features"]:
        g, p = f.get("geometry"), f.get("properties", {})
        if g and g["type"] == "Polygon" and p.get("kind") == "forbidden":
            out.append((p.get("name", "?"), np.array(g["coordinates"][0], float)))
    return out


# --- masque ----------------------------------------------------------------------------------

@dataclass
class Tile:
    lat0: float  # bord sud
    lon0: float  # bord ouest
    res: float
    mask: np.ndarray  # bool (nlat, nlon), ligne 0 = sud

    @property
    def lat1(self):
        return self.lat0 + self.mask.shape[0] * self.res

    @property
    def lon1(self):
        return self.lon0 + self.mask.shape[1] * self.res

    def contains(self, lat, lon):
        return (lat >= self.lat0) & (lat < self.lat1) & (lon >= self.lon0) & (lon < self.lon1)

    def lookup(self, lat, lon):
        j = np.clip(((lat - self.lat0) / self.res).astype(int), 0, self.mask.shape[0] - 1)
        i = np.clip(((lon - self.lon0) / self.res).astype(int), 0, self.mask.shape[1] - 1)
        return self.mask[j, i]


def rasterize(polys, lat0, lon0, lat1, lon1, res) -> np.ndarray:
    w = int(round((lon1 - lon0) / res))
    h = int(round((lat1 - lat0) / res))
    img = Image.new("1", (w, h), 0)
    draw = ImageDraw.Draw(img)
    for p in polys:
        if p[:, 0].max() < lon0 or p[:, 0].min() > lon1 or p[:, 1].max() < lat0 or p[:, 1].min() > lat1:
            continue
        xy = np.column_stack([(p[:, 0] - lon0) / res, (lat1 - p[:, 1]) / res])
        draw.polygon([tuple(v) for v in xy], fill=1, outline=1)
    return np.array(img, dtype=bool)[::-1]  # ligne 0 = sud


def dilate(mask: np.ndarray, lat0: float, res: float, margin_nm: float) -> np.ndarray:
    """Marge de sécurité : dilatation elliptique (la maille en longitude rétrécit avec la latitude)."""
    if margin_nm <= 0:
        return mask
    out = np.empty_like(mask)
    band = max(1, int(5.0 / res))
    for j0 in range(0, mask.shape[0], band):
        j1 = min(mask.shape[0], j0 + band)
        lat_mid = lat0 + (j0 + j1) / 2 * res
        ry = margin_nm / (res * 60.0)
        rx = margin_nm / (res * 60.0 * np.cos(np.radians(lat_mid)))
        ny, nx = int(np.ceil(ry)), int(np.ceil(rx))
        yy, xx = np.mgrid[-ny:ny + 1, -nx:nx + 1]
        st = (yy / max(ry, 1e-9)) ** 2 + (xx / max(rx, 1e-9)) ** 2 <= 1.0
        lo, hi = max(0, j0 - ny), min(mask.shape[0], j1 + ny)
        out[j0:j1] = ndimage.binary_dilation(mask[lo:hi], structure=st)[j0 - lo: j0 - lo + (j1 - j0)]
    return out


class LandMask:
    def __init__(self, tiles: list[Tile], forbidden_names: list[str] | None = None):
        self.tiles = tiles  # la dernière est la tuile grossière, les autres sont prioritaires
        self.forbidden_names = forbidden_names or []

    @classmethod
    def build(cls, gshhg_zip: Path, forbidden_geojson: Path | None, bbox: dict, res: float,
              margin_nm: float, fine_tiles: list[dict], fine_res: float) -> "LandMask":
        coarse_polys = read_gshhs(gshhg_zip, "gshhs_f.b", bbox)
        forbidden = read_forbidden(forbidden_geojson) if forbidden_geojson else []
        zone_polys = [p for _, p in forbidden]
        log.info("%d polygones de côte, %d zones interdites", len(coarse_polys), len(zone_polys))
        tiles = []
        for ft in fine_tiles:
            land = rasterize(coarse_polys, ft["lat_min"], ft["lon_min"], ft["lat_max"], ft["lon_max"], fine_res)
            m = dilate(land, ft["lat_min"], fine_res, ft.get("margin_nm", margin_nm))
            m |= rasterize(zone_polys, ft["lat_min"], ft["lon_min"], ft["lat_max"], ft["lon_max"], fine_res)
            tiles.append(Tile(ft["lat_min"], ft["lon_min"], fine_res, m))
        land = rasterize(coarse_polys, bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"], res)
        m = dilate(land, bbox["lat_min"], res, margin_nm)
        m |= rasterize(zone_polys, bbox["lat_min"], bbox["lon_min"], bbox["lat_max"], bbox["lon_max"], res)
        tiles.append(Tile(bbox["lat_min"], bbox["lon_min"], res, m))
        return cls(tiles, [n for n, _ in forbidden])

    @staticmethod
    def split(path: Path, size: int = 35_000) -> list[Path]:
        """Découpe mask.npz en morceaux (la connexion coupe les envois de plus de ~40 Ko)."""
        path = Path(path)
        for old in path.parent.glob(path.name + ".part*"):
            old.unlink()
        data = path.read_bytes()
        parts = []
        for k in range(0, len(data), size):
            q = path.with_name(f"{path.name}.part{k // size}")
            q.write_bytes(data[k:k + size])
            parts.append(q)
        return parts

    def save(self, path: Path) -> None:
        arrays = {}
        for k, t in enumerate(self.tiles):
            arrays[f"t{k}_meta"] = np.array([t.lat0, t.lon0, t.res, *t.mask.shape])
            arrays[f"t{k}_bits"] = np.packbits(t.mask)
        np.savez_compressed(path, n=len(self.tiles), names=np.array(self.forbidden_names), **arrays)

    @classmethod
    def load(cls, path: Path) -> "LandMask":
        path = Path(path)
        if not path.exists():
            # Version publiée : le masque est découpé en morceaux (mask.npz.part0, part1…), recollés ici.
            parts = sorted(path.parent.glob(path.name + ".part*"), key=lambda q: int(q.suffix[5:]))
            if not parts:
                raise FileNotFoundError(path)
            import io
            path = io.BytesIO(b"".join(q.read_bytes() for q in parts))
        d = np.load(path)
        tiles = []
        for k in range(int(d["n"])):
            lat0, lon0, res, h, w = d[f"t{k}_meta"]
            bits = np.unpackbits(d[f"t{k}_bits"])[: int(h) * int(w)].astype(bool)
            tiles.append(Tile(float(lat0), float(lon0), float(res), bits.reshape(int(h), int(w))))
        return cls(tiles, list(d["names"]))

    @classmethod
    def empty(cls) -> "LandMask":
        return cls([Tile(-90, -180, 1.0, np.zeros((180, 360), bool))])

    def blocked(self, lat, lon) -> np.ndarray:
        lat = np.asarray(lat, float)
        lon = np.asarray(lon, float)
        out = np.zeros(lat.shape, bool)
        done = np.zeros(lat.shape, bool)
        for t in self.tiles:
            inside = t.contains(lat, lon) & ~done
            if inside.any():
                out[inside] = t.lookup(lat[inside], lon[inside])
                done |= inside
        out[~done] = True  # hors de toute tuile : hors zone météo, interdit
        return out

    def segments_clear(self, lat1, lon1, lat2, lon2, max_samples: int = 2000) -> np.ndarray:
        """Vrai si le segment (interpolé en lat/lon) ne touche aucune cellule interdite."""
        lat1, lon1, lat2, lon2 = (np.asarray(a, float) for a in (lat1, lon1, lat2, lon2))
        fine = np.zeros(lat1.shape, bool)
        for t in self.tiles[:-1]:
            fine |= t.contains(lat1, lon1) | t.contains(lat2, lon2)
        spacing = np.where(fine, self.tiles[0].res if len(self.tiles) > 1 else self.tiles[-1].res,
                           self.tiles[-1].res) * 0.5
        span = np.maximum(np.abs(lat2 - lat1), np.abs(lon2 - lon1))
        n = np.clip(np.ceil(span / spacing).astype(int) + 1, 2, max_samples)
        seg = np.repeat(np.arange(lat1.size), n)
        start = np.repeat(np.cumsum(n) - n, n)
        frac = (np.arange(seg.size) - start) / np.repeat(n - 1, n)
        la = lat1.ravel()[seg] + (lat2.ravel()[seg] - lat1.ravel()[seg]) * frac
        lo = lon1.ravel()[seg] + (lon2.ravel()[seg] - lon1.ravel()[seg]) * frac
        hit = self.blocked(la, lo)
        bad = np.zeros(lat1.size, bool)
        np.logical_or.at(bad, seg, hit)
        return ~bad.reshape(lat1.shape)


def clip_polygon(poly: np.ndarray, bbox: dict) -> np.ndarray:
    """Découpe Sutherland-Hodgman d'un polygone (lon, lat) par un rectangle."""
    edges = [(0, bbox["lon_min"], True), (0, bbox["lon_max"], False), (1, bbox["lat_min"], True), (1, bbox["lat_max"], False)]
    out = poly
    for axis, val, keep_greater in edges:
        if len(out) == 0:
            break
        inside = out[:, axis] >= val if keep_greater else out[:, axis] <= val
        res = []
        for k in range(len(out)):
            cur, prev = out[k], out[k - 1]
            ic, ip = inside[k], inside[k - 1]
            if ic != ip:
                f = (val - prev[axis]) / (cur[axis] - prev[axis])
                res.append(prev + (cur - prev) * f)
            if ic:
                res.append(cur)
        out = np.array(res) if res else np.empty((0, 2))
    return out


def coastline_geojson(gshhg_zip: Path, bbox: dict, member: str = "gshhs_l.b", clip: bool = False,
                      decimals: int = 3) -> dict:
    """Contours de côte pour l'affichage carte (découpés au rectangle si clip=True)."""
    feats = []
    for p in read_gshhs(gshhg_zip, member, bbox):
        if clip:
            p = clip_polygon(p, bbox)
            if len(p) < 3:
                continue
        coords = np.round(p, decimals).tolist()
        feats.append({"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [coords]}})
    return {"type": "FeatureCollection", "features": feats}

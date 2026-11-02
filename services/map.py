"""
Static market map for the PDF: CARTO basemap tiles (fetched at render time,
cached on disk) with the dealership pin, radius ring and shopper bubbles.
Falls back to a clean tile-less plot if the tile host is unreachable.
"""
from __future__ import annotations

import io
import logging
import math
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle
from PIL import Image

import config

log = logging.getLogger(__name__)
TILE_URL = "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
TILE_CACHE = Path(os.getenv("TILE_CACHE", "/tmp/m1-tiles"))
B = config.BRAND


# ---- Web-mercator helpers --------------------------------------------------
def _latlon_to_tile(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _fetch_tile(z, x, y) -> Image.Image | None:
    TILE_CACHE.mkdir(parents=True, exist_ok=True)
    p = TILE_CACHE / f"{z}_{x}_{y}.png"
    try:
        if not p.exists():
            req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y),
                                         headers={"User-Agent": "M1Data-InMarket/1.0 (reports@m1-data.com)"})
            with urllib.request.urlopen(req, timeout=6) as r:
                p.write_bytes(r.read())
        return Image.open(p).convert("RGB")
    except Exception as e:  # noqa: BLE001
        log.warning("tile %s/%s/%s failed: %s", z, x, y, e)
        return None


def _google_static(center, radius_mi):
    """Google Maps Static API basemap. Returns (image, extent in tile units, zoom) or None."""
    key = config.GOOGLE_MAPS_STATIC_KEY
    if not key:
        return None
    w, h, scale = 640, 512, 2
    r_m = radius_mi * 1609.34
    for z in range(16, 6, -1):
        m_per_px = 40075016.686 * math.cos(math.radians(center["lat"])) / (256 * 2 ** z)
        if r_m / m_per_px * 1.3 <= min(w, h) / 2:
            break
    url = ("https://maps.googleapis.com/maps/api/staticmap?"
           f"center={center['lat']},{center['lon']}&zoom={z}&size={w}x{h}&scale={scale}&maptype=roadmap"
           "&style=feature:poi|visibility:off&style=feature:transit|visibility:off&format=png"
           f"&key={key}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "M1Data-InMarket/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            im = Image.open(io.BytesIO(r.read())).convert("RGB")
    except Exception as e:  # noqa: BLE001
        log.warning("Google static map failed (%s); falling back to CARTO tiles", e)
        return None
    cx, cy = _latlon_to_tile(center["lat"], center["lon"], z)
    half_w, half_h = w / 2 / 256, h / 2 / 256     # tile units (scale only changes pixel density)
    return im, (cx - half_w, cy - half_h, cx + half_w, cy + half_h), z


def _basemap(center, radius_mi, px=1200):
    """Return (image, extent_tiles=(x0,y0,x1,y1 in tile units), zoom) or None."""
    g = _google_static(center, radius_mi)
    if g:
        return g
    half_deg_lat = radius_mi / 69.0 * 1.25
    # pick zoom so the diameter spans ~ px/256 tiles
    for z in range(14, 7, -1):
        cx, cy = _latlon_to_tile(center["lat"], center["lon"], z)
        _, cy_top = _latlon_to_tile(center["lat"] + half_deg_lat, center["lon"], z)
        span = (cy - cy_top) * 2
        if span * 256 <= px:
            break
    cx, cy = _latlon_to_tile(center["lat"], center["lon"], z)
    half = max(span / 2, 1.0)
    x0, x1 = math.floor(cx - half), math.ceil(cx + half)
    y0, y1 = math.floor(cy - half), math.ceil(cy + half)
    tiles = [(z, x, y) for x in range(x0, x1) for y in range(y0, y1)]
    if len(tiles) > 64:
        return None
    with ThreadPoolExecutor(8) as ex:
        imgs = list(ex.map(lambda t: _fetch_tile(*t), tiles))
    if any(i is None for i in imgs):
        return None
    mosaic = Image.new("RGB", ((x1 - x0) * 256, (y1 - y0) * 256), "#EEF0F5")
    for (z_, x, y), im in zip(tiles, imgs):
        mosaic.paste(im, ((x - x0) * 256, (y - y0) * 256))
    return mosaic, (x0, y0, x1, y1), z


# ---- Public ---------------------------------------------------------------
def market_map_png(result: dict, dealership: str, width_px=1600) -> bytes:
    c = result["center"]
    radius_mi = result["radius_mi"]
    pts = [p for p in result["map_points"] if p.get("lat") is not None]
    bm = _basemap(c, radius_mi)
    z = bm[2] if bm else 12
    to_xy = lambda lat, lon: _latlon_to_tile(lat, lon, z)  # noqa: E731  (web-mercator keeps the ring round)
    m_per_tile = 40075016.686 * math.cos(math.radians(c["lat"])) / (2 ** z)
    r_tiles = radius_mi * 1609.34 / m_per_tile
    cx, cy = to_xy(c["lat"], c["lon"])

    fig, ax = plt.subplots(figsize=(8, 6.4), dpi=width_px / 8)
    if bm:
        mosaic, (x0, y0, x1, y1), _ = bm
        ax.imshow(mosaic, extent=(x0, x1, y1, y0), interpolation="bilinear", alpha=0.95)
    else:
        ax.set_facecolor("#F4F5FA")
    ax.set_xlim(cx - r_tiles * 1.3, cx + r_tiles * 1.3)
    ax.set_ylim(cy + r_tiles * 1.3 * 0.8, cy - r_tiles * 1.3 * 0.8)
    ax.set_aspect("equal")

    # bubbles
    if pts:
        mx = max(p["shoppers"] for p in pts) or 1
        xs, ys = zip(*[to_xy(p["lat"], p["lon"]) for p in pts])
        sizes = [40 + 900 * (p["shoppers"] / mx) for p in pts]
        ax.scatter(xs, ys, s=sizes, c=B["blue"], alpha=0.35, edgecolors=B["blue"], linewidths=1.2, zorder=3)
        from matplotlib import patheffects as pe
        for p, x, y in sorted(zip(pts, xs, ys), key=lambda t: -t[0]["shoppers"])[:8]:
            ax.annotate(f"{p['zip']}\n{p['shoppers']:,}", (x, y), ha="center", va="center", fontsize=6.5,
                        color=B["navy"], fontweight="bold", zorder=5,
                        path_effects=[pe.withStroke(linewidth=2.2, foreground="white")])

    # radius ring + dealership pin
    ax.add_patch(Circle((cx, cy), r_tiles, fill=False, ls=(0, (6, 4)), lw=1.6, ec=B["navy"], zorder=4))
    ax.scatter([cx], [cy], s=220, marker="*", c=B["orange"], edgecolors=B["navy"], linewidths=1.2, zorder=6)
    ax.annotate(dealership, (cx, cy), xytext=(0, 12), textcoords="offset points", ha="center", fontsize=8,
                fontweight="bold", color=B["navy"], zorder=6,
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=B["navy"], lw=0.8, alpha=0.95))
    credit = "Map data © Google" if (bm and config.GOOGLE_MAPS_STATIC_KEY) else "© OpenStreetMap, © CARTO"
    ax.text(0.01, 0.01, f"{int(radius_mi)}-mile radius  ·  bubble size = in-market shoppers  ·  {credit}",
            transform=ax.transAxes, fontsize=6, color=B["gray"], ha="left", va="bottom",
            bbox=dict(fc="white", ec="none", alpha=0.8, pad=2))
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_edgecolor("#E5E7EB")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    return buf.getvalue()

"""The texture maps of the Sand Stone finishes, made by code: seamless (every map tiles), seeded (the same maps every
time), at any resolution (4096 px by default).

The finishes are Technogym's Sand Stone signature finishes (the Sand Stone Collection catalogue, "Signature finishes
and materials"), calibrated to the catalogue's swatches:
  speckled_stone   casings containing mica powder: a warm off-white with fine dark specks and sparkling mica flakes
  warm_titanium    the metallic frames: a fine metallic-paint flake (bump and roughness only; the colour is the
                   material's)
  clay_leather     the soft-touch upholstery: a pebble grain with fine creases
  stipple          a fine moulded-plastic / rubber texture for the soft-touch parts, rubber and grips
  belt             a running belt: a fine woven rubber surface
  brushed          brushed steel: fine streaks in one direction
Each finish is a few files: <finish>_albedo.png (sRGB colour, 8 bit), <finish>_rough.png (roughness, linear, 8 bit),
<finish>_bump.png (height, linear, 16 bit).
"""
from pathlib import Path

import numpy as np

SIZE = 4096
SEED = 20261002

# the catalogue swatches, sRGB (Sand_Stone_Collection_catalogue.pdf, page 23)
SPECKLED_STONE = (200, 196, 184)
CLAY = (120, 103, 92)


# --------------------------------------------------------------------------- periodic building blocks
def _freq(n):
    f = np.fft.fftfreq(n) * n
    fx, fy = np.meshgrid(f, f)
    return fx, fy, np.hypot(fx, fy)


def norm01(a):
    lo, hi = np.percentile(a, [0.5, 99.5])
    return np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1)


def noise(n, rng, lo, hi, beta=1.0, aniso=1.0):
    """Band-limited fractal noise between the frequencies lo and hi (cycles per tile); tiles seamlessly.
    aniso > 1 stretches it along x (streaks)."""
    fx, fy, _ = _freq(n)
    r = np.hypot(fx * aniso, fy)
    amp = np.where((r >= lo) & (r <= hi), 1.0 / np.maximum(r, 1) ** beta, 0.0)
    spec = np.fft.fft2(rng.standard_normal((n, n))) * amp
    return norm01(np.real(np.fft.ifft2(spec)))


def splat(n, rng, count, radius, amp=(0.5, 1.0)):
    """count soft round dots per tile, radius a fraction of the tile, at random places, wrapped around the edges;
    0..1. Counts and sizes are per tile, so the look does not depend on the resolution."""
    radius_px = max(radius * n, 0.35)
    img = np.zeros((n, n))
    ix = rng.integers(0, n, count)
    iy = rng.integers(0, n, count)
    np.add.at(img, (iy, ix), rng.uniform(*amp, count))
    fx, fy, r = _freq(n)
    # the Fourier transform of a soft disc of radius radius_px (a Gaussian of that size)
    sigma = radius_px / 2.0
    kernel = np.exp(-2 * (np.pi * r / n * sigma) ** 2)
    out = np.real(np.fft.ifft2(np.fft.fft2(img) * kernel))
    return np.clip(out / max(out.max(), 1e-9), 0, 1)


def blur(a, sigma):
    """A periodic Gaussian blur; sigma a fraction of the tile."""
    _, _, r = _freq(a.shape[0])
    return np.real(np.fft.ifft2(np.fft.fft2(a) * np.exp(-2 * (np.pi * r * sigma) ** 2)))


def cells(n, rng, count):
    """Periodic Voronoi: (F1, F2) distances to the nearest and second-nearest cell centre, in pixels."""
    from scipy.spatial import cKDTree
    pts = rng.uniform(0, n, (count, 2))
    tree = cKDTree(pts, boxsize=n)
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    q = np.column_stack([xx.ravel() % n, yy.ravel() % n])
    d, _ = tree.query(q, k=2, workers=-1)
    return d[:, 0].reshape(n, n), d[:, 1].reshape(n, n)


# --------------------------------------------------------------------------- colour helpers
def srgb_to_lin(c):
    c = np.asarray(c, dtype=float) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255


# --------------------------------------------------------------------------- the finishes
def speckled_stone(n, rng):
    """Warm off-white casing with fine dark specks, a few warm specks and sparkling mica flakes (mean = the swatch)."""
    base = srgb_to_lin(SPECKLED_STONE)
    mottle = noise(n, rng, 2, 24, beta=1.2) - 0.5            # very soft clouds, +-2 %
    grain = noise(n, rng, n // 16, n // 3, beta=0.3) - 0.5     # the fine powder-coat grain
    # a tile is 120 mm: specks of 0.1 - 0.3 mm, mica flakes of 0.05 mm
    dark = splat(n, rng, 34000, 1 / 1100, amp=(0.25, 1.0))   # dark specks
    warm = splat(n, rng, 16000, 1 / 900, amp=(0.3, 1.0))     # warm brown specks
    mica = splat(n, rng, 20000, 1 / 2200, amp=(0.5, 1.0))   # mica flakes
    fleck = noise(n, rng, 60, 300, beta=0.6) - 0.5             # the stone's granular mottle, about 0.4 mm
    light = splat(n, rng, 9000, 1 / 700, amp=(0.4, 1.0))     # light flecks
    lum = (1 + 0.05 * mottle + 0.05 * grain + 0.20 * fleck - 0.95 * dark ** 1.1 - 0.30 * warm + 0.18 * mica
           + 0.07 * light)
    tint = np.stack([0.0 * warm, -0.06 * warm, -0.12 * warm], -1)   # warm specks lean to brown
    albedo = base * lum[..., None] * (1 + tint) * np.array([1.0, 1.0, 1.0])
    albedo *= base / albedo.reshape(-1, 3).mean(0)              # keep the swatch's mean colour
    rough = np.clip(0.46 + 0.05 * grain - 0.30 * mica, 0.08, 1)  # mica flakes catch the light
    bump = 0.55 * noise(n, rng, n // 24, n // 4, beta=0.8) + 0.25 * mica + 0.20 * (1 - dark)
    return {"albedo": lin_to_srgb(albedo), "rough": rough, "bump": norm01(bump)}


def warm_titanium(n, rng):
    """Metallic-paint flakes: tiny facets that change the roughness and the height a little."""
    flakes = splat(n, rng, 60000, 1 / 4000)                     # a tile is 40 mm: flakes of 0.01 mm
    orange_peel = noise(n, rng, n // 64, n // 10, beta=1.0)
    rough = np.clip(0.42 + 0.08 * (noise(n, rng, n // 8, n // 2, beta=0.2) - 0.5) - 0.14 * flakes, 0.05, 1)
    bump = norm01(0.7 * orange_peel + 0.3 * flakes)
    return {"rough": rough, "bump": bump}


def clay_leather(n, rng):
    """Pebble-grain upholstery: cells about 1 mm wide with soft creases between them, a little colour variation."""
    count = 5200                                                  # a tile is 80 mm: pebbles of about 1.1 mm
    f1, f2 = cells(n, rng, count)
    r = 2 * f1 / np.maximum(f1 + f2, 1e-9)                        # 0 at a pebble's centre, 1 at its crease
    pebble = blur(1 - r ** 2.6, 0.12 / np.sqrt(count))            # a rounded top, a narrow soft crease
    pebble *= 0.9 + 0.1 * noise(n, rng, 8, 120, beta=0.8)
    wrinkles = noise(n, rng, 3, 24, beta=1.6)
    height = norm01(pebble + 0.12 * wrinkles)
    base = srgb_to_lin(CLAY)
    shade = 0.84 + 0.16 * height + 0.05 * (noise(n, rng, 2, 16, beta=1.2) - 0.5)
    albedo = base * shade[..., None]
    albedo *= base / albedo.reshape(-1, 3).mean(0)
    rough = np.clip(0.62 - 0.12 * height, 0, 1)                  # cell tops a little smoother
    return {"albedo": lin_to_srgb(albedo), "rough": rough, "bump": height}


def stipple(n, rng):
    """Moulded soft-touch / rubber: a fine even stipple."""
    s = noise(n, rng, n // 20, n // 4, beta=0.4)
    d = splat(n, rng, 12000, 1 / 1500)
    return {"bump": norm01(0.75 * s + 0.25 * d), "rough": np.clip(0.55 + 0.15 * (s - 0.5), 0, 1)}


def belt(n, rng):
    """A running belt: a fine woven diamond texture (40 diamonds per tile), slightly irregular."""
    yy, xx = (np.mgrid[0:n, 0:n] + 0.5) / n
    k = 40
    weave = np.abs(np.sin(np.pi * k * (xx + yy))) * np.abs(np.sin(np.pi * k * (xx - yy)))
    wobble = noise(n, rng, n // 16, n // 4, beta=0.5)
    height = norm01(weave ** 0.5 + 0.25 * wobble)
    base = srgb_to_lin((58, 54, 50))
    albedo = base * (0.9 + 0.12 * height)[..., None]
    return {"albedo": lin_to_srgb(albedo), "rough": np.clip(0.78 - 0.18 * height, 0, 1), "bump": height}


def brushed(n, rng):
    """Brushed steel: long fine streaks along x."""
    streaks = noise(n, rng, n // 64, n // 2, beta=0.3, aniso=48)
    return {"rough": np.clip(0.30 + 0.12 * (streaks - 0.5), 0, 1), "bump": streaks}


FINISHES = {"speckled_stone": speckled_stone, "warm_titanium": warm_titanium, "clay_leather": clay_leather,
            "stipple": stipple, "belt": belt, "brushed": brushed}


# --------------------------------------------------------------------------- files
def write_png(path, data, bits):
    """An image as PNG: data 0..255 (RGB, 8 bit) or 0..1 (grey, 8 or 16 bit)."""
    from osgeo import gdal
    gdal.UseExceptions()
    data = np.asarray(data)
    if data.ndim == 3:
        bands = [np.clip(np.round(data[..., i]), 0, 255).astype(np.uint8) for i in range(3)]
        dtype = gdal.GDT_Byte
    elif bits == 16:
        bands, dtype = [np.round(np.clip(data, 0, 1) * 65535).astype(np.uint16)], gdal.GDT_UInt16
    else:
        bands, dtype = [np.round(np.clip(data, 0, 1) * 255).astype(np.uint8)], gdal.GDT_Byte
    mem = gdal.GetDriverByName("MEM").Create("", data.shape[1], data.shape[0], len(bands), dtype)
    for i, b in enumerate(bands, 1):
        mem.GetRasterBand(i).WriteArray(b)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    gdal.GetDriverByName("PNG").CreateCopy(str(path), mem, options=["ZLEVEL=6"])
    mem = None


def make_all(folder, size=SIZE, seed=SEED, only=None):
    """Every finish's maps into folder (skipping files that are there for this size); returns {file name: path}."""
    folder = Path(folder)
    out = {}
    for i, (name, fn) in enumerate(FINISHES.items()):
        if only and name not in only:
            continue
        wanted = {f"{name}_{kind}.png" for kind in ("albedo", "rough", "bump")}
        stamp = folder / f"{name}.{size}.done"
        if stamp.exists() and all((folder / w).exists() for w in wanted if (folder / w).exists()):
            out.update({p.name: p for p in folder.glob(f"{name}_*.png")})
            continue
        maps = fn(size, np.random.default_rng(seed + i))
        for kind, data in maps.items():
            path = folder / f"{name}_{kind}.png"
            write_png(path, data, 16 if kind == "bump" else 8)
            out[path.name] = path
        stamp.write_text("made by corona_materials.maps\n", encoding="utf-8")
    return out

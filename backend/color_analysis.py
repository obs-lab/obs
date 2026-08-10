import numpy as np


_M_RGB_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
], dtype=np.float64)

_D65 = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)

_LAB_DELTA = 6.0 / 29.0


def _srgb_linearize(c):
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def rgb_to_xyz(rgb):
    rgb = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = _srgb_linearize(rgb)
    return lin @ _M_RGB_XYZ.T


def _f_lab(t):
    t = np.asarray(t, dtype=np.float64)
    thr = _LAB_DELTA ** 3
    return np.where(t > thr, np.cbrt(t), t / (3.0 * _LAB_DELTA ** 2) + 4.0 / 29.0)


def rgb_to_lab(rgb):
    xyz = rgb_to_xyz(rgb)
    xyz_n = xyz / _D65
    f = _f_lab(xyz_n)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return np.stack([L, a, b], axis=-1)


def rgb_to_hex(rgb):
    r, g, b = (int(round(float(v))) for v in rgb)
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def delta_e_2000(lab1, lab2, k_L=1.0, k_C=1.0, k_H=1.0):
    L1, a1, b1 = (float(x) for x in lab1)
    L2, a2, b2 = (float(x) for x in lab2)

    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    C_bar = (C1 + C2) / 2.0

    G = 0.5 * (1.0 - np.sqrt(C_bar ** 7 / (C_bar ** 7 + 25.0 ** 7)))
    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2

    C1p = np.hypot(a1p, b1)
    C2p = np.hypot(a2p, b2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p

    if C1p * C2p == 0.0:
        dhp = 0.0
    else:
        diff = h2p - h1p
        if diff > 180.0:
            diff -= 360.0
        elif diff < -180.0:
            diff += 360.0
        dhp = diff
    dHp = 2.0 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp) / 2.0)

    Lp_bar = (L1 + L2) / 2.0
    Cp_bar = (C1p + C2p) / 2.0

    if C1p * C2p == 0.0:
        hp_bar = h1p + h2p
    else:
        s = h1p + h2p
        if abs(h1p - h2p) > 180.0:
            hp_bar = (s + 360.0) / 2.0 if s < 360.0 else (s - 360.0) / 2.0
        else:
            hp_bar = s / 2.0

    T = (1.0
         - 0.17 * np.cos(np.radians(hp_bar - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * hp_bar))
         + 0.32 * np.cos(np.radians(3.0 * hp_bar + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * hp_bar - 63.0)))

    d_theta = 30.0 * np.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    R_C = 2.0 * np.sqrt(Cp_bar ** 7 / (Cp_bar ** 7 + 25.0 ** 7))
    S_L = 1.0 + (0.015 * (Lp_bar - 50.0) ** 2) / np.sqrt(20.0 + (Lp_bar - 50.0) ** 2)
    S_C = 1.0 + 0.045 * Cp_bar
    S_H = 1.0 + 0.015 * Cp_bar * T
    R_T = -np.sin(np.radians(2.0 * d_theta)) * R_C

    term_L = dLp / (k_L * S_L)
    term_C = dCp / (k_C * S_C)
    term_H = dHp / (k_H * S_H)

    return float(np.sqrt(term_L ** 2 + term_C ** 2 + term_H ** 2 + R_T * term_C * term_H))


def sample_color(arr, cx, cy, radius=2):
    h, w = arr.shape[:2]
    cx = int(round(cx))
    cy = int(round(cy))
    r = max(0, int(radius))
    x0 = max(0, cx - r)
    x1 = min(w, cx + r + 1)
    y0 = max(0, cy - r)
    y1 = min(h, cy + r + 1)
    if x0 >= x1 or y0 >= y1:
        raise ValueError("Punto fuori dall'immagine.")
    patch = arr[y0:y1, x0:x1, :3].reshape(-1, 3).astype(np.float64)
    mean_rgb = patch.mean(axis=0)
    lab = rgb_to_lab(mean_rgb)
    return {
        "rgb": [int(round(v)) for v in mean_rgb],
        "hex": rgb_to_hex(mean_rgb),
        "lab": [round(float(v), 2) for v in lab],
        "pixels": int(patch.shape[0]),
    }


def _crop_region(arr, region):
    if not region:
        return arr
    h, w = arr.shape[:2]
    x0f, y0f, x1f, y1f = region
    x0f, x1f = sorted((float(x0f), float(x1f)))
    y0f, y1f = sorted((float(y0f), float(y1f)))
    x0 = max(0, min(w - 1, int(round(x0f * w))))
    x1 = max(x0 + 1, min(w, int(round(x1f * w))))
    y0 = max(0, min(h - 1, int(round(y0f * h))))
    y1 = max(y0 + 1, min(h, int(round(y1f * h))))
    return arr[y0:y1, x0:x1, :]


def dominant_colors(arr, k=5, region=None, max_samples=20000):
    from sklearn.cluster import KMeans

    sub = _crop_region(arr, region)
    pixels = sub[..., :3].reshape(-1, 3).astype(np.float64)
    if pixels.shape[0] == 0:
        raise ValueError("Nessun pixel nella regione selezionata.")

    if pixels.shape[0] > max_samples:
        idx = np.random.default_rng(0).choice(pixels.shape[0], max_samples, replace=False)
        sample = pixels[idx]
    else:
        sample = pixels

    k = max(1, min(int(k), sample.shape[0]))
    km = KMeans(n_clusters=k, n_init=4, random_state=0)
    labels = km.fit_predict(sample)
    centers = km.cluster_centers_

    counts = np.bincount(labels, minlength=k).astype(np.float64)
    coverage = counts / counts.sum()
    order = np.argsort(-coverage)

    out = []
    for i in order:
        c = centers[i]
        lab = rgb_to_lab(c)
        out.append({
            "rgb": [int(round(v)) for v in c],
            "hex": rgb_to_hex(c),
            "lab": [round(float(v), 2) for v in lab],
            "coverage": round(float(coverage[i]), 4),
        })
    return out
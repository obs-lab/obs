import math
from datetime import datetime, timezone


LINEAR = "linear"
LOG = "log"
TIME = "time"
CATEGORY = "category"


def is_numeric_axis(axis_type):
    return axis_type in (LINEAR, LOG, TIME)

_TIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%Y-%m",
    "%Y",
)


def _to_forward(value, axis_type):
    if axis_type == LINEAR:
        return float(value)
    if axis_type == LOG:
        v = float(value)
        if v <= 0:
            raise ValueError("Asse logaritmico: i valori devono essere maggiori di zero.")
        return math.log(v)
    if axis_type == TIME:
        return _time_to_number(value)
    raise ValueError("Tipo di asse non valido: " + str(axis_type))


def _from_forward(t, axis_type):
    if axis_type == LINEAR:
        return float(t)
    if axis_type == LOG:
        return math.exp(float(t))
    if axis_type == TIME:
        return _number_to_time(t)
    raise ValueError("Tipo di asse non valido: " + str(axis_type))


def _time_to_number(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    if isinstance(value, str):
        s = value.strip()
        for fmt in _TIME_FORMATS:
            try:
                dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue
        raise ValueError("Data non riconosciuta: " + s)
    raise ValueError("Valore temporale non valido: " + str(value))


def _number_to_time(t):
    return datetime.fromtimestamp(float(t), tz=timezone.utc)


def fit_axis(references, axis_type=LINEAR):
    n = len(references)
    if n < 2:
        raise ValueError("Servono almeno due riferimenti per calibrare un asse.")

    px = [float(p) for p, _ in references]
    tv = [_to_forward(v, axis_type) for _, v in references]

    if max(px) - min(px) == 0:
        raise ValueError("Tutti i riferimenti hanno lo stesso pixel: impossibile calibrare.")
    if max(tv) - min(tv) == 0:
        raise ValueError("Tutti i riferimenti hanno lo stesso valore: impossibile calibrare.")

    mean_p = sum(px) / n
    mean_t = sum(tv) / n
    sxx = sum((p - mean_p) ** 2 for p in px)
    sxy = sum((p - mean_p) * (t - mean_t) for p, t in zip(px, tv))

    slope = sxy / sxx
    intercept = mean_t - slope * mean_p

    sst = sum((t - mean_t) ** 2 for t in tv)
    ssr = sum((t - (slope * p + intercept)) ** 2 for p, t in zip(px, tv))
    r2 = 1.0 - (ssr / sst) if sst > 0 else 1.0

    residuals = [t - (slope * p + intercept) for p, t in zip(px, tv)]
    rms_px = (sum(r ** 2 for r in residuals) / n) ** 0.5 / abs(slope) if slope != 0 else 0.0

    return {
        "axis_type": axis_type,
        "slope": slope,
        "intercept": intercept,
        "r2": r2,
        "rms_pixel_error": rms_px,
        "n_references": n,
    }


def pixel_to_value(pixel, calibration):
    axis_type = calibration["axis_type"]
    t = calibration["slope"] * float(pixel) + calibration["intercept"]
    return _from_forward(t, axis_type)


def digitize_point(pixel_xy, cal_x, cal_y):
    px, py = pixel_xy
    return (pixel_to_value(px, cal_x), pixel_to_value(py, cal_y))


def calibration_warnings(cal_x, cal_y, r2_threshold=0.999, rms_threshold=4.0):
    warnings = []
    for axis_name, cal in (("X", cal_x), ("Y", cal_y)):
        if cal["n_references"] >= 3 and cal["r2"] < r2_threshold:
            warnings.append(
                "Asse " + axis_name + ": riferimenti poco coerenti (R2 "
                + format(cal["r2"], ".4f") + ")."
            )
        if cal["n_references"] >= 3 and cal["rms_pixel_error"] > rms_threshold:
            warnings.append(
                "Asse " + axis_name + ": scarto medio "
                + format(cal["rms_pixel_error"], ".1f") + " pixel."
            )
    return warnings

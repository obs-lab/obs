import ast
import math
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import integrate, interpolate, optimize, signal, stats

_trapz = getattr(np, "trapezoid", None) or np.trapz


class ComputeError(Exception):
    pass


_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Name,
    ast.Load,
    ast.Call,
    ast.Constant,
    ast.Compare,
    ast.BoolOp,
    ast.IfExp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


def _safe_log(x, base=None):
    with np.errstate(divide="ignore", invalid="ignore"):
        if base is None:
            return np.log(x)
        return np.log(x) / np.log(base)


_FORMULA_FUNCS = {
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "asin": np.arcsin,
    "acos": np.arccos,
    "atan": np.arctan,
    "sinh": np.sinh,
    "cosh": np.cosh,
    "tanh": np.tanh,
    "exp": np.exp,
    "log": _safe_log,
    "log10": np.log10,
    "log2": np.log2,
    "sqrt": np.sqrt,
    "abs": np.abs,
    "floor": np.floor,
    "ceil": np.ceil,
    "round": np.round,
    "sign": np.sign,
    "mean": np.nanmean,
    "median": np.nanmedian,
    "std": np.nanstd,
    "var": np.nanvar,
    "min": np.nanmin,
    "max": np.nanmax,
    "sum": np.nansum,
    "cumsum": np.nancumsum,
    "diff": lambda a: np.concatenate([[np.nan], np.diff(a)]),
    "norm": lambda a: (a - np.nanmean(a)) / (np.nanstd(a) or 1.0),
}

_FORMULA_CONSTS = {"pi": math.pi, "e": math.e, "nan": float("nan")}


def _validate_ast(node: ast.AST, allowed_names: set) -> None:
    for child in ast.walk(node):
        if not isinstance(child, _ALLOWED_NODES):
            raise ComputeError(
                "Construct not allowed in the formula: " + type(child).__name__
            )
        if isinstance(child, ast.Call):
            if not isinstance(child.func, ast.Name):
                raise ComputeError("Call not allowed in the formula.")
            if child.func.id not in _FORMULA_FUNCS:
                raise ComputeError("Unrecognized function: " + child.func.id)
            if child.keywords:
                raise ComputeError("Named arguments not allowed in the formula.")
        if isinstance(child, ast.Name):
            if child.id not in allowed_names:
                raise ComputeError("Unrecognized name in the formula: " + child.id)


def evaluate_formula(
    expression: str, columns: Dict[str, np.ndarray], length: int
) -> np.ndarray:
    expr = (expression or "").strip()
    if not expr:
        raise ComputeError("Empty formula.")
    if len(expr) > 512:
        raise ComputeError("Formula too long.")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ComputeError("Invalid syntax: " + str(exc.msg))
    allowed = set(columns) | set(_FORMULA_FUNCS) | set(_FORMULA_CONSTS)
    _validate_ast(tree, allowed)
    env = {"__builtins__": {}}
    env.update(_FORMULA_FUNCS)
    env.update(_FORMULA_CONSTS)
    env.update(columns)
    try:
        with np.errstate(all="ignore"):
            result = eval(compile(tree, "<formula>", "eval"), env, {})
    except ComputeError:
        raise
    except Exception as exc:
        raise ComputeError("Evaluation error: " + str(exc))
    arr = np.asarray(result, dtype=float)
    if arr.ndim == 0:
        arr = np.full(length, float(arr))
    if arr.shape[0] != length:
        raise ComputeError("The formula produced an incompatible length.")
    return arr


def to_numeric(values: List[Any]) -> np.ndarray:
    out = np.empty(len(values), dtype=float)
    for i, v in enumerate(values):
        if v is None:
            out[i] = np.nan
            continue
        s = str(v).strip()
        if not s:
            out[i] = np.nan
            continue
        s = s.replace(",", ".") if s.count(",") == 1 and "." not in s else s
        try:
            out[i] = float(s)
        except ValueError:
            out[i] = np.nan
    return out


def sheet_arrays(columns: List[Dict[str, Any]], rows: List[List[Any]]) -> Dict[str, np.ndarray]:
    out = {}
    for i, col in enumerate(columns):
        raw = [r[i] if i < len(r) else "" for r in rows]
        if col.get("kind") == "text":
            out[col["name"]] = np.array([str(v) for v in raw], dtype=object)
        else:
            out[col["name"]] = to_numeric(raw)
    return out


def clean_pair(x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def clean(a: np.ndarray) -> np.ndarray:
    return a[np.isfinite(a)]


def _f(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return v


def descriptive(a: np.ndarray, confidence: float = 0.95) -> Dict[str, Any]:
    d = clean(a)
    n = int(d.size)
    if n == 0:
        raise ComputeError("No valid numeric value in the column.")
    mean = float(np.mean(d))
    sd = float(np.std(d, ddof=1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 1 else 0.0
    if n > 1 and se > 0:
        half = float(stats.t.ppf(0.5 + confidence / 2.0, n - 1) * se)
    else:
        half = 0.0
    q1, q3 = (float(np.percentile(d, 25)), float(np.percentile(d, 75)))
    return {
        "n": n,
        "mean": mean,
        "median": float(np.median(d)),
        "std": sd,
        "variance": float(np.var(d, ddof=1)) if n > 1 else 0.0,
        "sem": se,
        "min": float(np.min(d)),
        "max": float(np.max(d)),
        "range": float(np.max(d) - np.min(d)),
        "sum": float(np.sum(d)),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
        "skewness": _f(stats.skew(d)) if n > 2 else None,
        "kurtosis": _f(stats.kurtosis(d)) if n > 3 else None,
        "ci_level": confidence,
        "ci_lower": mean - half,
        "ci_upper": mean + half,
    }


def normality(a: np.ndarray) -> Dict[str, Any]:
    d = clean(a)
    if d.size < 3:
        raise ComputeError("At least 3 values are required for a normality test.")
    out = {"n": int(d.size)}
    if d.size <= 5000:
        w, p = stats.shapiro(d)
        out["shapiro"] = {"statistic": float(w), "p_value": float(p)}
    if d.size >= 8:
        k2, p = stats.normaltest(d)
        out["dagostino"] = {"statistic": float(k2), "p_value": float(p)}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ad = stats.anderson(d, dist="norm")
        out["anderson"] = {
            "statistic": float(ad.statistic),
            "critical_values": [float(v) for v in ad.critical_values],
            "significance_levels": [float(v) for v in ad.significance_level],
        }
    except (AttributeError, TypeError, ValueError):
        pass
    return out


def ttest(
    a: np.ndarray,
    b: Optional[np.ndarray] = None,
    kind: str = "two_sample",
    mu: float = 0.0,
    equal_var: bool = True,
) -> Dict[str, Any]:
    x = clean(a)
    if kind == "one_sample":
        if x.size < 2:
            raise ComputeError("At least 2 values are required.")
        t, p = stats.ttest_1samp(x, mu)
        return {
            "test": "one-sample t",
            "n": int(x.size),
            "mu": mu,
            "mean": float(np.mean(x)),
            "statistic": float(t),
            "p_value": float(p),
            "df": int(x.size - 1),
        }
    if b is None:
        raise ComputeError("The test requires a second column.")
    if kind == "paired":
        mask = np.isfinite(a) & np.isfinite(b)
        xa, xb = a[mask], b[mask]
        if xa.size < 2:
            raise ComputeError("At least 2 valid pairs are required.")
        t, p = stats.ttest_rel(xa, xb)
        return {
            "test": "paired t",
            "n": int(xa.size),
            "mean_difference": float(np.mean(xa - xb)),
            "statistic": float(t),
            "p_value": float(p),
            "df": int(xa.size - 1),
        }
    y = clean(b)
    if x.size < 2 or y.size < 2:
        raise ComputeError("At least 2 values per group are required.")
    t, p = stats.ttest_ind(x, y, equal_var=equal_var)
    return {
        "test": "two-sample t" if equal_var else "Welch test",
        "n1": int(x.size),
        "n2": int(y.size),
        "mean1": float(np.mean(x)),
        "mean2": float(np.mean(y)),
        "statistic": float(t),
        "p_value": float(p),
    }


def nonparametric(a: np.ndarray, b: np.ndarray, kind: str) -> Dict[str, Any]:
    if kind == "mann_whitney":
        x, y = clean(a), clean(b)
        if x.size < 1 or y.size < 1:
            raise ComputeError("Gruppi vuoti.")
        u, p = stats.mannwhitneyu(x, y, alternative="two-sided")
        return {"test": "Mann-Whitney", "statistic": float(u), "p_value": float(p),
                "n1": int(x.size), "n2": int(y.size)}
    if kind == "wilcoxon":
        mask = np.isfinite(a) & np.isfinite(b)
        xa, xb = a[mask], b[mask]
        if xa.size < 1:
            raise ComputeError("No valid pair.")
        w, p = stats.wilcoxon(xa, xb)
        return {"test": "Paired Wilcoxon", "statistic": float(w),
                "p_value": float(p), "n": int(xa.size)}
    if kind == "ks":
        x, y = clean(a), clean(b)
        d, p = stats.ks_2samp(x, y)
        return {"test": "Kolmogorov-Smirnov", "statistic": float(d),
                "p_value": float(p), "n1": int(x.size), "n2": int(y.size)}
    raise ComputeError("Unrecognized test: " + str(kind))


def anova(groups: List[np.ndarray], kind: str = "one_way") -> Dict[str, Any]:
    cleaned = [clean(g) for g in groups]
    cleaned = [g for g in cleaned if g.size > 0]
    if len(cleaned) < 2:
        raise ComputeError("At least two non-empty groups are required.")
    if kind == "kruskal":
        h, p = stats.kruskal(*cleaned)
        return {"test": "Kruskal-Wallis", "statistic": float(h), "p_value": float(p),
                "groups": len(cleaned)}
    f, p = stats.f_oneway(*cleaned)
    total = sum(g.size for g in cleaned)
    grand = float(np.mean(np.concatenate(cleaned)))
    ss_between = sum(g.size * (float(np.mean(g)) - grand) ** 2 for g in cleaned)
    ss_within = sum(float(np.sum((g - np.mean(g)) ** 2)) for g in cleaned)
    df_b = len(cleaned) - 1
    df_w = total - len(cleaned)
    return {
        "test": "One-way ANOVA",
        "statistic": float(f),
        "p_value": float(p),
        "df_between": df_b,
        "df_within": df_w,
        "ss_between": ss_between,
        "ss_within": ss_within,
        "ms_between": ss_between / df_b if df_b else None,
        "ms_within": ss_within / df_w if df_w else None,
        "group_means": [float(np.mean(g)) for g in cleaned],
        "group_sizes": [int(g.size) for g in cleaned],
    }


def correlation(series: Dict[str, np.ndarray], method: str = "pearson") -> Dict[str, Any]:
    names = list(series)
    if len(names) < 2:
        raise ComputeError("At least two columns are required.")
    n = len(names)
    matrix = [[1.0] * n for _ in range(n)]
    pvals = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            x, y = clean_pair(series[names[i]], series[names[j]])
            if x.size < 3:
                r, p = float("nan"), float("nan")
            elif method == "spearman":
                r, p = stats.spearmanr(x, y)
            elif method == "kendall":
                r, p = stats.kendalltau(x, y)
            else:
                r, p = stats.pearsonr(x, y)
            matrix[i][j] = matrix[j][i] = _f(r)
            pvals[i][j] = pvals[j][i] = _f(p)
    return {"method": method, "names": names, "matrix": matrix, "p_values": pvals}


def linear_fit(x: np.ndarray, y: np.ndarray, through_origin: bool = False) -> Dict[str, Any]:
    xs, ys = clean_pair(x, y)
    if xs.size < 3:
        raise ComputeError("At least 3 valid points are required.")
    n = xs.size
    if through_origin:
        slope = float(np.sum(xs * ys) / np.sum(xs * xs))
        intercept = 0.0
        pred = slope * xs
        dof = n - 1
    else:
        design = np.vstack([xs, np.ones(n)]).T
        coef, *_ = np.linalg.lstsq(design, ys, rcond=None)
        slope, intercept = float(coef[0]), float(coef[1])
        pred = slope * xs + intercept
        dof = n - 2
    resid = ys - pred
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((ys - np.mean(ys)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    mse = ss_res / dof if dof > 0 else float("nan")
    sxx = float(np.sum((xs - np.mean(xs)) ** 2))
    se_slope = math.sqrt(mse / sxx) if sxx > 0 and np.isfinite(mse) else float("nan")
    se_inter = (
        math.sqrt(mse * (1.0 / n + np.mean(xs) ** 2 / sxx))
        if sxx > 0 and np.isfinite(mse) and not through_origin
        else float("nan")
    )
    npar = 1 if through_origin else 2
    adj = 1.0 - (1.0 - r2) * (n - 1) / dof if dof > 0 and np.isfinite(r2) else None
    return {
        "model": "linear regression",
        "n": int(n),
        "slope": slope,
        "intercept": intercept,
        "se_slope": _f(se_slope),
        "se_intercept": _f(se_inter),
        "r_squared": _f(r2),
        "adj_r_squared": _f(adj),
        "residual_std": _f(math.sqrt(mse)) if np.isfinite(mse) else None,
        "ss_residual": ss_res,
        "ss_total": ss_tot,
        "df": int(dof),
        "parameters": npar,
        "fit_x": [float(v) for v in xs],
        "fit_y": [float(v) for v in pred],
        "residuals": [float(v) for v in resid],
    }


def polynomial_fit(x: np.ndarray, y: np.ndarray, degree: int = 2) -> Dict[str, Any]:
    xs, ys = clean_pair(x, y)
    degree = max(1, min(int(degree), 9))
    if xs.size <= degree + 1:
        raise ComputeError("Not enough points for the requested degree.")
    coef, cov = np.polyfit(xs, ys, degree, cov=True)
    pred = np.polyval(coef, xs)
    resid = ys - pred
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((ys - np.mean(ys)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    order = np.argsort(xs)
    return {
        "model": "polynomial regression",
        "degree": degree,
        "n": int(xs.size),
        "coefficients": [float(c) for c in coef],
        "std_errors": [float(v) for v in np.sqrt(np.diag(cov))],
        "r_squared": _f(r2),
        "ss_residual": ss_res,
        "fit_x": [float(v) for v in xs[order]],
        "fit_y": [float(v) for v in pred[order]],
        "residuals": [float(v) for v in resid],
    }


def _gaussian(x, a, mu, sigma, base):
    return base + a * np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def _lorentzian(x, a, mu, gamma, base):
    return base + a * gamma ** 2 / ((x - mu) ** 2 + gamma ** 2)


def _exp_decay(x, a, tau, base):
    return base + a * np.exp(-x / tau)


def _exp_growth(x, a, tau, base):
    return base + a * np.exp(x / tau)


def _logistic(x, top, bottom, x0, rate):
    return bottom + (top - bottom) / (1.0 + np.exp(-rate * (x - x0)))


def _boltzmann(x, a1, a2, x0, dx):
    return a2 + (a1 - a2) / (1.0 + np.exp((x - x0) / dx))


def _hill(x, vmax, k, n):
    return vmax * x ** n / (k ** n + x ** n)


def _power(x, a, b):
    return a * np.power(x, b)


def _michaelis(x, vmax, km):
    return vmax * x / (km + x)


NONLINEAR_MODELS = {
    "gaussian": (_gaussian, ["amplitude", "centro", "sigma", "base"]),
    "lorentzian": (_lorentzian, ["amplitude", "centro", "gamma", "base"]),
    "exp_decay": (_exp_decay, ["amplitude", "tau", "base"]),
    "exp_growth": (_exp_growth, ["amplitude", "tau", "base"]),
    "logistic": (_logistic, ["maximum", "minimum", "x0", "slope"]),
    "boltzmann": (_boltzmann, ["A1", "A2", "x0", "dx"]),
    "hill": (_hill, ["Vmax", "K", "n"]),
    "power": (_power, ["a", "b"]),
    "michaelis_menten": (_michaelis, ["Vmax", "Km"]),
}


def _initial_guess(model: str, xs: np.ndarray, ys: np.ndarray) -> List[float]:
    span = float(np.max(xs) - np.min(xs)) or 1.0
    ymin, ymax = float(np.min(ys)), float(np.max(ys))
    xpeak = float(xs[int(np.argmax(ys))])
    if model == "gaussian":
        return [ymax - ymin, xpeak, span / 6.0, ymin]
    if model == "lorentzian":
        return [ymax - ymin, xpeak, span / 6.0, ymin]
    if model in ("exp_decay", "exp_growth"):
        return [ymax - ymin, span / 2.0 or 1.0, ymin]
    if model == "logistic":
        return [ymax, ymin, float(np.median(xs)), 1.0 / (span / 10.0)]
    if model == "boltzmann":
        return [ymin, ymax, float(np.median(xs)), span / 10.0]
    if model == "hill":
        return [ymax, float(np.median(xs)) or 1.0, 1.0]
    if model == "power":
        return [1.0, 1.0]
    if model == "michaelis_menten":
        return [ymax, float(np.median(xs)) or 1.0]
    return [1.0]


def nonlinear_fit(
    x: np.ndarray, y: np.ndarray, model: str, guess: Optional[List[float]] = None
) -> Dict[str, Any]:
    if model not in NONLINEAR_MODELS:
        raise ComputeError("Unrecognized model: " + str(model))
    func, names = NONLINEAR_MODELS[model]
    xs, ys = clean_pair(x, y)
    if xs.size < len(names) + 1:
        raise ComputeError("Not enough points for the chosen model.")
    p0 = guess if guess and len(guess) == len(names) else _initial_guess(model, xs, ys)
    try:
        popt, pcov = optimize.curve_fit(func, xs, ys, p0=p0, maxfev=20000)
    except (RuntimeError, ValueError) as exc:
        raise ComputeError("Fit did not converge: " + str(exc))
    pred = func(xs, *popt)
    resid = ys - pred
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((ys - np.mean(ys)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    dof = xs.size - len(popt)
    errs = np.sqrt(np.abs(np.diag(pcov))) if pcov is not None else np.full(len(popt), np.nan)
    order = np.argsort(xs)
    dense = np.linspace(float(np.min(xs)), float(np.max(xs)), 300)
    aic = xs.size * math.log(ss_res / xs.size) + 2 * len(popt) if ss_res > 0 else None
    return {
        "model": model,
        "n": int(xs.size),
        "parameter_names": names,
        "parameters": [float(v) for v in popt],
        "std_errors": [_f(v) for v in errs],
        "r_squared": _f(r2),
        "adj_r_squared": _f(1.0 - (1.0 - r2) * (xs.size - 1) / dof) if dof > 0 else None,
        "reduced_chi_square": _f(ss_res / dof) if dof > 0 else None,
        "aic": _f(aic),
        "ss_residual": ss_res,
        "fit_x": [float(v) for v in dense],
        "fit_y": [float(v) for v in func(dense, *popt)],
        "residuals": [float(v) for v in resid[order]],
    }


def interpolate_series(
    x: np.ndarray, y: np.ndarray, method: str = "cubic", points: int = 200
) -> Dict[str, Any]:
    xs, ys = clean_pair(x, y)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    uniq, idx = np.unique(xs, return_index=True)
    xs, ys = uniq, ys[idx]
    if xs.size < 2:
        raise ComputeError("At least 2 distinct points are required.")
    points = max(10, min(int(points), 5000))
    dense = np.linspace(float(xs[0]), float(xs[-1]), points)
    if method == "linear":
        vals = np.interp(dense, xs, ys)
    elif method == "akima":
        if xs.size < 3:
            raise ComputeError("Akima requires at least 3 points.")
        vals = interpolate.Akima1DInterpolator(xs, ys)(dense)
    elif method == "pchip":
        vals = interpolate.PchipInterpolator(xs, ys)(dense)
    elif method == "bspline":
        k = min(3, xs.size - 1)
        tck = interpolate.splrep(xs, ys, k=k)
        vals = interpolate.splev(dense, tck)
    else:
        if xs.size < 4:
            raise ComputeError("The cubic spline requires at least 4 points.")
        vals = interpolate.CubicSpline(xs, ys)(dense)
    return {
        "method": method,
        "x": [float(v) for v in dense],
        "y": [float(v) for v in vals],
    }


def smooth_series(
    y: np.ndarray, method: str = "savgol", window: int = 11, order: int = 3
) -> Dict[str, Any]:
    d = np.asarray(y, dtype=float)
    finite = np.isfinite(d)
    if finite.sum() < 3:
        raise ComputeError("Not enough values for smoothing.")
    work = d.copy()
    if not finite.all():
        idx = np.arange(d.size)
        work[~finite] = np.interp(idx[~finite], idx[finite], d[finite])
    window = max(3, int(window))
    if window % 2 == 0:
        window += 1
    window = min(window, work.size if work.size % 2 == 1 else work.size - 1)
    if method == "adjacent":
        kernel = np.ones(window) / window
        out = np.convolve(work, kernel, mode="same")
    elif method == "percentile":
        half = window // 2
        out = np.array(
            [
                np.percentile(work[max(0, i - half): i + half + 1], 50)
                for i in range(work.size)
            ]
        )
    elif method == "lowess":
        import statsmodels.api as sm

        frac = max(0.05, min(1.0, window / max(work.size, 1)))
        res = sm.nonparametric.lowess(work, np.arange(work.size), frac=frac)
        out = res[:, 1]
    else:
        order = max(1, min(int(order), window - 1))
        out = signal.savgol_filter(work, window, order)
    return {
        "method": method,
        "window": int(window),
        "y": [float(v) for v in out],
    }


def fft_analysis(y: np.ndarray, sample_rate: float = 1.0) -> Dict[str, Any]:
    d = clean(y)
    if d.size < 4:
        raise ComputeError("At least 4 samples are required.")
    sample_rate = float(sample_rate) if sample_rate and sample_rate > 0 else 1.0
    spectrum = np.fft.rfft(d - np.mean(d))
    freqs = np.fft.rfftfreq(d.size, d=1.0 / sample_rate)
    amplitude = np.abs(spectrum) * 2.0 / d.size
    power = amplitude ** 2
    peak = int(np.argmax(amplitude[1:]) + 1) if amplitude.size > 1 else 0
    return {
        "n": int(d.size),
        "sample_rate": sample_rate,
        "frequency": [float(v) for v in freqs],
        "amplitude": [float(v) for v in amplitude],
        "power": [float(v) for v in power],
        "phase": [float(v) for v in np.angle(spectrum)],
        "dominant_frequency": float(freqs[peak]) if freqs.size > peak else None,
    }


def digital_filter(
    y: np.ndarray,
    kind: str = "lowpass",
    design: str = "butter",
    order: int = 4,
    cutoff: float = 0.1,
    cutoff_high: float = 0.4,
    sample_rate: float = 1.0,
) -> Dict[str, Any]:
    d = np.asarray(y, dtype=float)
    finite = np.isfinite(d)
    if finite.sum() < 8:
        raise ComputeError("Not enough samples for filtering.")
    work = d.copy()
    if not finite.all():
        idx = np.arange(d.size)
        work[~finite] = np.interp(idx[~finite], idx[finite], d[finite])
    nyq = float(sample_rate) / 2.0 if sample_rate and sample_rate > 0 else 0.5
    lo = float(cutoff) / nyq
    hi = float(cutoff_high) / nyq
    lo = min(max(lo, 1e-6), 0.999)
    hi = min(max(hi, 1e-6), 0.999)
    if kind in ("bandpass", "bandstop"):
        if lo >= hi:
            raise ComputeError("The lower frequency must be smaller than the upper one.")
        wn = [lo, hi]
    else:
        wn = lo
    order = max(1, min(int(order), 10))
    kwargs = {"btype": kind, "output": "sos"}
    if design == "cheby1":
        sos = signal.cheby1(order, 1.0, wn, **kwargs)
    elif design == "cheby2":
        sos = signal.cheby2(order, 40.0, wn, **kwargs)
    elif design == "ellip":
        sos = signal.ellip(order, 1.0, 40.0, wn, **kwargs)
    else:
        sos = signal.butter(order, wn, **kwargs)
    out = signal.sosfiltfilt(sos, work)
    return {
        "filter": design,
        "type": kind,
        "order": order,
        "y": [float(v) for v in out],
    }


def _baseline_als(y: np.ndarray, lam: float = 1e5, p: float = 0.01, niter: int = 10) -> np.ndarray:
    from scipy import sparse
    from scipy.sparse import linalg as splinalg

    n = y.size
    diff = sparse.diags([1.0, -2.0, 1.0], [0, -1, -2], shape=(n, n - 2))
    penalty = lam * diff.dot(diff.transpose())
    w = np.ones(n)
    z = y.copy()
    for _ in range(niter):
        wmat = sparse.spdiags(w, 0, n, n)
        z = splinalg.spsolve((wmat + penalty).tocsc(), w * y)
        w = p * (y > z) + (1 - p) * (y < z)
    return z


def peak_analysis(
    x: np.ndarray,
    y: np.ndarray,
    prominence: Optional[float] = None,
    height: Optional[float] = None,
    distance: Optional[int] = None,
    baseline: bool = True,
) -> Dict[str, Any]:
    xs, ys = clean_pair(x, y)
    if xs.size < 5:
        raise ComputeError("At least 5 points are required.")
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    base = _baseline_als(ys) if baseline else np.zeros_like(ys)
    corrected = ys - base
    span = float(np.max(corrected) - np.min(corrected)) or 1.0
    prom = float(prominence) if prominence is not None else span * 0.05
    kwargs = {"prominence": prom}
    if height is not None:
        kwargs["height"] = float(height)
    if distance is not None and int(distance) > 0:
        kwargs["distance"] = int(distance)
    idx, props = signal.find_peaks(corrected, **kwargs)
    widths, width_heights, left_ips, right_ips = signal.peak_widths(
        corrected, idx, rel_height=0.5
    )
    peaks = []
    for k, i in enumerate(idx):
        left = int(max(0, math.floor(left_ips[k])))
        right = int(min(xs.size - 1, math.ceil(right_ips[k])))
        seg_x, seg_y = xs[left: right + 1], corrected[left: right + 1]
        area = float(_trapz(seg_y, seg_x)) if seg_x.size > 1 else 0.0
        total = float(np.sum(seg_y))
        centroid = float(np.sum(seg_x * seg_y) / total) if total else float(xs[i])
        dx = float(np.mean(np.diff(xs))) if xs.size > 1 else 1.0
        peaks.append(
            {
                "index": int(i),
                "center": float(xs[i]),
                "height": float(corrected[i]),
                "raw_height": float(ys[i]),
                "prominence": float(props["prominences"][k]),
                "fwhm": float(widths[k] * dx),
                "area": area,
                "centroid": centroid,
                "left": float(xs[left]),
                "right": float(xs[right]),
            }
        )
    total_area = sum(p["area"] for p in peaks)
    for p in peaks:
        p["area_percent"] = (p["area"] / total_area * 100.0) if total_area else 0.0
    return {
        "count": len(peaks),
        "peaks": peaks,
        "baseline": [float(v) for v in base],
        "corrected": [float(v) for v in corrected],
        "x": [float(v) for v in xs],
    }


def differentiate(x: np.ndarray, y: np.ndarray, order: int = 1) -> Dict[str, Any]:
    xs, ys = clean_pair(x, y)
    if xs.size < 3:
        raise ComputeError("At least 3 points are required.")
    idx = np.argsort(xs)
    xs, ys = xs[idx], ys[idx]
    out = ys
    for _ in range(max(1, min(int(order), 3))):
        out = np.gradient(out, xs)
    return {
        "order": int(order),
        "x": [float(v) for v in xs],
        "y": [float(v) for v in out],
    }


def integrate_series(x: np.ndarray, y: np.ndarray, baseline: float = 0.0) -> Dict[str, Any]:
    xs, ys = clean_pair(x, y)
    if xs.size < 2:
        raise ComputeError("At least 2 points are required.")
    idx = np.argsort(xs)
    xs, ys = xs[idx], ys[idx] - float(baseline)
    cumulative = integrate.cumulative_trapezoid(ys, xs, initial=0.0)
    total = float(_trapz(ys, xs))
    peak_i = int(np.argmax(np.abs(ys)))
    return {
        "area": total,
        "absolute_area": float(_trapz(np.abs(ys), xs)),
        "mean_value": total / float(xs[-1] - xs[0]) if xs[-1] != xs[0] else None,
        "peak_x": float(xs[peak_i]),
        "peak_y": float(ys[peak_i]),
        "x": [float(v) for v in xs],
        "cumulative": [float(v) for v in cumulative],
    }


def histogram_bins(a: np.ndarray, bins: Any = "auto") -> Dict[str, Any]:
    d = clean(a)
    if d.size < 1:
        raise ComputeError("No valid value.")
    try:
        nbins = int(bins)
    except (TypeError, ValueError):
        nbins = "auto"
    counts, edges = np.histogram(d, bins=nbins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    return {
        "counts": [int(v) for v in counts],
        "edges": [float(v) for v in edges],
        "centers": [float(v) for v in centers],
        "density": [float(v) for v in counts / (d.size * np.diff(edges))],
    }


ANALYSES = {
    "descriptive": "Descriptive statistics",
    "normality": "Normality test",
    "ttest_one": "One-sample t test",
    "ttest_two": "Two-sample t test",
    "ttest_paired": "Paired t test",
    "welch": "Welch test",
    "mann_whitney": "Mann-Whitney",
    "wilcoxon": "Paired Wilcoxon",
    "ks": "Kolmogorov-Smirnov",
    "anova": "One-way ANOVA",
    "kruskal": "Kruskal-Wallis",
    "correlation": "Correlation",
    "linear_fit": "Linear regression",
    "polynomial_fit": "Polynomial regression",
    "nonlinear_fit": "Nonlinear fit",
    "interpolate": "Interpolation",
    "smooth": "Smoothing",
    "fft": "Fourier transform",
    "filter": "Digital filter",
    "peaks": "Peak analysis",
    "differentiate": "Numerical differentiation",
    "integrate": "Numerical integration",
    "histogram": "Histogram",
}

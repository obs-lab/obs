import csv
import io
import json
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import sheets_compute as compute
import sheets_plots as plots
import sheets_store as store
from auth_routes import current_user

router = APIRouter(prefix="/api/sheets", tags=["sheets"])

MAX_IMPORT_BYTES = 8 * 1024 * 1024


class WorkbookRequest(BaseModel):
    name: str = "Workbook"


class SheetRequest(BaseModel):
    name: str = ""


class SaveSheetRequest(BaseModel):
    name: Optional[str] = None
    columns: List[Dict[str, Any]]
    rows: List[List[Any]]


class FormulaRequest(BaseModel):
    expression: str
    target: str


class AnalyzeRequest(BaseModel):
    analysis: str
    columns: List[Dict[str, Any]]
    rows: List[List[Any]]
    params: Dict[str, Any] = {}


class PlotRequest(BaseModel):
    plot_type: str
    columns: List[Dict[str, Any]]
    rows: List[List[Any]]
    config: Dict[str, Any] = {}


class SavePlotRequest(BaseModel):
    name: str
    plot_type: str
    config: Dict[str, Any] = {}
    plot_id: Optional[str] = None


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _series(columns: List[Dict[str, Any]], rows: List[List[Any]]) -> Dict[str, np.ndarray]:
    cols = store.normalize_columns(columns)
    data = store.normalize_rows(rows, len(cols))
    return compute.sheet_arrays(cols, data)


def _pick(series: Dict[str, np.ndarray], name: Optional[str]) -> np.ndarray:
    if not name or name not in series:
        raise compute.ComputeError("Column not found: " + str(name))
    return np.asarray(series[name], dtype=float)


def _roles(columns: List[Dict[str, Any]], role: str) -> List[str]:
    return [c["name"] for c in store.normalize_columns(columns) if c.get("role") == role]


@router.get("/plot-types")
def plot_types(user: dict = Depends(current_user)):
    return plots.plot_catalog()


@router.get("/analyses")
def analyses(user: dict = Depends(current_user)):
    return {
        "analyses": [{"id": k, "label": v} for k, v in compute.ANALYSES.items()],
        "models": [
            {"id": k, "parameters": v[1]}
            for k, v in compute.NONLINEAR_MODELS.items()
        ],
    }


@router.get("/workbooks")
def get_workbooks(user: dict = Depends(current_user)):
    return {"workbooks": store.list_workbooks(user["user_id"])}


@router.post("/workbooks")
def post_workbook(req: WorkbookRequest, user: dict = Depends(current_user)):
    try:
        return store.create_workbook(user["user_id"], req.name)
    except store.SheetsError as exc:
        raise _fail(exc)


@router.get("/workbooks/{workbook_id}")
def get_workbook(workbook_id: str, user: dict = Depends(current_user)):
    wb = store.get_workbook(user["user_id"], workbook_id)
    if not wb:
        raise HTTPException(status_code=404, detail="Workbook not found.")
    return wb


@router.patch("/workbooks/{workbook_id}")
def patch_workbook(
    workbook_id: str, req: WorkbookRequest, user: dict = Depends(current_user)
):
    try:
        ok = store.rename_workbook(user["user_id"], workbook_id, req.name)
    except store.SheetsError as exc:
        raise _fail(exc)
    if not ok:
        raise HTTPException(status_code=404, detail="Workbook not found.")
    return {"ok": True}


@router.delete("/workbooks/{workbook_id}")
def remove_workbook(workbook_id: str, user: dict = Depends(current_user)):
    if not store.delete_workbook(user["user_id"], workbook_id):
        raise HTTPException(status_code=404, detail="Workbook not found.")
    return {"ok": True}


@router.post("/workbooks/{workbook_id}/sheets")
def post_sheet(
    workbook_id: str, req: SheetRequest, user: dict = Depends(current_user)
):
    try:
        sheet = store.add_sheet(user["user_id"], workbook_id, req.name)
    except store.SheetsError as exc:
        raise _fail(exc)
    if not sheet:
        raise HTTPException(status_code=404, detail="Workbook not found.")
    return sheet


@router.get("/sheets/{sheet_id}")
def get_sheet(sheet_id: str, user: dict = Depends(current_user)):
    sheet = store.get_sheet(user["user_id"], sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Sheet not found.")
    sheet["plots"] = store.list_plots(user["user_id"], sheet_id)
    return sheet


@router.put("/sheets/{sheet_id}")
def put_sheet(
    sheet_id: str, req: SaveSheetRequest, user: dict = Depends(current_user)
):
    try:
        saved = store.save_sheet(user["user_id"], sheet_id, req.name, req.columns, req.rows)
    except store.SheetsError as exc:
        raise _fail(exc)
    if not saved:
        raise HTTPException(status_code=404, detail="Sheet not found.")
    return saved


@router.delete("/sheets/{sheet_id}")
def remove_sheet(sheet_id: str, user: dict = Depends(current_user)):
    try:
        ok = store.delete_sheet(user["user_id"], sheet_id)
    except store.SheetsError as exc:
        raise _fail(exc)
    if not ok:
        raise HTTPException(status_code=404, detail="Sheet not found.")
    return {"ok": True}


@router.post("/sheets/{sheet_id}/formula")
def post_formula(
    sheet_id: str, req: FormulaRequest, user: dict = Depends(current_user)
):
    sheet = store.get_sheet(user["user_id"], sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Sheet not found.")
    try:
        series = compute.sheet_arrays(sheet["columns"], sheet["rows"])
        numeric = {
            k: np.asarray(v, dtype=float)
            for k, v in series.items()
            if v.dtype != object
        }
        values = compute.evaluate_formula(
            req.expression, numeric, len(sheet["rows"])
        )
    except compute.ComputeError as exc:
        raise _fail(exc)
    return {
        "target": req.target,
        "values": [None if not np.isfinite(v) else float(v) for v in values],
    }


@router.post("/sheets/{sheet_id}/analyze")
def post_analyze(
    sheet_id: str, req: AnalyzeRequest, user: dict = Depends(current_user)
):
    if not store.get_sheet(user["user_id"], sheet_id):
        raise HTTPException(status_code=404, detail="Sheet not found.")
    try:
        series = _series(req.columns, req.rows)
        return {
            "analysis": req.analysis,
            "label": compute.ANALYSES.get(req.analysis, req.analysis),
            "result": _run_analysis(req.analysis, series, req.columns, req.params),
        }
    except (compute.ComputeError, store.SheetsError) as exc:
        raise _fail(exc)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise _fail(exc)


def _run_analysis(
    name: str,
    series: Dict[str, np.ndarray],
    columns: List[Dict[str, Any]],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    xs = _roles(columns, "x")
    ys = _roles(columns, "y")
    x_name = params.get("x") or (xs[0] if xs else None)
    y_name = params.get("y") or (ys[0] if ys else None)
    y2_name = params.get("y2") or (ys[1] if len(ys) > 1 else None)

    if name == "descriptive":
        targets = params.get("targets") or ys or list(series)
        return {
            "columns": {
                t: compute.descriptive(
                    _pick(series, t), float(params.get("confidence", 0.95))
                )
                for t in targets
            }
        }
    if name == "normality":
        return compute.normality(_pick(series, y_name))
    if name == "ttest_one":
        return compute.ttest(
            _pick(series, y_name), kind="one_sample", mu=float(params.get("mu", 0.0))
        )
    if name == "ttest_two":
        return compute.ttest(_pick(series, y_name), _pick(series, y2_name),
                             kind="two_sample", equal_var=True)
    if name == "welch":
        return compute.ttest(_pick(series, y_name), _pick(series, y2_name),
                             kind="two_sample", equal_var=False)
    if name == "ttest_paired":
        return compute.ttest(_pick(series, y_name), _pick(series, y2_name),
                             kind="paired")
    if name in ("mann_whitney", "wilcoxon", "ks"):
        return compute.nonparametric(
            _pick(series, y_name), _pick(series, y2_name), name
        )
    if name in ("anova", "kruskal"):
        targets = params.get("targets") or ys
        if len(targets) < 2:
            raise compute.ComputeError("At least two columns with the Y role are required.")
        groups = [_pick(series, t) for t in targets]
        return compute.anova(groups, "kruskal" if name == "kruskal" else "one_way")
    if name == "correlation":
        targets = params.get("targets") or ys or list(series)
        subset = {t: _pick(series, t) for t in targets}
        return compute.correlation(subset, params.get("method", "pearson"))
    if name == "linear_fit":
        return compute.linear_fit(
            _pick(series, x_name), _pick(series, y_name),
            bool(params.get("through_origin", False)),
        )
    if name == "polynomial_fit":
        return compute.polynomial_fit(
            _pick(series, x_name), _pick(series, y_name),
            int(params.get("degree", 2)),
        )
    if name == "nonlinear_fit":
        return compute.nonlinear_fit(
            _pick(series, x_name), _pick(series, y_name),
            params.get("model", "gaussian"), params.get("guess"),
        )
    if name == "interpolate":
        return compute.interpolate_series(
            _pick(series, x_name), _pick(series, y_name),
            params.get("method", "cubic"), int(params.get("points", 200)),
        )
    if name == "smooth":
        return compute.smooth_series(
            _pick(series, y_name), params.get("method", "savgol"),
            int(params.get("window", 11)), int(params.get("order", 3)),
        )
    if name == "fft":
        return compute.fft_analysis(
            _pick(series, y_name), float(params.get("sample_rate", 1.0))
        )
    if name == "filter":
        return compute.digital_filter(
            _pick(series, y_name),
            params.get("kind", "lowpass"), params.get("design", "butter"),
            int(params.get("order", 4)), float(params.get("cutoff", 0.1)),
            float(params.get("cutoff_high", 0.4)),
            float(params.get("sample_rate", 1.0)),
        )
    if name == "peaks":
        return compute.peak_analysis(
            _pick(series, x_name), _pick(series, y_name),
            params.get("prominence"), params.get("height"),
            params.get("distance"), bool(params.get("baseline", True)),
        )
    if name == "differentiate":
        return compute.differentiate(
            _pick(series, x_name), _pick(series, y_name), int(params.get("order", 1))
        )
    if name == "integrate":
        return compute.integrate_series(
            _pick(series, x_name), _pick(series, y_name),
            float(params.get("baseline", 0.0)),
        )
    if name == "histogram":
        return compute.histogram_bins(_pick(series, y_name), params.get("bins", "auto"))
    raise compute.ComputeError("Analisi non riconosciuta: " + str(name))


@router.post("/sheets/{sheet_id}/plot")
def post_plot(sheet_id: str, req: PlotRequest, user: dict = Depends(current_user)):
    if not store.get_sheet(user["user_id"], sheet_id):
        raise HTTPException(status_code=404, detail="Sheet not found.")
    if req.plot_type not in plots.SERVER_PLOTS:
        raise HTTPException(
            status_code=400,
            detail="The requested type is rendered by the client: " + req.plot_type,
        )
    try:
        series = _series(req.columns, req.rows)
        config = dict(req.config or {})
        cols = store.normalize_columns(req.columns)
        if "labels" not in config:
            labels = [c["name"] for c in cols if c.get("role") == "label"]
            if labels:
                idx = [c["name"] for c in cols].index(labels[0])
                config["labels"] = [
                    str(r[idx]) if idx < len(r) else "" for r in req.rows
                ]
        svg = plots.render(req.plot_type, series, config)
    except (compute.ComputeError, store.SheetsError) as exc:
        raise _fail(exc)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise _fail(exc)
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/sheets/{sheet_id}/plots")
def get_plots(sheet_id: str, user: dict = Depends(current_user)):
    if not store.get_sheet(user["user_id"], sheet_id):
        raise HTTPException(status_code=404, detail="Sheet not found.")
    return {"plots": store.list_plots(user["user_id"], sheet_id)}


@router.post("/sheets/{sheet_id}/plots")
def post_saved_plot(
    sheet_id: str, req: SavePlotRequest, user: dict = Depends(current_user)
):
    saved = store.save_plot(
        user["user_id"], sheet_id, req.name, req.plot_type, req.config, req.plot_id
    )
    if not saved:
        raise HTTPException(status_code=404, detail="Sheet not found.")
    return saved


@router.delete("/plots/{plot_id}")
def remove_plot(plot_id: str, user: dict = Depends(current_user)):
    if not store.delete_plot(user["user_id"], plot_id):
        raise HTTPException(status_code=404, detail="Chart not found.")
    return {"ok": True}


@router.post("/sheets/{sheet_id}/import")
async def post_import(
    sheet_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
):
    if not store.get_sheet(user["user_id"], sheet_id):
        raise HTTPException(status_code=404, detail="Sheet not found.")
    filename = (file.filename or "").lower()
    if not (filename.endswith(".csv") or filename.endswith(".tsv")
            or filename.endswith(".txt")):
        raise HTTPException(
            status_code=400,
            detail="Only CSV, TSV or TXT tabular data are accepted.",
        )
    raw = await file.read()
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="File troppo grande.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Codifica non riconosciuta.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if filename.endswith(".tsv") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    table = [row for row in reader if any(str(c).strip() for c in row)]
    if not table:
        raise HTTPException(status_code=400, detail="File privo di dati.")
    header = table[0]
    body = table[1:]
    numeric_header = all(_looks_numeric(c) for c in header if str(c).strip())
    if numeric_header or not body:
        body = table
        header = ["C" + str(i + 1) for i in range(len(table[0]))]
    width = max(len(header), max((len(r) for r in body), default=0))
    columns = []
    for i in range(width):
        name = str(header[i]).strip() if i < len(header) else ""
        sample_col = [r[i] for r in body[:50] if i < len(r) and str(r[i]).strip()]
        is_num = bool(sample_col) and all(_looks_numeric(v) for v in sample_col)
        columns.append(
            {
                "name": name or ("C" + str(i + 1)),
                "role": "x" if i == 0 else ("y" if is_num else "none"),
                "kind": "numeric" if is_num else "text",
                "units": "",
                "comment": "",
                "formula": "",
            }
        )
    rows = [[str(r[i]) if i < len(r) else "" for i in range(width)] for r in body]
    try:
        saved = store.save_sheet(user["user_id"], sheet_id, None, columns, rows)
    except store.SheetsError as exc:
        raise _fail(exc)
    if not saved:
        raise HTTPException(status_code=404, detail="Sheet not found.")
    return saved


def _looks_numeric(value: Any) -> bool:
    s = str(value).strip()
    if not s:
        return False
    s = s.replace(",", ".") if s.count(",") == 1 and "." not in s else s
    try:
        float(s)
        return True
    except ValueError:
        return False


@router.get("/sheets/{sheet_id}/export")
def get_export(sheet_id: str, user: dict = Depends(current_user)):
    sheet = store.get_sheet(user["user_id"], sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Sheet not found.")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c["name"] for c in sheet["columns"]])
    for row in sheet["rows"]:
        writer.writerow(row)
    name = "".join(
        ch for ch in sheet["name"] if ch.isalnum() or ch in ("-", "_")
    ) or "sheet"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="' + name + '.csv"'},
    )

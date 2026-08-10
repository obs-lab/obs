var SHEETS = {
  workbooks: [],
  workbookId: null,
  sheetId: null,
  name: "",
  columns: [],
  rows: [],
  dirty: false,
  activeCell: null,
  catalog: null,
  analyses: null,
  models: [],
  lastResult: null,
  initialized: false
};

var SHEETS_ROLES = [
  ["x", "X"],
  ["y", "Y"],
  ["z", "Z"],
  ["xerr", "Err X"],
  ["yerr", "Err Y"],
  ["zerr", "Err Z"],
  ["label", "Label"],
  ["group", "Group"],
  ["none", "None"]
];

var SHEETS_KINDS = [
  ["numeric", "Numeric"],
  ["text", "Text"],
  ["datetime", "Date and time"]
];

function shAsk(message, value, title) {
  if (typeof obsPrompt === "function") {
    return obsPrompt(message, value, title || shT("tab.sheets", "Sheets"));
  }
  return Promise.resolve(prompt(message, value));
}

function shConfirm(message, okLabel) {
  if (typeof obsConfirm === "function") {
    return obsConfirm(message, shT("tab.sheets", "Sheets"), okLabel);
  }
  return Promise.resolve(confirm(message));
}

function shT(key, fallback) {
  if (typeof t === "function") {
    var v = t(key);
    if (v && v !== key) return v;
  }
  return fallback;
}

function shEsc(s) {
  if (typeof esc === "function") return esc(s);
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function shToast(msg, type) {
  if (typeof toast === "function") { toast(msg, type); return; }
  if (type === "error") console.error(msg); else console.log(msg);
}

function shFail(resp) {
  return resp.json().then(function (d) {
    throw new Error(d && d.detail ? d.detail : shT("sheets.reqError", "Request error"));
  }, function () {
    throw new Error(shT("sheets.reqError", "Request error"));
  });
}

function shJson(url, options) {
  return fetch(url, options).then(function (r) {
    if (!r.ok) return shFail(r);
    return r.json();
  });
}

function initSheetsPanel() {
  if (SHEETS.initialized) {
    shRenderGrid();
    return;
  }
  SHEETS.initialized = true;
  Promise.all([
    shJson("/api/sheets/plot-types"),
    shJson("/api/sheets/analyses")
  ]).then(function (res) {
    SHEETS.catalog = res[0];
    SHEETS.analyses = res[1].analyses;
    SHEETS.models = res[1].models;
    shBuildSelectors();
    return shLoadWorkbooks();
  }).catch(function (e) {
    shToast("Sheets non disponibile: " + e.message, "error");
  });
}

function shLoadWorkbooks() {
  return shJson("/api/sheets/workbooks").then(function (d) {
    SHEETS.workbooks = d.workbooks || [];
    shRenderWorkbookList();
    if (!SHEETS.sheetId && SHEETS.workbooks.length) {
      var wb = SHEETS.workbooks[0];
      if (wb.sheets && wb.sheets.length) shOpenSheet(wb.workbook_id, wb.sheets[0].sheet_id);
    } else if (!SHEETS.workbooks.length) {
      shRenderGrid();
    }
  });
}

function shRenderWorkbookList() {
  var el = document.getElementById("shWorkbooks");
  if (!el) return;
  if (!SHEETS.workbooks.length) {
    el.innerHTML = '<div class="sh-empty">' + shEsc(shT("sheets.nowb", "No workbooks yet.")) + "</div>";
    return;
  }
  var html = "";
  SHEETS.workbooks.forEach(function (wb) {
    var open = wb.workbook_id === SHEETS.workbookId;
    html += '<div class="sh-wb' + (open ? " open" : "") + '">' +
      '<div class="sh-wb-head" onclick="shToggleWorkbook(\'' + wb.workbook_id + '\')">' +
      '<span class="sh-wb-name">' + shEsc(wb.name) + "</span>" +
      '<span class="sh-wb-actions">' +
      '<button class="sh-mini" title="' + t('sheets.newSheet') + '" onclick="event.stopPropagation();shNewSheet(\'' +
      wb.workbook_id + '\')">+</button>' +
      '<button class="sh-mini" title="' + t('sheets.deleteFolder') + '" onclick="event.stopPropagation();shDeleteWorkbook(\'' +
      wb.workbook_id + '\')">x</button>' +
      "</span></div>";
    (wb.sheets || []).forEach(function (s) {
      var active = s.sheet_id === SHEETS.sheetId;
      html += '<div class="sh-sheet' + (active ? " active" : "") +
        '" onclick="shOpenSheet(\'' + wb.workbook_id + "','" + s.sheet_id + '\')">' +
        shEsc(s.name) + "</div>";
    });
    html += "</div>";
  });
  el.innerHTML = html;
}

function shToggleWorkbook(workbookId) {
  var wb = null;
  SHEETS.workbooks.forEach(function (w) { if (w.workbook_id === workbookId) wb = w; });
  if (wb && wb.sheets && wb.sheets.length) shOpenSheet(workbookId, wb.sheets[0].sheet_id);
}

function shNewWorkbook() {
  shAsk(shT("sheets.wbname", "Workbook name"),
        shT("sheets.wbdefault", "Workbook")).then(function (name) {
    if (name === null || name === undefined) return null;
    return shJson("/api/sheets/workbooks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name })
    }).then(function (wb) {
      return shLoadWorkbooks().then(function () {
        if (wb.sheets && wb.sheets.length) {
          shOpenSheet(wb.workbook_id, wb.sheets[0].sheet_id);
        }
      });
    });
  }).catch(function (e) { shToast(e.message, "error"); });
}

function shDeleteWorkbook(workbookId) {
  shConfirm(shT("sheets.delwbask", "Delete this workbook and all its sheets?"),
            shT("sheets.delete", "Delete")).then(function (ok) {
    if (!ok) return null;
    return fetch("/api/sheets/workbooks/" + encodeURIComponent(workbookId),
                 { method: "DELETE" })
      .then(function (r) {
        if (!r.ok) return shFail(r);
        if (SHEETS.workbookId === workbookId) {
          SHEETS.workbookId = null;
          SHEETS.sheetId = null;
          SHEETS.columns = [];
          SHEETS.rows = [];
        }
        return shLoadWorkbooks();
      });
  }).catch(function (e) { shToast(e.message, "error"); });
}

function shNewSheet(workbookId) {
  shAsk(shT("sheets.sheetname", "Sheet name"), "").then(function (name) {
    if (name === null || name === undefined) return null;
    return shJson(
      "/api/sheets/workbooks/" + encodeURIComponent(workbookId) + "/sheets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name })
      }).then(function (created) {
        return shLoadWorkbooks().then(function () {
          shOpenSheet(workbookId, created.sheet_id);
        });
      });
  }).catch(function (e) { shToast(e.message, "error"); });
}

function shDeleteSheet() {
  if (!SHEETS.sheetId) return;
  var target = SHEETS.sheetId;
  shConfirm(shT("sheets.delsheetask", "Delete the current sheet?"),
            shT("sheets.delete", "Delete")).then(function (ok) {
    if (!ok) return null;
    return fetch("/api/sheets/sheets/" + encodeURIComponent(target),
                 { method: "DELETE" })
      .then(function (r) {
        if (!r.ok) return shFail(r);
        SHEETS.sheetId = null;
        SHEETS.columns = [];
        SHEETS.rows = [];
        return shLoadWorkbooks();
      });
  }).catch(function (e) { shToast(e.message, "error"); });
}

function shOpenSheet(workbookId, sheetId) {
  if (SHEETS.dirty && SHEETS.sheetId && SHEETS.sheetId !== sheetId) {
    shConfirm(shT("sheets.unsavedask", "There are unsaved changes. Continue without saving?"),
              shT("sheets.continue", "Continue")).then(function (ok) {
      if (!ok) return;
      SHEETS.dirty = false;
      shOpenSheet(workbookId, sheetId);
    });
    return;
  }
  shJson("/api/sheets/sheets/" + encodeURIComponent(sheetId)).then(function (sheet) {
    SHEETS.workbookId = workbookId;
    SHEETS.sheetId = sheet.sheet_id;
    SHEETS.name = sheet.name;
    SHEETS.columns = sheet.columns;
    SHEETS.rows = sheet.rows;
    SHEETS.dirty = false;
    shRenderWorkbookList();
    shRenderGrid();
    shBuildSelectors();
  }).catch(function (e) { shToast(e.message, "error"); });
}

function shSaveSheet() {
  if (!SHEETS.sheetId) { shToast(shT("sheets.noSheetOpen", "No sheet open"), "error"); return; }
  shJson("/api/sheets/sheets/" + encodeURIComponent(SHEETS.sheetId), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: SHEETS.name,
      columns: SHEETS.columns,
      rows: SHEETS.rows
    })
  }).then(function (saved) {
    SHEETS.columns = saved.columns;
    SHEETS.rows = saved.rows;
    SHEETS.dirty = false;
    shUpdateStatus(shT("sheets.saved", "Saved"));
    shRenderWorkbookList();
  }).catch(function (e) { shToast(e.message, "error"); });
}

function shUpdateStatus(text) {
  var el = document.getElementById("shStatus");
  if (el) el.textContent = text || (SHEETS.dirty ? shT("sheets.unsaved", "Unsaved changes") : shT("sheets.ready", "Ready"));
}

function shMarkDirty() {
  SHEETS.dirty = true;
  shUpdateStatus();
}

function shRenderGrid() {
  var el = document.getElementById("shGrid");
  if (!el) return;
  if (!SHEETS.sheetId) {
    el.innerHTML = '<div class="sh-empty">' + shEsc(shT("sheets.nosheet", "Open or create a sheet to begin.")) + "</div>";
    return;
  }
  var cols = SHEETS.columns;
  var html = '<table class="sh-table"><thead>';
  html += '<tr class="sh-hrow"><th class="sh-corner"></th>';
  cols.forEach(function (c, i) {
    html += '<th class="sh-colhead"><input class="sh-cname" value="' + shEsc(c.name) +
      '" onchange="shSetColName(' + i + ',this.value)" title="' + t('sheets.columnName') + '"></th>';
  });
  html += '<th class="sh-addcol"><button class="sh-mini" onclick="shAddColumn()">+</button></th></tr>';
  html += '<tr class="sh-hrow"><th class="sh-corner">' +
    shEsc(shT("sheets.role", "role")) + '</th>';
  cols.forEach(function (c, i) {
    html += '<th class="sh-colhead"><select class="sh-crole" onchange="shSetColRole(' + i + ',this.value)">';
    SHEETS_ROLES.forEach(function (r) {
      html += '<option value="' + r[0] + '"' + (c.role === r[0] ? " selected" : "") +
        ">" + shEsc(shT("sheets.role." + r[0], r[1])) + "</option>";
    });
    html += "</select></th>";
  });
  html += "<th></th></tr>";
  html += '<tr class="sh-hrow"><th class="sh-corner">' +
    shEsc(shT("sheets.kind", "type")) + '</th>';
  cols.forEach(function (c, i) {
    html += '<th class="sh-colhead"><select class="sh-ckind" onchange="shSetColKind(' + i + ',this.value)">';
    SHEETS_KINDS.forEach(function (k) {
      html += '<option value="' + k[0] + '"' + (c.kind === k[0] ? " selected" : "") +
        ">" + shEsc(shT("sheets.kind." + k[0], k[1])) + "</option>";
    });
    html += "</select></th>";
  });
  html += "<th></th></tr>";
  html += '<tr class="sh-hrow"><th class="sh-corner">' +
    shEsc(shT("sheets.units", "units")) + '</th>';
  cols.forEach(function (c, i) {
    html += '<th class="sh-colhead"><input class="sh-cunit" value="' + shEsc(c.units || "") +
      '" onchange="shSetColUnits(' + i + ',this.value)" placeholder="' + t('sheets.units') + '"></th>';
  });
  html += '<th></th></tr></thead><tbody>';
  SHEETS.rows.forEach(function (row, r) {
    html += '<tr><td class="sh-rownum">' + (r + 1) + "</td>";
    cols.forEach(function (c, i) {
      var v = row[i] === undefined ? "" : row[i];
      html += '<td class="sh-cell"><input value="' + shEsc(v) +
        '" data-r="' + r + '" data-c="' + i +
        '" onchange="shSetCell(' + r + "," + i + ',this.value)" onkeydown="shCellKey(event,' +
        r + "," + i + ')"></td>';
    });
    html += '<td class="sh-cell"><button class="sh-mini" title="' + t('sheets.deleteRow') + '" onclick="shDeleteRow(' +
      r + ')">x</button></td></tr>';
  });
  html += "</tbody></table>";
  html += '<div class="sh-gridfoot"><button class="qbtn" onclick="shAddRows(10)">' +
    shEsc(shT("sheets.addrows10", "Add 10 rows")) + '</button>' +
    '<button class="qbtn" onclick="shAddRows(100)">' +
    shEsc(shT("sheets.addrows100", "Add 100 rows")) + '</button>' +
    '<span class="sh-dims">' + SHEETS.rows.length + " " +
    shT("sheets.rows", "rows") + ", " + cols.length + " " +
    shT("sheets.cols", "columns") + "</span></div>";
  el.innerHTML = html;
  shUpdateStatus();
}

function shSetCell(r, c, value) {
  if (!SHEETS.rows[r]) return;
  SHEETS.rows[r][c] = value;
  shMarkDirty();
}

function shCellKey(ev, r, c) {
  var next = null;
  if (ev.key === "Enter" || ev.key === "ArrowDown") next = [r + 1, c];
  else if (ev.key === "ArrowUp") next = [r - 1, c];
  else if (ev.key === "Tab") return;
  else return;
  ev.preventDefault();
  if (next[0] < 0) return;
  if (next[0] >= SHEETS.rows.length) shAddRows(1);
  var sel = document.querySelector(
    '#shGrid input[data-r="' + next[0] + '"][data-c="' + next[1] + '"]');
  if (sel) { sel.focus(); sel.select(); }
}

function shSetColName(i, value) {
  SHEETS.columns[i].name = value;
  shMarkDirty();
  shBuildSelectors();
}

function shSetColRole(i, value) {
  SHEETS.columns[i].role = value;
  shMarkDirty();
  shBuildSelectors();
}

function shSetColKind(i, value) {
  SHEETS.columns[i].kind = value;
  shMarkDirty();
}

function shSetColUnits(i, value) {
  SHEETS.columns[i].units = value;
  shMarkDirty();
}

function shAddColumn() {
  var n = SHEETS.columns.length + 1;
  SHEETS.columns.push({
    name: "C" + n, role: "y", kind: "numeric", units: "", comment: "", formula: ""
  });
  SHEETS.rows.forEach(function (r) { r.push(""); });
  shMarkDirty();
  shRenderGrid();
  shBuildSelectors();
}

function shAddRows(n) {
  var width = SHEETS.columns.length;
  for (var i = 0; i < n; i++) {
    var row = [];
    for (var j = 0; j < width; j++) row.push("");
    SHEETS.rows.push(row);
  }
  shMarkDirty();
  shRenderGrid();
}

function shDeleteRow(r) {
  SHEETS.rows.splice(r, 1);
  shMarkDirty();
  shRenderGrid();
}

function shColumnNames() {
  return SHEETS.columns.map(function (c) { return c.name; });
}

function shFillSelect(id, names, preferredRole) {
  var el = document.getElementById(id);
  if (!el) return;
  var current = el.value;
  var html = '<option value="">' + shEsc(shT("sheets.auto", "automatic")) + '</option>';
  names.forEach(function (n) { html += '<option value="' + shEsc(n) + '">' + shEsc(n) + "</option>"; });
  el.innerHTML = html;
  if (current && names.indexOf(current) >= 0) el.value = current;
  else if (preferredRole) {
    for (var i = 0; i < SHEETS.columns.length; i++) {
      if (SHEETS.columns[i].role === preferredRole) { el.value = SHEETS.columns[i].name; break; }
    }
  }
}

function shBuildSelectors() {
  var names = shColumnNames();
  shFillSelect("shAnX", names, "x");
  shFillSelect("shAnY", names, "y");
  shFillSelect("shAnY2", names, null);
  shFillSelect("shPlotX", names, "x");
  shFillSelect("shPlotY", names, "y");

  var an = document.getElementById("shAnalysis");
  if (an && SHEETS.analyses && !an.dataset.filled) {
    var html = "";
    SHEETS.analyses.forEach(function (a) {
      html += '<option value="' + a.id + '">' + shEsc(a.label) + "</option>";
    });
    an.innerHTML = html;
    an.dataset.filled = "1";
  }
  var md = document.getElementById("shModel");
  if (md && SHEETS.models && !md.dataset.filled) {
    var mh = "";
    SHEETS.models.forEach(function (m) {
      mh += '<option value="' + m.id + '">' + shEsc(m.id) + "</option>";
    });
    md.innerHTML = mh;
    md.dataset.filled = "1";
  }
  var pt = document.getElementById("shPlotType");
  if (pt && SHEETS.catalog && !pt.dataset.filled) {
    var ph = '<optgroup label="' + t('sheets.interactive') + '">';
    SHEETS.catalog.client.forEach(function (p) {
      ph += '<option value="c:' + p.id + '">' + shEsc(p.label) + "</option>";
    });
    ph += '</optgroup><optgroup label="' + t('sheets.specialized') + '">';
    SHEETS.catalog.server.forEach(function (p) {
      ph += '<option value="s:' + p.id + '">' + shEsc(p.label) + "</option>";
    });
    ph += "</optgroup>";
    pt.innerHTML = ph;
    pt.dataset.filled = "1";
  }
}

function shAnalysisParams() {
  var p = {};
  var x = document.getElementById("shAnX");
  var y = document.getElementById("shAnY");
  var y2 = document.getElementById("shAnY2");
  if (x && x.value) p.x = x.value;
  if (y && y.value) p.y = y.value;
  if (y2 && y2.value) p.y2 = y2.value;
  var kind = document.getElementById("shAnalysis");
  var name = kind ? kind.value : "";
  if (name === "polynomial_fit") {
    p.degree = parseInt(document.getElementById("shDegree").value || "2", 10);
  }
  if (name === "nonlinear_fit") {
    p.model = document.getElementById("shModel").value || "gaussian";
  }
  if (name === "fft" || name === "filter") {
    p.sample_rate = parseFloat(document.getElementById("shRate").value || "1") || 1;
  }
  if (name === "filter") {
    p.kind = document.getElementById("shFilterKind").value || "lowpass";
    p.design = document.getElementById("shFilterDesign").value || "butter";
    p.cutoff = parseFloat(document.getElementById("shCutoff").value || "0.1") || 0.1;
  }
  if (name === "smooth") {
    p.method = document.getElementById("shSmoothMethod").value || "savgol";
    p.window = parseInt(document.getElementById("shWindow").value || "11", 10);
  }
  if (name === "interpolate") {
    p.method = document.getElementById("shInterpMethod").value || "cubic";
  }
  if (name === "anova" || name === "kruskal" || name === "correlation" ||
      name === "descriptive") {
    var picked = [];
    SHEETS.columns.forEach(function (c) {
      if (c.role === "y") picked.push(c.name);
    });
    if (picked.length) p.targets = picked;
  }
  return p;
}

function shShowAnalysisOptions() {
  var name = document.getElementById("shAnalysis").value;
  var map = {
    shDegreeWrap: ["polynomial_fit"],
    shModelWrap: ["nonlinear_fit"],
    shRateWrap: ["fft", "filter"],
    shFilterWrap: ["filter"],
    shSmoothWrap: ["smooth"],
    shInterpWrap: ["interpolate"],
    shY2Wrap: ["ttest_two", "welch", "ttest_paired", "mann_whitney", "wilcoxon", "ks"]
  };
  Object.keys(map).forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.style.display = map[id].indexOf(name) >= 0 ? "flex" : "none";
  });
}

function shRunAnalysis() {
  if (!SHEETS.sheetId) { shToast(shT("sheets.noSheetOpen", "No sheet open"), "error"); return; }
  var name = document.getElementById("shAnalysis").value;
  var out = document.getElementById("shResult");
  out.innerHTML = '<div class="sh-empty">' + shEsc(shT("sheets.computing", "Computing.")) + "</div>";
  shJson("/api/sheets/sheets/" + encodeURIComponent(SHEETS.sheetId) + "/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      analysis: name,
      columns: SHEETS.columns,
      rows: SHEETS.rows,
      params: shAnalysisParams()
    })
  }).then(function (d) {
    SHEETS.lastResult = d;
    shRenderResult(d);
  }).catch(function (e) {
    out.innerHTML = '<div class="sh-error">' + shEsc(e.message) + "</div>";
  });
}

function shNum(v) {
  if (v === null || v === undefined) return "-";
  if (typeof v !== "number") return shEsc(v);
  if (!isFinite(v)) return "-";
  var a = Math.abs(v);
  if (a !== 0 && (a < 0.001 || a >= 1e6)) return v.toExponential(4);
  return String(Math.round(v * 1e6) / 1e6);
}

function shRenderResult(d) {
  var out = document.getElementById("shResult");
  var r = d.result || {};
  var html = '<div class="sh-rhead">' +
    shEsc(shT("sheets.an." + d.analysis, d.label || d.analysis)) + "</div>";
  if (r.columns) {
    var names = Object.keys(r.columns);
    var keys = names.length ? Object.keys(r.columns[names[0]]) : [];
    html += '<table class="sh-rtable"><tr><th>' +
      shEsc(shT("sheets.statistic", "statistic")) + '</th>';
    names.forEach(function (n) { html += "<th>" + shEsc(n) + "</th>"; });
    html += "</tr>";
    keys.forEach(function (k) {
      html += "<tr><td>" + shEsc(k) + "</td>";
      names.forEach(function (n) { html += "<td>" + shNum(r.columns[n][k]) + "</td>"; });
      html += "</tr>";
    });
    html += "</table>";
  } else if (r.matrix) {
    html += '<table class="sh-rtable"><tr><th></th>';
    r.names.forEach(function (n) { html += "<th>" + shEsc(n) + "</th>"; });
    html += "</tr>";
    r.names.forEach(function (n, i) {
      html += "<tr><td>" + shEsc(n) + "</td>";
      r.names.forEach(function (m, j) { html += "<td>" + shNum(r.matrix[i][j]) + "</td>"; });
      html += "</tr>";
    });
    html += "</table>";
  } else if (r.peaks) {
    html += '<div class="sh-rline">' + shEsc(shT("sheets.peaksfound", "Peaks found")) +
      ": " + r.count + "</div>";
    if (r.count) {
      html += '<table class="sh-rtable"><tr><th>n</th><th>' +
        shEsc(shT("sheets.center", "center")) + '</th><th>' +
        shEsc(shT("sheets.height", "height")) + '</th>' +
        "<th>FWHM</th><th>" + shEsc(shT("sheets.area", "area")) +
        "</th><th>" + shEsc(shT("sheets.area", "area")) + " %</th></tr>";
      r.peaks.forEach(function (p, i) {
        html += "<tr><td>" + (i + 1) + "</td><td>" + shNum(p.center) + "</td><td>" +
          shNum(p.height) + "</td><td>" + shNum(p.fwhm) + "</td><td>" +
          shNum(p.area) + "</td><td>" + shNum(p.area_percent) + "</td></tr>";
      });
      html += "</table>";
    }
  } else if (r.parameter_names) {
    html += '<table class="sh-rtable"><tr><th>' +
      shEsc(shT("sheets.parameter", "parameter")) + '</th><th>' +
      shEsc(shT("sheets.value", "value")) + '</th><th>' +
      shEsc(shT("sheets.error", "error")) + "</th></tr>";
    r.parameter_names.forEach(function (n, i) {
      html += "<tr><td>" + shEsc(n) + "</td><td>" + shNum(r.parameters[i]) +
        "</td><td>" + shNum((r.std_errors || [])[i]) + "</td></tr>";
    });
    html += "</table>";
    html += '<div class="sh-rline">' + shEsc(shT("sheets.rsquared", "R squared")) +
      ": " + shNum(r.r_squared) + "</div>";
  } else {
    html += '<table class="sh-rtable">';
    Object.keys(r).forEach(function (k) {
      var v = r[k];
      if (Array.isArray(v) && v.length > 12) {
        html += "<tr><td>" + shEsc(k) + "</td><td>serie di " + v.length + " valori</td></tr>";
      } else if (v !== null && typeof v === "object") {
        Object.keys(v).forEach(function (k2) {
          var inner = v[k2];
          if (Array.isArray(inner)) inner = inner.map(shNum).join(", ");
          else inner = shNum(inner);
          html += "<tr><td>" + shEsc(k + "." + k2) + "</td><td>" + inner + "</td></tr>";
        });
      } else {
        html += "<tr><td>" + shEsc(k) + "</td><td>" + shNum(v) + "</td></tr>";
      }
    });
    html += "</table>";
  }
  html += '<div class="sh-ractions">' +
    '<button class="qbtn" onclick="shResultToColumns()">' +
    shEsc(shT("sheets.tocolumns", "Send to sheet")) + "</button></div>";
  out.innerHTML = html;
  shPlotResultOverlay(d);
}

function shPlotResultOverlay(d) {
  var r = d.result || {};
  if (!r.fit_x && !r.x) return;
  var el = document.getElementById("shChart");
  if (!el || typeof Plotly === "undefined") return;
  var traces = [];
  var series = shNumericSeries();
  var xName = (shAnalysisParams().x) || shFirstRole("x");
  var yName = (shAnalysisParams().y) || shFirstRole("y");
  if (xName && yName && series[xName] && series[yName]) {
    traces.push({
      x: series[xName], y: series[yName], mode: "markers", type: "scatter",
      name: yName, marker: { size: 6, color: "#3d5a80" }
    });
  }
  if (r.fit_x && r.fit_y) {
    traces.push({
      x: r.fit_x, y: r.fit_y, mode: "lines", type: "scatter",
      name: "adattamento", line: { color: "#98544d", width: 2 }
    });
  } else if (r.x && r.y) {
    traces.push({
      x: r.x, y: r.y, mode: "lines", type: "scatter",
      name: d.analysis, line: { color: "#98544d", width: 2 }
    });
  } else if (r.x && r.corrected) {
    traces.push({
      x: r.x, y: r.corrected, mode: "lines", type: "scatter",
      name: "corretto", line: { color: "#98544d", width: 2 }
    });
  }
  if (!traces.length) return;
  Plotly.newPlot(el, traces, shLayout(xName || "", yName || ""),
    { responsive: true, displaylogo: false });
}

function shFirstRole(role) {
  for (var i = 0; i < SHEETS.columns.length; i++) {
    if (SHEETS.columns[i].role === role) return SHEETS.columns[i].name;
  }
  return null;
}

function shNumericSeries() {
  var out = {};
  SHEETS.columns.forEach(function (c, i) {
    if (c.kind === "text") return;
    var vals = SHEETS.rows.map(function (r) {
      var raw = (r[i] === undefined || r[i] === null) ? "" : String(r[i]).trim();
      if (!raw) return null;
      if (raw.indexOf(",") >= 0 && raw.indexOf(".") < 0) raw = raw.replace(",", ".");
      var v = parseFloat(raw);
      return isNaN(v) ? null : v;
    });
    out[c.name] = vals;
  });
  return out;
}

function shTextSeries(name) {
  var idx = shColumnNames().indexOf(name);
  if (idx < 0) return [];
  return SHEETS.rows.map(function (r) { return r[idx] === undefined ? "" : String(r[idx]); });
}

function shResultToColumns() {
  var d = SHEETS.lastResult;
  if (!d) return;
  var r = d.result || {};
  var added = 0;
  ["y", "cumulative", "corrected", "amplitude", "residuals"].forEach(function (key) {
    if (!Array.isArray(r[key])) return;
    if (r[key].length !== SHEETS.rows.length) return;
    SHEETS.columns.push({
      name: d.analysis + "_" + key, role: "y", kind: "numeric",
      units: "", comment: "", formula: ""
    });
    var ci = SHEETS.columns.length - 1;
    SHEETS.rows.forEach(function (row, i) { row[ci] = String(r[key][i]); });
    added++;
  });
  if (!added) {
    shToast(shT("sheets.noCompatSeries", "No series with a length compatible with the sheet"), "error");
    return;
  }
  shMarkDirty();
  shRenderGrid();
  shBuildSelectors();
}

function shLayout(xTitle, yTitle) {
  return {
    margin: { l: 60, r: 24, t: 30, b: 52 },
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    font: { family: "inherit", size: 11, color: "#333333" },
    xaxis: { title: { text: xTitle, font: { size: 11 } }, gridcolor: "#e2e2e2",
             zerolinecolor: "#cccccc" },
    yaxis: { title: { text: yTitle, font: { size: 11 } }, gridcolor: "#e2e2e2",
             zerolinecolor: "#cccccc" },
    showlegend: true,
    legend: { orientation: "h", y: -0.2 }
  };
}

function shAxisLabel(name) {
  for (var i = 0; i < SHEETS.columns.length; i++) {
    if (SHEETS.columns[i].name === name) {
      var u = SHEETS.columns[i].units;
      return u ? name + " (" + u + ")" : name;
    }
  }
  return name || "";
}

function shDrawPlot() {
  if (!SHEETS.sheetId) { shToast(shT("sheets.noSheetOpen", "No sheet open"), "error"); return; }
  var raw = document.getElementById("shPlotType").value || "c:line";
  var parts = raw.split(":");
  if (parts[0] === "s") { shDrawServerPlot(parts[1]); return; }
  shDrawClientPlot(parts[1]);
}

function shDrawServerPlot(kind) {
  var el = document.getElementById("shChart");
  el.innerHTML = '<div class="sh-empty">' + shEsc(shT("sheets.generating", "Rendering.")) + "</div>";
  var config = {};
  var xs = document.getElementById("shPlotX").value;
  var ys = document.getElementById("shPlotY").value;
  if (xs) config.x = xs;
  if (ys) config.y = ys;
  var comps = [];
  SHEETS.columns.forEach(function (c) {
    if (c.role === "y" || c.role === "x") comps.push(c.name);
  });
  if (kind === "ternary") config.components = comps.slice(0, 3);
  if (kind === "radar") config.values = comps;
  if (kind === "forest") {
    var errName = shFirstRole("yerr");
    if (errName) config.error = errName;
  }
  if (kind === "wind_rose") {
    config.direction = xs || shFirstRole("x");
    config.speed = ys || shFirstRole("y");
  }
  fetch("/api/sheets/sheets/" + encodeURIComponent(SHEETS.sheetId) + "/plot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plot_type: kind, columns: SHEETS.columns, rows: SHEETS.rows, config: config
    })
  }).then(function (r) {
    if (!r.ok) return shFail(r);
    return r.text();
  }).then(function (svg) {
    el.innerHTML = '<div class="sh-svg">' + svg + "</div>";
  }).catch(function (e) {
    el.innerHTML = '<div class="sh-error">' + shEsc(e.message) + "</div>";
  });
}

function shDrawClientPlot(kind) {
  var el = document.getElementById("shChart");
  if (typeof Plotly === "undefined") {
    el.innerHTML = '<div class="sh-error">Plotly non disponibile.</div>';
    return;
  }
  var series = shNumericSeries();
  var xSel = document.getElementById("shPlotX").value || shFirstRole("x");
  var ySel = document.getElementById("shPlotY").value;
  var yNames = [];
  if (ySel) yNames = [ySel];
  else SHEETS.columns.forEach(function (c) { if (c.role === "y") yNames.push(c.name); });
  if (!yNames.length) {
    el.innerHTML = '<div class="sh-error">' + shEsc(shT("sheets.assignY", "Assign the Y role to at least one column.")) + '</div>';
    return;
  }
  var xVals = xSel && series[xSel] ? series[xSel] : null;
  var xErr = shFirstRole("xerr");
  var yErr = shFirstRole("yerr");
  var labelCol = shFirstRole("label");
  var groupCol = shFirstRole("group");
  var traces = [];
  var layout = shLayout(shAxisLabel(xSel), shAxisLabel(yNames[0]));

  function errObj(name) {
    if (!name || !series[name]) return undefined;
    return { type: "data", array: series[name], visible: true, color: "#888888",
             thickness: 1, width: 3 };
  }

  if (kind === "pie" || kind === "doughnut") {
    var labels = labelCol ? shTextSeries(labelCol)
      : (xVals ? xVals.map(String) : yNames);
    traces.push({
      type: "pie", labels: labels, values: series[yNames[0]],
      hole: kind === "doughnut" ? 0.45 : 0,
      marker: { colors: ["#3d5a80", "#98544d", "#5c6b73", "#2f4858",
                         "#7a6a4f", "#6b7a80", "#455a64", "#57708c"] }
    });
    delete layout.xaxis;
    delete layout.yaxis;
  } else if (kind === "histogram") {
    yNames.forEach(function (n, i) {
      traces.push({ type: "histogram", x: series[n], name: n, opacity: 0.75,
                    marker: { color: shColor(i) } });
    });
    layout.barmode = "overlay";
    layout.xaxis.title.text = shAxisLabel(yNames[0]);
    layout.yaxis.title.text = "conteggio";
  } else if (kind === "box") {
    yNames.forEach(function (n, i) {
      traces.push({ type: "box", y: series[n], name: n, boxpoints: "outliers",
                    marker: { color: shColor(i) } });
    });
    layout.xaxis.title.text = "";
  } else if (kind === "violin") {
    yNames.forEach(function (n, i) {
      traces.push({ type: "violin", y: series[n], name: n, box: { visible: true },
                    meanline: { visible: true }, line: { color: shColor(i) } });
    });
    layout.xaxis.title.text = "";
  } else if (kind === "heatmap" || kind === "contour" || kind === "surface3d") {
    var matNames = shMatrixColumns(ySel);
    if (matNames.length < 2) {
      el.innerHTML = '<div class="sh-error">' +
        shEsc(shT("sheets.needmatrix",
          "This chart needs at least two Y columns. Set Y on the data columns and leave the Y selector on automatic.")) +
        "</div>";
      return;
    }
    var zmat = shTranspose(matNames, series);
    var scale = shColorscale();
    if (kind === "surface3d") {
      traces.push({
        type: "surface", z: zmat, colorscale: scale,
        contours: { z: { show: true, usecolormap: true, project: { z: true } } }
      });
      layout.scene = {
        xaxis: { title: { text: shAxisLabel(matNames[0] ? "Y" : "Y") } },
        yaxis: { title: { text: shAxisLabel(xSel) || "X" } },
        zaxis: { title: { text: "Z" } },
        camera: { eye: { x: 1.5, y: 1.5, z: 0.9 } }
      };
      delete layout.xaxis;
      delete layout.yaxis;
    } else {
      traces.push({
        type: kind === "contour" ? "contour" : "heatmap",
        z: zmat, y: xVals || undefined, colorscale: scale,
        contours: kind === "contour"
          ? { coloring: "fill", showlines: true } : undefined
      });
      layout.xaxis.title.text = "";
      layout.yaxis.title.text = shAxisLabel(xSel);
    }
  } else if (kind === "scatter3d") {
    var zName = shFirstRole("z") || yNames[1] || yNames[0];
    traces.push({
      type: "scatter3d", mode: "markers", x: xVals, y: series[yNames[0]],
      z: series[zName], marker: { size: 4, color: "#3d5a80" }, name: yNames[0]
    });
    layout.scene = { xaxis: { title: shAxisLabel(xSel) },
                     yaxis: { title: shAxisLabel(yNames[0]) },
                     zaxis: { title: shAxisLabel(zName) } };
  } else if (kind === "polar") {
    yNames.forEach(function (n, i) {
      traces.push({
        type: "scatterpolar", r: series[n],
        theta: xVals || series[n].map(function (v, k) { return k * 360 / series[n].length; }),
        mode: "lines+markers", name: n, line: { color: shColor(i) }
      });
    });
    layout.polar = { radialaxis: { visible: true } };
    delete layout.xaxis;
    delete layout.yaxis;
  } else if (kind === "bubble") {
    var sizeName = yNames[1] || yNames[0];
    traces.push({
      type: "scatter", mode: "markers", x: xVals, y: series[yNames[0]],
      marker: {
        size: series[sizeName], sizemode: "area", color: "#3d5a80",
        sizeref: 2.0 * Math.max.apply(null, series[sizeName].filter(function (v) {
          return v !== null;
        })) / (40 * 40), opacity: 0.75
      },
      name: yNames[0], text: labelCol ? shTextSeries(labelCol) : undefined
    });
  } else {
    var barmode = null;
    if (kind === "column_stacked" || kind === "area_stacked") barmode = "stack";
    if (kind === "column_grouped") barmode = "group";
    yNames.forEach(function (n, i) {
      var t = {
        name: n, x: xVals || undefined, y: series[n],
        text: labelCol ? shTextSeries(labelCol) : undefined
      };
      if (kind === "column" || kind === "column_stacked" || kind === "column_grouped") {
        t.type = "bar";
        t.marker = { color: shColor(i) };
      } else if (kind === "bar") {
        t.type = "bar";
        t.orientation = "h";
        t.x = series[n];
        t.y = xVals || undefined;
        t.marker = { color: shColor(i) };
      } else if (kind === "area" || kind === "area_stacked") {
        t.type = "scatter";
        t.mode = "lines";
        t.fill = kind === "area_stacked" ? "tonexty" : "tozeroy";
        t.line = { color: shColor(i), width: 1.6 };
        if (kind === "area_stacked") t.stackgroup = "one";
      } else if (kind === "scatter") {
        t.type = "scatter";
        t.mode = "markers";
        t.marker = { size: 7, color: shColor(i) };
      } else if (kind === "line_symbol") {
        t.type = "scatter";
        t.mode = "lines+markers";
        t.marker = { size: 6, color: shColor(i) };
        t.line = { color: shColor(i), width: 1.6 };
      } else {
        t.type = "scatter";
        t.mode = "lines";
        t.line = { color: shColor(i), width: 1.8 };
      }
      if (i === 0) {
        if (yErr) t.error_y = errObj(yErr);
        if (xErr) t.error_x = errObj(xErr);
      }
      traces.push(t);
    });
    if (barmode) layout.barmode = barmode;
    if (kind === "bar") {
      layout.xaxis.title.text = shAxisLabel(yNames[0]);
      layout.yaxis.title.text = shAxisLabel(xSel);
    }
  }
  if (groupCol) layout.title = { text: "", font: { size: 12 } };
  el.innerHTML = "";
  Plotly.newPlot(el, traces, layout, { responsive: true, displaylogo: false })
    .then(function () { Plotly.Plots.resize(el); });
}

function shMatrixColumns(ySel) {
  var names = [];
  SHEETS.columns.forEach(function (c) {
    if (c.role === "y" || c.role === "z") names.push(c.name);
  });
  if (names.length >= 2) return names;
  if (ySel) return [ySel];
  return names;
}

function shTranspose(names, series) {
  var nrows = SHEETS.rows.length;
  var out = [];
  for (var r = 0; r < nrows; r++) {
    var row = [];
    for (var c = 0; c < names.length; c++) {
      var col = series[names[c]];
      var v = col ? col[r] : null;
      row.push(v === undefined ? null : v);
    }
    out.push(row);
  }
  return out;
}

function shColorscale() {
  var el = document.getElementById("shPalette");
  var name = el && el.value ? el.value : "Turbo";
  if (name === "Viridis") return "Viridis";
  if (name === "Cividis") return "Cividis";
  if (name === "Portland") return "Portland";
  if (name === "YlGnBu") return "YlGnBu";
  return SH_TURBO;
}

var SH_TURBO = [
  [0.0, "#30123b"], [0.07, "#4145ab"], [0.13, "#4675ed"],
  [0.20, "#39a2fc"], [0.27, "#1bcfd4"], [0.34, "#24eca6"],
  [0.41, "#61fc6c"], [0.47, "#a4fc3b"], [0.54, "#d1e834"],
  [0.61, "#f3c63a"], [0.68, "#fe9b2d"], [0.75, "#f36315"],
  [0.82, "#d93806"], [0.89, "#b11901"], [1.0, "#7a0403"]
];

function shColor(i) {
  var p = ["#3d5a80", "#98544d", "#5c6b73", "#2f4858",
           "#7a6a4f", "#6b7a80", "#455a64", "#57708c"];
  return p[i % p.length];
}

function shApplyFormula() {
  if (!SHEETS.sheetId) return;
  var expr = document.getElementById("shFormula").value;
  var target = document.getElementById("shFormulaTarget").value;
  if (!expr.trim()) { shToast("Formula vuota", "error"); return; }
  if (SHEETS.dirty) {
    shToast(shT("sheets.saveBeforeFormula", "Save the sheet before applying a formula"), "error");
    return;
  }
  shJson("/api/sheets/sheets/" + encodeURIComponent(SHEETS.sheetId) + "/formula", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expression: expr, target: target })
  }).then(function (d) {
    var name = (target || "").trim() || "F" + (SHEETS.columns.length + 1);
    var idx = shColumnNames().indexOf(name);
    if (idx < 0) {
      SHEETS.columns.push({
        name: name, role: "y", kind: "numeric", units: "", comment: "", formula: expr
      });
      SHEETS.rows.forEach(function (r) { r.push(""); });
      idx = SHEETS.columns.length - 1;
    } else {
      SHEETS.columns[idx].formula = expr;
    }
    SHEETS.rows.forEach(function (r, i) {
      var v = d.values[i];
      r[idx] = (v === null || v === undefined) ? "" : String(v);
    });
    shMarkDirty();
    shRenderGrid();
    shBuildSelectors();
  }).catch(function (e) { shToast(e.message, "error"); });
}

function shImportFile(input) {
  if (!SHEETS.sheetId) { shToast(shT("sheets.openBeforeImport", "Open a sheet before importing"), "error"); return; }
  if (!input.files || !input.files.length) return;
  var fd = new FormData();
  fd.append("file", input.files[0]);
  shJson("/api/sheets/sheets/" + encodeURIComponent(SHEETS.sheetId) + "/import", {
    method: "POST", body: fd
  }).then(function (saved) {
    SHEETS.columns = saved.columns;
    SHEETS.rows = saved.rows;
    SHEETS.dirty = false;
    shRenderGrid();
    shBuildSelectors();
    shUpdateStatus(shT("sheets.imported", "Data imported"));
  }).catch(function (e) { shToast(e.message, "error"); })
    .then(function () { input.value = ""; });
}

function shExportCsv() {
  if (!SHEETS.sheetId) return;
  window.location = "/api/sheets/sheets/" + encodeURIComponent(SHEETS.sheetId) + "/export";
}

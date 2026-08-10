var OBS_CODE = {
  editor: null,
  monacoReady: false,
  language: "python",
  scriptId: null,
  scriptName: "",
  status: null,
  pollTimer: null,
  webTimer: null,
  toastTimer: null,
  touched: false,
  outHeight: 220,
  plotsOpen: false,
  plots: [],
  specs: [],
  files: [],
  openFile: null,
  fileFilter: "",
  scriptFilter: "",
  scriptsAll: [],
  lastUsage: null
};

var OBS_CODE_MONACO_LANG = {
  python: "python",
  javascript: "javascript",
  java: "java",
  c: "c",
  cpp: "cpp",
  octave: "plaintext",
  r: "r",
  html: "html",
  css: "css",
  web: "html"
};

var OBS_CODE_BROWSER = ["html", "css", "web"];

function obsCodeIsBrowser(lang) {
  return OBS_CODE_BROWSER.indexOf(lang) !== -1;
}

function obsCodeCanManage() {
  if (!window.OBS_AUTH || !OBS_AUTH.user) return false;
  var r = OBS_AUTH.user.role;
  return r === "developer" || r === "admin";
}

function obsCodeT(key) {
  return (typeof t === "function") ? t(key) : key;
}

function obsCodeEsc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function obsCodeSize(bytes) {
  if (!bytes) return "";
  var mb = bytes / (1024 * 1024);
  if (mb >= 1024) return (mb / 1024).toFixed(2) + " GB";
  return mb.toFixed(0) + " MB";
}

function initCodePanel() {
  obsCodeLoadMonaco(function () {
    obsCodeRefreshStatus();
    obsCodeLoadScripts();
    obsCodeInitResize();
    obsCodeInitFilesModal();
    obsCodeUpdateMode();

    if (OBS_CODE.editor) {
      setTimeout(function () { OBS_CODE.editor.layout(); }, 60);
    }
  });
}

function obsCodeLoadMonaco(cb) {
  if (OBS_CODE.monacoReady) {
    if (cb) cb();
    return;
  }
  if (window.require && window.require.config && window.monaco) {
    obsCodeCreateEditor();
    if (cb) cb();
    return;
  }

  var loader = document.createElement("script");
  loader.src = "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.min.js";
  loader.onload = function () {
    window.require.config({
      paths: {
        vs: "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs"
      }
    });
    window.require(["vs/editor/editor.main"], function () {
      obsCodeCreateEditor();
      if (cb) cb();
    });
  };
  loader.onerror = function () {
    var host = document.getElementById("codeEditorHost");
    if (host) {
      host.innerHTML =
        '<div style="padding:16px;color:var(--text2)">' +
        obsCodeEsc(obsCodeT("code.editor.offline")) + "</div>";
    }
  };
  document.head.appendChild(loader);
}

function obsCodeTheme() {
  var light = document.body.classList.contains("light") ||
              document.body.getAttribute("data-theme") === "light";
  return light ? "vs" : "vs-dark";
}

function obsCodeCreateEditor() {
  var host = document.getElementById("codeEditorHost");
  if (!host || OBS_CODE.editor) return;

  OBS_CODE.editor = window.monaco.editor.create(host, {
    value: "",
    language: OBS_CODE_MONACO_LANG[OBS_CODE.language] || "plaintext",
    theme: obsCodeTheme(),
    fontSize: 13,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    automaticLayout: true,
    tabSize: 4,
    renderWhitespace: "none"
  });

  OBS_CODE.monacoReady = true;

  OBS_CODE.editor.onDidChangeModelContent(function () {
    OBS_CODE.touched = true;
  });

  OBS_CODE.editor.addCommand(
    window.monaco.KeyMod.CtrlCmd | window.monaco.KeyCode.Enter,
    function () { obsCodeRun(); }
  );
  OBS_CODE.editor.addCommand(
    window.monaco.KeyMod.CtrlCmd | window.monaco.KeyCode.KeyS,
    function () { obsCodeSave(); }
  );
}

function obsCodeSetLanguage(lang) {
  OBS_CODE.language = lang;

  if (OBS_CODE.editor) {
    window.monaco.editor.setModelLanguage(
      OBS_CODE.editor.getModel(),
      OBS_CODE_MONACO_LANG[lang] || "plaintext"
    );
  }

  var runBtn = document.getElementById("codeRunBtn");
  if (runBtn) {
    runBtn.textContent = obsCodeT(
      obsCodeIsBrowser(lang) ? "code.preview" : "code.run"
    );
  }

  var obsBox = document.getElementById("codeWithObsBox");
  if (obsBox) {
    obsBox.style.display = obsCodeIsBrowser(lang) ? "none" : "";
  }

  var preview = document.getElementById("codePreview");
  var output = document.getElementById("codeOutput");
  if (preview && output) {
    preview.style.display = obsCodeIsBrowser(lang) ? "" : "none";
    output.style.display = obsCodeIsBrowser(lang) ? "none" : "";
  }

  obsCodeRenderStatus();
}


function obsCodeRefreshStatus() {
  fetch("/api/code/status")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      OBS_CODE.status = d;
      obsCodeRenderStatus();
      obsCodeRenderImages();
      obsCodeSyncPolling();
    })
    .catch(function () {});
}

function obsCodeAnyJobRunning() {
  var st = OBS_CODE.status;
  if (!st || !st.languages) return false;

  var keys = Object.keys(st.languages);
  for (var i = 0; i < keys.length; i++) {
    var job = st.languages[keys[i]].job;
    if (job && job.running) return true;
  }
  return false;
}

function obsCodeSyncPolling() {
  var running = obsCodeAnyJobRunning();

  if (running && !OBS_CODE.pollTimer) {
    OBS_CODE.pollTimer = setInterval(obsCodeRefreshStatus, 2000);
  } else if (!running && OBS_CODE.pollTimer) {
    clearInterval(OBS_CODE.pollTimer);
    OBS_CODE.pollTimer = null;
  }
}

function obsCodeRenderStatus() {
  var el = document.getElementById("codeRunnerStatus");
  if (!el) return;

  var st = OBS_CODE.status;
  if (!st) {
    el.textContent = "";
    return;
  }

  if (obsCodeIsBrowser(OBS_CODE.language)) {
    el.innerHTML = '<span style="color:var(--text2)">' +
      obsCodeEsc(obsCodeT("code.browser")) + "</span>";
    return;
  }

  if (!st.available) {
    el.innerHTML = '<span style="color:var(--red)">' +
      obsCodeEsc(st.detail || "runner non disponibile") + "</span>";
    return;
  }

  var lang = st.languages ? st.languages[OBS_CODE.language] : null;
  if (lang && !lang.ready) {
    el.innerHTML = '<span style="color:var(--red)">' +
      obsCodeEsc(obsCodeT("code.noimage")) + obsCodeEsc(lang.image) +
      "</span>";
    return;
  }

  el.innerHTML = '<span style="color:var(--text2)">runner: ' +
    obsCodeEsc(st.runner) + " | " + obsCodeEsc(obsCodeT("code.status.timeout")) +
    " " + obsCodeEsc(st.timeout) + "s | " +
    obsCodeEsc(obsCodeT("code.status.memory")) + " " +
    obsCodeEsc(st.memory_mb) + " MB</span>";
}

function obsCodeRun() {
  if (OBS_CODE.openFile && !obsCodeIsRunnable(OBS_CODE.openFile)) {
    obsCodeToast(obsCodeT("code.files.notrunnable"));
    return;
  }
  if (obsCodeIsBrowser(OBS_CODE.language)) {
    obsCodePreview();
    return;
  }
  if (!OBS_CODE.editor) return;

  var out = document.getElementById("codeOutput");
  var btn = document.getElementById("codeRunBtn");
  if (out) out.textContent = obsCodeT("code.running");
  if (btn) btn.disabled = true;

  var withObs = document.getElementById("codeWithObs");

  fetch("/api/code/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      language: OBS_CODE.language,
      source: OBS_CODE.editor.getValue(),
      stdin: (document.getElementById("codeStdin") || {}).value || "",
      with_obs: withObs ? withObs.checked : true
    })
  })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
      return r.json();
    })
    .then(function (d) {
      obsCodeRenderOutput(d);
      obsCodeShowPlots(d);
    })
    .catch(function (e) {
      if (out) out.textContent = obsCodeT("code.error") + e.message;
    })
    .finally(function () {
      if (btn) btn.disabled = false;
    });
}

function obsCodeShowPlots(d) {
  OBS_CODE.plots = d.plots || [];
  OBS_CODE.specs = d.specs || [];

  var total = OBS_CODE.plots.length + OBS_CODE.specs.length;
  var side = document.getElementById("codePlotSide");
  var body = document.getElementById("codePlotBody");
  if (!side || !body) return;

  if (!total) {
    if (OBS_CODE.plotsOpen) obsCodeTogglePlots();
    return;
  }

  body.innerHTML = "";

  OBS_CODE.plots.forEach(function (p, i) {
    var wrap = document.createElement("div");
    wrap.className = "code-plot";

    var img = document.createElement("img");
    img.src = "data:" + p.mime + ";base64," + p.data;
    img.alt = p.name;
    wrap.appendChild(img);

    var bar = document.createElement("div");
    bar.className = "code-plot-bar";

    var nm = document.createElement("span");
    nm.textContent = p.name;
    bar.appendChild(nm);

    var dl = document.createElement("button");
    dl.className = "btn btng";
    dl.textContent = obsCodeT("code.plot.download");
    dl.onclick = function () { obsCodeDownloadPlot(i); };
    bar.appendChild(dl);

    wrap.appendChild(bar);
    body.appendChild(wrap);
  });

  OBS_CODE.specs.forEach(function (spec, i) {
    var wrap = document.createElement("div");
    wrap.className = "code-plot";

    var host = document.createElement("div");
    host.id = "codePlotly" + i;
    host.style.width = "100%";
    host.style.height = "320px";
    wrap.appendChild(host);
    body.appendChild(wrap);

    obsCodeDrawSpec(host.id, spec);
  });

  if (!OBS_CODE.plotsOpen) obsCodeTogglePlots();
}

function obsCodeDrawSpec(hostId, spec) {
  if (typeof Plotly === "undefined") return;

  var kind = spec.kind || "line";
  var trace;

  if (kind === "bar") {
    trace = { type: "bar", x: spec.x, y: spec.y };
  } else if (kind === "scatter") {
    trace = { type: "scatter", mode: "markers", x: spec.x, y: spec.y };
  } else if (kind === "histogram") {
    trace = { type: "histogram", x: spec.x };
  } else if (kind === "pie") {
    trace = { type: "pie", labels: spec.labels, values: spec.y };
  } else {
    trace = { type: "scatter", mode: "lines", x: spec.x, y: spec.y };
  }

  var layout = {
    title: spec.title || "",
    xaxis: { title: spec.xlabel || "" },
    yaxis: { title: spec.ylabel || "" },
    margin: { l: 50, r: 20, t: 40, b: 50 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)"
  };

  Plotly.newPlot(hostId, [trace], layout, {
    responsive: true,
    displayModeBar: false
  });
}

function obsCodeDownloadPlot(i) {
  var p = OBS_CODE.plots[i];
  if (!p) return;

  var bin = atob(p.data);
  var arr = new Uint8Array(bin.length);
  for (var k = 0; k < bin.length; k++) arr[k] = bin.charCodeAt(k);

  var blob = new Blob([arr], { type: p.mime });
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = p.name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function obsCodeInitResize() {
  var handle = document.getElementById("codeResize");
  var wrap = document.getElementById("codeOutWrap");
  if (!handle || !wrap || handle.dataset.ready) return;

  handle.dataset.ready = "1";

  var startY = 0;
  var startH = 0;

  function onMove(ev) {
    var y = ev.touches ? ev.touches[0].clientY : ev.clientY;
    var delta = startY - y;
    var h = startH + delta;

    var body = document.querySelector("#panelCode .code-body");
    var max = body ? body.clientHeight - 120 : 600;

    if (h < 60) h = 60;
    if (h > max) h = max;

    wrap.style.height = h + "px";
    wrap.style.flexBasis = h + "px";
  }

  function onUp() {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    document.removeEventListener("touchmove", onMove);
    document.removeEventListener("touchend", onUp);

    document.body.classList.remove("code-resizing");
    handle.classList.remove("dragging");

    OBS_CODE.outHeight = wrap.clientHeight;
    try {
      localStorage.setItem("obs_code_out_h", String(OBS_CODE.outHeight));
    } catch (e) {}

    if (OBS_CODE.editor) OBS_CODE.editor.layout();
    obsCodeResizeSpecs();
  }

  function onDown(ev) {
    startY = ev.touches ? ev.touches[0].clientY : ev.clientY;
    startH = wrap.clientHeight;

    document.body.classList.add("code-resizing");
    handle.classList.add("dragging");

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("touchend", onUp);

    ev.preventDefault();
  }

  handle.addEventListener("mousedown", onDown);
  handle.addEventListener("touchstart", onDown, { passive: false });

  handle.addEventListener("dblclick", function () {
    obsCodeSetOutHeight(220);
  });

  var saved = null;
  try {
    saved = localStorage.getItem("obs_code_out_h");
  } catch (e) {}

  if (saved) {
    var h = parseInt(saved, 10);
    if (h >= 60 && h <= 1200) obsCodeSetOutHeight(h);
  }
}

function obsCodeSetOutHeight(h) {
  var wrap = document.getElementById("codeOutWrap");
  if (!wrap) return;

  wrap.style.height = h + "px";
  wrap.style.flexBasis = h + "px";
  OBS_CODE.outHeight = h;

  if (OBS_CODE.editor) {
    setTimeout(function () { OBS_CODE.editor.layout(); }, 40);
  }
  obsCodeResizeSpecs();
}

function obsCodeResizeSpecs() {
  if (typeof Plotly === "undefined") return;
  setTimeout(function () {
    OBS_CODE.specs.forEach(function (spec, i) {
      var el = document.getElementById("codePlotly" + i);
      if (el) Plotly.Plots.resize(el);
    });
  }, 60);
}

function obsCodeTogglePlots() {
  var side = document.getElementById("codePlotSide");
  if (!side) return;

  OBS_CODE.plotsOpen = !OBS_CODE.plotsOpen;
  side.style.display = OBS_CODE.plotsOpen ? "flex" : "none";

  if (OBS_CODE.editor) {
    setTimeout(function () { OBS_CODE.editor.layout(); }, 60);
  }
  if (OBS_CODE.plotsOpen && typeof Plotly !== "undefined") {
    setTimeout(function () {
      OBS_CODE.specs.forEach(function (spec, i) {
        var el = document.getElementById("codePlotly" + i);
        if (el) Plotly.Plots.resize(el);
      });
    }, 80);
  }
}

function obsCodeRenderOutput(d) {
  var out = document.getElementById("codeOutput");
  if (!out) return;

  var parts = [];

  if (d.timed_out) {
    parts.push('<div style="color:var(--red)">' +
      obsCodeEsc(obsCodeT("code.timeout")) + "</div>");
  }
  if (d.stage === "build" && d.exit_code !== 0) {
    parts.push('<div style="color:var(--red)">' +
      obsCodeEsc(obsCodeT("code.builderror")) + "</div>");
  }
  if (d.stdout) {
    parts.push("<pre>" + obsCodeEsc(d.stdout) + "</pre>");
  }
  if (d.stderr) {
    parts.push('<pre style="color:var(--red)">' + obsCodeEsc(d.stderr) + "</pre>");
  }
  if (!d.stdout && !d.stderr) {
    parts.push('<div style="color:var(--text2)">' +
      obsCodeEsc(obsCodeT("code.nooutput")) + "</div>");
  }

  parts.push('<div class="code-meta">exit ' + obsCodeEsc(d.exit_code) +
    " | " + obsCodeEsc(d.duration) + "s | " + obsCodeEsc(d.stage) + "</div>");

  out.innerHTML = parts.join("");
}

function obsCodePreview() {
  if (!OBS_CODE.editor) return;
  var frame = document.getElementById("codePreviewFrame");
  if (!frame) return;

  var src = OBS_CODE.editor.getValue();
  if (OBS_CODE.language === "css") {
    src = "<!DOCTYPE html><html><head><style>" + src +
          "</style></head><body><h1>CSS</h1>" +
          "<p>Lorem ipsum dolor sit amet.</p>" +
          "<button>Button</button></body></html>";
  }

  frame.srcdoc = src;
}

function obsCodeSave() {
  if (!OBS_CODE.editor) return;

  if (OBS_CODE.openFile) {
    obsCodeSaveFile();
    return;
  }

  if (OBS_CODE.scriptName) {
    obsCodeDoSave(OBS_CODE.scriptName);
    return;
  }

  obsCodeAsk(obsCodeT("code.scripts.name"), "script").then(function (name) {
    if (name) obsCodeDoSave(name);
  });
}

function obsCodeAsk(message, value) {
  if (typeof obsPrompt === "function") {
    return obsPrompt(message, value, obsCodeT("code.save"));
  }
  return Promise.resolve(prompt(message, value));
}

function obsCodeAskConfirm(message, okLabel) {
  if (typeof obsConfirm === "function") {
    return obsConfirm(message, obsCodeT("tab.code"), okLabel);
  }
  return Promise.resolve(confirm(message));
}

function obsCodeDoSave(name) {
  OBS_CODE.scriptName = name;

  fetch("/api/code/scripts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: name,
      language: OBS_CODE.language,
      source: OBS_CODE.editor.getValue(),
      script_id: OBS_CODE.scriptId
    })
  })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
      return r.json();
    })
    .then(function (d) {
      OBS_CODE.scriptId = d.script_id;
      obsCodeLoadScripts();
      obsCodeToast(obsCodeT("code.scripts.saved"));
    })
    .catch(function (e) { obsCodeToast(obsCodeT("code.error") + e.message); });
}

function obsCodeNew() {
  OBS_CODE.scriptId = null;
  OBS_CODE.scriptName = "";
  OBS_CODE.openFile = null;
  OBS_CODE.touched = false;
  obsCodeUpdateMode();

  if (OBS_CODE.editor) {
    OBS_CODE.editor.setValue("");
  }

  var out = document.getElementById("codeOutput");
  if (out) out.innerHTML = "";

  OBS_CODE.plots = [];
  OBS_CODE.specs = [];
  if (OBS_CODE.plotsOpen) obsCodeTogglePlots();
}


function obsCodeLoadScripts() {
  fetch("/api/code/scripts")
    .then(function (r) { return r.ok ? r.json() : []; })
    .then(function (list) {
      OBS_CODE.scriptsAll = list || [];
      obsCodeRenderScripts();
    })
    .catch(function () {});
}

function obsCodeRenderScripts() {
  var el = document.getElementById("codeScriptList");
  if (!el) return;

  var list = OBS_CODE.scriptsAll || [];
  var filtro = OBS_CODE.scriptFilter;

  var visibili = list.filter(function (s) {
    return !filtro ||
           s.name.toLowerCase().indexOf(filtro) !== -1 ||
           s.language.toLowerCase().indexOf(filtro) !== -1;
  });

  if (!list.length) {
    el.innerHTML = '<div class="code-empty">' +
      obsCodeEsc(obsCodeT("code.scripts.empty")) + "</div>";
    return;
  }

  if (!visibili.length) {
    el.innerHTML = '<div class="code-empty">' +
      obsCodeEsc(obsCodeT("code.search.none")) + "</div>";
    return;
  }

  el.innerHTML = visibili.map(function (s) {
    var attivo = (OBS_CODE.scriptId === s.script_id) ? " attivo" : "";
    return '<div class="code-script' + attivo + '" onclick="obsCodeOpen(\'' +
      obsCodeEsc(s.script_id) + '\')">' +
      '<span class="nm">' + obsCodeEsc(s.name) + "</span>" +
      '<span class="lg">' + obsCodeEsc(s.language) + "</span>" +
      '<button class="code-del" title="' +
      obsCodeEsc(obsCodeT("code.files.delete")) + '" ' +
      'onclick="event.stopPropagation();obsCodeDelete(\'' +
      obsCodeEsc(s.script_id) + '\')">\u00d7</button>' +
      "</div>";
  }).join("");
}

function obsCodeOpen(scriptId) {
  fetch("/api/code/scripts/" + encodeURIComponent(scriptId))
    .then(function (r) {
      if (!r.ok) throw new Error("script non accessibile");
      return r.json();
    })
    .then(function (d) {
      OBS_CODE.scriptId = d.script_id;
      OBS_CODE.scriptName = d.name;
      OBS_CODE.openFile = null;
      OBS_CODE.language = d.language;
      obsCodeUpdateMode();

      var sel = document.getElementById("codeLangSelect");
      if (sel) sel.value = d.language;

      if (OBS_CODE.editor) {
        window.monaco.editor.setModelLanguage(
          OBS_CODE.editor.getModel(),
          OBS_CODE_MONACO_LANG[d.language] || "plaintext"
        );
        OBS_CODE.editor.setValue(d.source || "");
      }

      obsCodeRenderStatus();
    })
    .catch(function (e) { obsCodeToast(obsCodeT("code.error") + e.message); });
}

function obsCodeDelete(scriptId) {
  obsCodeAskConfirm(
    obsCodeT("code.scripts.delete"),
    obsCodeT("code.images.remove")
  ).then(function (ok) {
    if (!ok) return;

    fetch("/api/code/scripts/" + encodeURIComponent(scriptId), { method: "DELETE" })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        if (OBS_CODE.scriptId === scriptId) obsCodeNew();
        obsCodeLoadScripts();
      })
      .catch(function (e) { obsCodeToast(obsCodeT("code.error") + e.message); });
  });
}

function obsCodeExport() {
  if (!OBS_CODE.editor) return;

  if (obsCodeIsBrowser(OBS_CODE.language)) {
    var ext = OBS_CODE.language === "css" ? ".css" : ".html";
    var blob = new Blob([OBS_CODE.editor.getValue()], { type: "text/plain" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (OBS_CODE.scriptName || "script") + ext;
    a.click();
    URL.revokeObjectURL(a.href);
    return;
  }

  var withObs = document.getElementById("codeWithObs");

  fetch("/api/code/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: OBS_CODE.scriptName || "script",
      language: OBS_CODE.language,
      source: OBS_CODE.editor.getValue(),
      with_obs: withObs ? withObs.checked : true
    })
  })
    .then(function (r) {
      if (!r.ok) throw new Error("esportazione fallita");
      return r.blob();
    })
    .then(function (blob) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = (OBS_CODE.scriptName || "script") + ".zip";
      a.click();
      URL.revokeObjectURL(a.href);
    })
    .catch(function (e) { obsCodeToast(obsCodeT("code.error") + e.message); });
}

function obsCodeToggleFiles() {
  var m = document.getElementById("codeFilesModal");
  if (!m) return;

  if (m.classList.contains("show")) {
    m.classList.remove("show");
    return;
  }

  m.classList.add("show");
  obsCodeLoadFiles();

  var cerca = document.getElementById("codeFilesSearch");
  if (cerca) {
    cerca.value = OBS_CODE.fileFilter;
    setTimeout(function () { cerca.focus(); }, 40);
  }
}

function obsCodeInitFilesModal() {
  var m = document.getElementById("codeFilesModal");
  if (!m || m.dataset.ready) return;

  m.dataset.ready = "1";

  m.addEventListener("mousedown", function (ev) {
    if (ev.target === m) obsCodeToggleFiles();
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && m.classList.contains("show")) {
      obsCodeToggleFiles();
    }
  });
}

function obsCodeFilterFiles(v) {
  OBS_CODE.fileFilter = (v || "").toLowerCase();
  obsCodeRenderFiles(null);
}

function obsCodeFilterScripts(v) {
  OBS_CODE.scriptFilter = (v || "").toLowerCase();
  obsCodeRenderScripts();
}


function obsCodeSize2(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function obsCodeLoadFiles() {
  fetch("/api/code/files")
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d) return;
      OBS_CODE.files = d.files || [];
      obsCodeRenderFiles(d.usage);
    })
    .catch(function () {});
}

function obsCodeRenderFiles(usage) {
  var box = document.getElementById("codeFilesList");
  if (!box) return;

  if (usage) OBS_CODE.lastUsage = usage;
  usage = OBS_CODE.lastUsage;

  var filtro = OBS_CODE.fileFilter;
  var visibili = OBS_CODE.files.filter(function (f) {
    return !filtro || f.name.toLowerCase().indexOf(filtro) !== -1;
  });

  var parts = [];

  if (!OBS_CODE.files.length) {
    parts.push('<div class="code-empty">' +
      obsCodeEsc(obsCodeT("code.files.empty")) + "</div>");
  } else if (!visibili.length) {
    parts.push('<div class="code-empty">' +
      obsCodeEsc(obsCodeT("code.search.none")) + "</div>");
  } else {
    parts.push(visibili.map(function (f) {
      var apribile = obsCodeIsTextFile(f.name);
      var attivo = (OBS_CODE.openFile === f.name) ? " attivo" : "";

      return '<div class="code-file-row' + attivo + '">' +
        (apribile
          ? '<span class="nm apri" onclick="obsCodeOpenFile(\'' +
            obsCodeEsc(f.name) + '\')" title="' +
            obsCodeEsc(obsCodeT("code.files.open")) + '">' +
            obsCodeEsc(f.name) + "</span>"
          : '<span class="nm">' + obsCodeEsc(f.name) + "</span>") +
        '<span class="sz">' + obsCodeSize2(f.size) + "</span>" +
        '<button class="btn btng" onclick="obsCodeDownloadFile(\'' +
        obsCodeEsc(f.name) + '\')">' +
        obsCodeEsc(obsCodeT("code.files.download")) + "</button>" +
        '<button class="code-del" title="' +
        obsCodeEsc(obsCodeT("code.files.delete")) + '" ' +
        'onclick="obsCodeDeleteFile(\'' + obsCodeEsc(f.name) + '\')">' +
        "\u00d7</button>" +
        "</div>";
    }).join(""));
  }

  if (usage) {
    parts.push('<div class="code-files-foot">' +
      obsCodeEsc(obsCodeT("code.files.usage")) + " " +
      obsCodeSize2(usage.used) + " / " + obsCodeSize2(usage.max_total) +
      " | " + usage.files + " / " + usage.max_files +
      "</div>");
  }

  box.innerHTML = parts.join("");
}

var OBS_CODE_TEXT_EXT = [
  ".csv", ".tsv", ".txt", ".json", ".xml", ".yaml", ".yml",
  ".dat", ".data", ".md", ".sql", ".svg",
  ".py", ".js", ".java", ".c", ".cpp", ".h", ".hpp", ".m", ".r",
  ".html", ".css"
];

var OBS_CODE_EXT_LANG = {
  ".py": "python", ".js": "javascript", ".java": "java",
  ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
  ".m": "octave", ".r": "r",
  ".html": "html", ".css": "css"
};

function obsCodeExt(name) {
  var i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i).toLowerCase();
}

function obsCodeIsTextFile(name) {
  return OBS_CODE_TEXT_EXT.indexOf(obsCodeExt(name)) !== -1;
}

function obsCodeIsRunnable(name) {
  return OBS_CODE_EXT_LANG.hasOwnProperty(obsCodeExt(name));
}

function obsCodeOpenFile(name) {
  if (!OBS_CODE.editor) return;

  fetch("/api/code/files/" + encodeURIComponent(name) + "/content")
    .then(function (r) {
      if (!r.ok) throw new Error("apertura fallita");
      return r.json();
    })
    .then(function (d) {
      if (!d.readable) {
        obsCodeToast(obsCodeT("code.files.binary"));
        return;
      }

      OBS_CODE.openFile = d.name;
      OBS_CODE.scriptId = null;
      OBS_CODE.scriptName = "";

      var ext = obsCodeExt(d.name);
      var lang = OBS_CODE_EXT_LANG[ext];

      if (lang) {
        OBS_CODE.language = lang;
        var sel = document.getElementById("codeLangSelect");
        if (sel) sel.value = lang;
        obsCodeRenderStatus();
      }

      window.monaco.editor.setModelLanguage(
        OBS_CODE.editor.getModel(),
        lang ? (OBS_CODE_MONACO_LANG[lang] || "plaintext")
             : obsCodeMonacoForExt(ext)
      );

      OBS_CODE.editor.setValue(d.content);
      OBS_CODE.touched = false;

      if (d.truncated) {
        obsCodeToast(obsCodeT("code.files.truncated"));
      }

      obsCodeRenderFiles(null);
      obsCodeLoadFiles();
      obsCodeUpdateMode();
    })
    .catch(function (e) {
      obsCodeToast(obsCodeT("code.error") + e.message);
    });
}

function obsCodeMonacoForExt(ext) {
  var m = {
    ".csv": "plaintext", ".tsv": "plaintext", ".txt": "plaintext",
    ".dat": "plaintext", ".data": "plaintext",
    ".json": "json", ".xml": "xml", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".sql": "sql", ".svg": "xml"
  };
  return m[ext] || "plaintext";
}

function obsCodeUpdateMode() {
  var bar = document.getElementById("codeFileBar");
  var nome = document.getElementById("codeFileName");

  if (!bar) return;

  if (OBS_CODE.openFile) {
    bar.style.display = "";
    if (nome) nome.textContent = OBS_CODE.openFile;
  } else {
    bar.style.display = "none";
  }

  if (OBS_CODE.editor) {
    setTimeout(function () { OBS_CODE.editor.layout(); }, 40);
  }
}

function obsCodeCloseFile() {
  OBS_CODE.openFile = null;
  OBS_CODE.touched = false;

  if (OBS_CODE.editor) {
    OBS_CODE.editor.setValue("");
  }

  obsCodeUpdateMode();
  obsCodeLoadFiles();
}

function obsCodeSaveFile() {
  if (!OBS_CODE.openFile || !OBS_CODE.editor) return;

  fetch("/api/code/files/" + encodeURIComponent(OBS_CODE.openFile) + "/content", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: OBS_CODE.editor.getValue() })
  })
    .then(function (r) {
      if (!r.ok) {
        return r.json().then(function (e) {
          throw new Error(e.detail || r.status);
        });
      }
      return r.json();
    })
    .then(function () {
      OBS_CODE.touched = false;
      obsCodeToast(obsCodeT("code.files.saved"));
      obsCodeLoadFiles();
    })
    .catch(function (e) {
      obsCodeToast(obsCodeT("code.error") + e.message);
    });
}

function obsCodeUploadFiles(input) {
  if (!input.files || !input.files.length) return;

  var pendenti = input.files.length;
  var errori = [];

  Array.prototype.forEach.call(input.files, function (f) {
    var fd = new FormData();
    fd.append("file", f);

    fetch("/api/code/files", { method: "POST", body: fd })
      .then(function (r) {
        if (!r.ok) {
          return r.json().then(function (e) {
            throw new Error(f.name + ": " + (e.detail || r.status));
          });
        }
        return r.json();
      })
      .catch(function (e) { errori.push(e.message); })
      .finally(function () {
        pendenti--;
        if (pendenti === 0) {
          input.value = "";
          obsCodeLoadFiles();
          if (errori.length) {
            obsCodeToast(errori[0]);
          } else {
            obsCodeToast(obsCodeT("code.files.uploaded"));
          }
        }
      });
  });
}

function obsCodeDownloadFile(name) {
  var a = document.createElement("a");
  a.href = "/api/code/files/" + encodeURIComponent(name);
  a.download = name;
  a.click();
}

function obsCodeDeleteFile(name) {
  obsCodeAskConfirm(obsCodeT("code.files.confirm") + " " + name + "?")
    .then(function (ok) {
      if (!ok) return;
      fetch("/api/code/files/" + encodeURIComponent(name), { method: "DELETE" })
        .then(function (r) {
          if (!r.ok) throw new Error("eliminazione fallita");
          obsCodeLoadFiles();
        })
        .catch(function (e) { obsCodeToast(obsCodeT("code.error") + e.message); });
    });
}

function obsCodeToggleImages() {
  var box = document.getElementById("codeImagesBox");
  if (!box) return;
  var open = box.style.display !== "none";
  box.style.display = open ? "none" : "";
  if (!open) {
    obsCodeRefreshStatus();
  }
}

function obsCodeRenderImages() {
  var box = document.getElementById("codeImagesList");
  if (!box) return;

  var st = OBS_CODE.status;
  if (!st || !st.managed) {
    box.innerHTML = '<div class="code-empty">' +
      obsCodeEsc(obsCodeT("code.images.norunner")) + "</div>";
    return;
  }
  if (!st.available) {
    box.innerHTML = '<div style="color:var(--red);font-size:12px">' +
      obsCodeEsc(st.detail) + "</div>";
    return;
  }

  var canManage = obsCodeCanManage();

  var rows = Object.keys(st.languages).map(function (key) {
    var l = st.languages[key];
    var job = l.job;

    var state;
    if (job && job.running) {
      var fallback = l.built
        ? obsCodeT("code.images.building")
        : obsCodeT("code.images.downloading");
      state = '<span style="color:var(--accent)">' +
        obsCodeEsc(job.message || fallback) + "</span>";
    } else if (l.ready) {
      state = '<span style="color:var(--text2)">' +
        obsCodeEsc(obsCodeT("code.images.installed")) + " " +
        obsCodeSize(l.size) + "</span>";
    } else {
      state = '<span style="color:var(--text2)">' +
        obsCodeEsc(obsCodeT("code.images.notinstalled")) + "</span>";
    }

    var action = "";
    if (canManage && !(job && job.running)) {
      if (l.ready) {
        action = '<button class="btn btng" onclick="obsCodeRemoveImage(\'' +
          obsCodeEsc(key) + '\')">' + obsCodeEsc(obsCodeT("code.images.remove")) +
          "</button>";
      } else {
        action = '<button class="btn btng" onclick="obsCodePullImage(\'' +
          obsCodeEsc(key) + '\')">' +
          obsCodeEsc(obsCodeT(l.built ? "code.images.build"
                                      : "code.images.download")) +
          "</button>";
      }
    }

    var tags = [];
    if (l.plotting) tags.push("plot");
    if (l.extras && l.extras.length) {
      l.extras.forEach(function (x) { tags.push(x); });
    }
    var badge = tags.length
      ? ' <span style="color:var(--text2);font-size:10px">(' +
        obsCodeEsc(tags.join(", ")) + ")</span>"
      : "";

    return '<div class="code-img-row">' +
      "<div><b>" + obsCodeEsc(l.label) + "</b>" + badge + "<br>" +
      '<span class="img">' + obsCodeEsc(l.image) + "</span></div>" +
      "<div>" + state + "</div>" +
      "<div>" + (action || "") + "</div>" +
      "</div>";
  }).join("");

  var footer = "";
  if (canManage) {
    footer = '<div style="margin-top:10px">' +
      '<button class="btn btng" onclick="obsCodeCleanup()">' +
      obsCodeEsc(obsCodeT("code.images.cleanup")) + "</button></div>";
  } else {
    footer = '<div style="margin-top:10px;color:var(--text2);font-size:11px">' +
      obsCodeEsc(obsCodeT("code.images.restricted")) + "</div>";
  }

  box.innerHTML = rows + footer;

}

function obsCodePullImage(lang) {
  fetch("/api/code/images/pull", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language: lang })
  })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
      return r.json();
    })
    .then(function () { obsCodeRefreshStatus(); })
    .catch(function (e) { obsCodeToast(obsCodeT("code.error") + e.message); });
}

function obsCodeRemoveImage(lang) {
  obsCodeAskConfirm(
    obsCodeT("code.images.confirm") + lang + "?",
    obsCodeT("code.images.remove")
  ).then(function (ok) {
    if (!ok) return;

    fetch("/api/code/images/" + encodeURIComponent(lang), { method: "DELETE" })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
        return r.json();
      })
      .then(function (d) {
        if (d.also_affects && d.also_affects.length) {
          obsCodeToast(obsCodeT("code.images.affects") + d.also_affects.join(", "));
        }
        obsCodeRefreshStatus();
      })
      .catch(function (e) { obsCodeToast(obsCodeT("code.error") + e.message); });
  });
}

function obsCodeCleanup() {
  fetch("/api/code/images/cleanup", { method: "POST" })
    .then(function (r) {
      if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || r.status); });
      return r.json();
    })
    .then(function (d) {
      obsCodeToast(obsCodeT("code.images.cleaned") + d.containers_removed);
      obsCodeRefreshStatus();
    })
    .catch(function (e) { obsCodeToast(obsCodeT("code.error") + e.message); });
}

function obsCodeToast(msg) {
  var el = document.getElementById("codeToast");
  if (!el) {
    if (typeof obsConfirm === "function") {
      obsConfirm(msg, obsCodeT("tab.code"), "OK");
    }
    return;
  }
  el.textContent = msg;
  el.style.display = "";
  setTimeout(function () { el.style.display = "none"; }, 3000);
}

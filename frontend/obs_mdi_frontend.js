var OBS_MDI = {
  wins: [],
  activeId: null,
  seq: 0,
  z: 10,
  owner: {},
  _internal: false,
  _init: false
};

var OBS_MDI_PANELS = [
  "query", "upload", "documents", "audit", "clusters",
  "images", "entities", "investigate", "digitize", "code", "sheets",
  "agents", "fs"
];

function obsMdiT(key, fallback) {
  if (typeof t === "function") {
    var v = t(key);
    if (v && v !== key) return v;
  }
  return fallback;
}

var OBS_MDI_FB = {
  query: "Query", upload: "Upload", documents: "Documents", audit: "Audit",
  clusters: "Clusters", images: "Images", entities: "Entities",
  investigate: "Investigate", digitize: "Digitize", code: "Code",
  sheets: "Sheets", agents: "Agents", fs: "Local files"
};

function obsMdiLabel(panel) {
  return obsMdiT("tab." + panel, OBS_MDI_FB[panel] || panel);
}

function obsMdiEsc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function obsMdiPanelEl(panel) {
  return document.getElementById(
    "panel" + panel.charAt(0).toUpperCase() + panel.slice(1)
  );
}

function obsMdiFind(id) {
  for (var i = 0; i < OBS_MDI.wins.length; i++) {
    if (OBS_MDI.wins[i].id === id) return OBS_MDI.wins[i];
  }
  return null;
}

function obsMdiActive() {
  return obsMdiFind(OBS_MDI.activeId);
}

function obsMdiEnsureInit() {
  if (OBS_MDI._init) return;
  var dock = document.getElementById("obsPanelDock");
  var main = document.getElementById("obsMdi");
  if (!dock || !main) return;
  for (var i = 0; i < OBS_MDI_PANELS.length; i++) {
    var el = obsMdiPanelEl(OBS_MDI_PANELS[i]);
    if (el && el.parentNode && el.parentNode.id !== "obsPanelDock") {
      dock.appendChild(el);
    }
  }
  OBS_MDI._init = true;
}

function obsMdiCaptureQuery() {
  var chat = document.getElementById("chatArea");
  var ta = document.getElementById("queryInput");
  var az = document.getElementById("azFilter");
  var dt = document.getElementById("docTarget");
  return {
    html: chat ? chat.innerHTML : null,
    input: ta ? ta.value : "",
    azienda: az ? az.value : "",
    docTarget: dt ? dt.value : "",
    chatId: typeof currentChatId !== "undefined" ? currentChatId : null,
    messages: typeof currentChatMessages !== "undefined"
      ? currentChatMessages.slice() : [],
    title: typeof currentChatTitle !== "undefined" ? currentChatTitle : null,
    history: typeof conversationHistory !== "undefined"
      ? conversationHistory.slice() : [],
    charts: window.OBS_CHARTS ? window.OBS_CHARTS : null
  };
}

function obsMdiRestoreQuery(st) {
  if (!st) return;
  var chat = document.getElementById("chatArea");
  var ta = document.getElementById("queryInput");
  var az = document.getElementById("azFilter");
  var dt = document.getElementById("docTarget");
  if (chat && typeof st.html === "string") chat.innerHTML = st.html;
  if (ta) ta.value = st.input || "";
  if (az && typeof st.azienda === "string") az.value = st.azienda;
  if (dt && typeof st.docTarget === "string") dt.value = st.docTarget;
  if (typeof currentChatId !== "undefined") currentChatId = st.chatId;
  if (typeof currentChatMessages !== "undefined") {
    currentChatMessages = st.messages ? st.messages.slice() : [];
  }
  if (typeof currentChatTitle !== "undefined") currentChatTitle = st.title;
  if (typeof conversationHistory !== "undefined") {
    conversationHistory = st.history ? st.history.slice() : [];
  }
  if (st.charts) window.OBS_CHARTS = st.charts;
  if (typeof rerenderCharts === "function") setTimeout(rerenderCharts, 120);
}

function obsMdiCaptureCode() {
  if (typeof OBS_CODE === "undefined") return null;
  var src = "";
  if (OBS_CODE.editor) {
    try { src = OBS_CODE.editor.getValue(); } catch (e) { src = ""; }
  }
  var out = document.getElementById("codeOut");
  return {
    source: src,
    language: OBS_CODE.language,
    scriptId: OBS_CODE.scriptId,
    scriptName: OBS_CODE.scriptName,
    touched: !!OBS_CODE.touched,
    outHtml: out ? out.innerHTML : null
  };
}

function obsMdiRestoreCode(st) {
  if (!st || typeof OBS_CODE === "undefined") return;
  OBS_CODE.language = st.language || OBS_CODE.language;
  OBS_CODE.scriptId = st.scriptId;
  OBS_CODE.scriptName = st.scriptName || "";
  if (OBS_CODE.editor) {
    try {
      OBS_CODE.editor.setValue(st.source || "");
      if (window.monaco && typeof OBS_CODE_MONACO_LANG !== "undefined") {
        window.monaco.editor.setModelLanguage(
          OBS_CODE.editor.getModel(),
          OBS_CODE_MONACO_LANG[OBS_CODE.language] || "plaintext"
        );
      }
    } catch (e) {}
  }
  OBS_CODE.touched = !!st.touched;
  var out = document.getElementById("codeOut");
  if (out && typeof st.outHtml === "string") out.innerHTML = st.outHtml;
  if (typeof obsCodeUpdateMode === "function") obsCodeUpdateMode();
}

function obsMdiCapture(panel) {
  if (panel === "query") return obsMdiCaptureQuery();
  if (panel === "code") return obsMdiCaptureCode();
  return null;
}

function obsMdiRestore(panel, st) {
  if (panel === "query") { obsMdiRestoreQuery(st); return; }
  if (panel === "code") { obsMdiRestoreCode(st); return; }
}

function obsMdiIsDirty(win) {
  if (!win || win.panel !== "code") return false;
  if (OBS_MDI.owner[win.panel] === win.id && typeof OBS_CODE !== "undefined") {
    return !!OBS_CODE.touched;
  }
  return !!(win.state && win.state.touched);
}

function obsMdiDetachPanel(panel) {
  var owner = OBS_MDI.owner[panel];
  if (!owner) return;
  var win = obsMdiFind(owner);
  var el = obsMdiPanelEl(panel);
  var dock = document.getElementById("obsPanelDock");
  if (win) {
    win.state = obsMdiCapture(panel);
    var ph = win.bodyEl ? win.bodyEl.querySelector(".obs-win-placeholder") : null;
    if (win.bodyEl && !ph) {
      var d = document.createElement("div");
      d.className = "obs-win-placeholder";
      d.innerHTML = obsMdiT("mdi.detached",
        "Questo pannello e attivo in un altra finestra. Clicca per riportarlo qui.");
      win.bodyEl.appendChild(d);
    }
  }
  if (el && dock) dock.appendChild(el);
  OBS_MDI.owner[panel] = null;
}

function obsMdiAttachPanel(win) {
  var panel = win.panel;
  var prev = OBS_MDI.owner[panel];
  if (prev && prev !== win.id) obsMdiDetachPanel(panel);
  var el = obsMdiPanelEl(panel);
  if (!el || !win.bodyEl) return;
  var ph = win.bodyEl.querySelector(".obs-win-placeholder");
  if (ph) ph.parentNode.removeChild(ph);
  win.bodyEl.appendChild(el);
  el.classList.add("active");
  OBS_MDI.owner[panel] = win.id;
  OBS_MDI._internal = true;
  if (typeof _obsSwitchPanelCore === "function") _obsSwitchPanelCore(panel);
  OBS_MDI._internal = false;
  obsMdiRestore(panel, win.state);
}

function obsMdiNew(panel, focus) {
  if (OBS_MDI_PANELS.indexOf(panel) === -1) return null;
  obsMdiEnsureInit();
  obsMdiEnterMode();
  OBS_MDI.seq += 1;
  var n = OBS_MDI.wins.length;
  var win = {
    id: "w" + OBS_MDI.seq,
    panel: panel,
    label: obsMdiLabel(panel),
    state: null,
    minimized: false,
    maximized: false,
    x: 20 + (n % 6) * 26,
    y: 16 + (n % 6) * 24,
    w: 640,
    h: 420,
    px: 0, py: 0, pw: 0, ph: 0
  };
  OBS_MDI.wins.push(win);
  obsMdiBuild(win);
  obsMdiRender();
  if (focus !== false) obsMdiActivate(win.id);
  return win;
}

function obsMdiNewFromCurrent() {
  var act = obsMdiActive();
  var panel = act ? act.panel : (window.OBS_ACTIVE_PANEL || "query");
  obsMdiNew(panel, true);
}

function obsMdiBuild(win) {
  var host = document.getElementById("obsMdi");
  if (!host) return;
  var el = document.createElement("div");
  el.className = "obs-win";
  el.id = "mdi-" + win.id;
  el.style.left = win.x + "px";
  el.style.top = win.y + "px";
  el.style.width = win.w + "px";
  el.style.height = win.h + "px";
  el.style.zIndex = String(++OBS_MDI.z);

  var title = document.createElement("div");
  title.className = "obs-win-title";
  var name = document.createElement("div");
  name.className = "obs-win-name";
  name.textContent = win.label;
  var btns = document.createElement("div");
  btns.className = "obs-win-btns";
  var bMin = document.createElement("button");
  bMin.className = "obs-win-btn min";
  bMin.innerHTML = "&#8211;";
  bMin.title = "Minimize";
  bMin.onclick = function (e) { e.stopPropagation(); obsMdiMinimize(win.id); };
  var bMax = document.createElement("button");
  bMax.className = "obs-win-btn max";
  bMax.innerHTML = "&#9633;";
  bMax.title = "Maximize";
  bMax.onclick = function (e) { e.stopPropagation(); obsMdiToggleMax(win.id); };
  var bClose = document.createElement("button");
  bClose.className = "obs-win-btn close";
  bClose.innerHTML = "&#215;";
  bClose.title = "Close";
  bClose.onclick = function (e) { e.stopPropagation(); obsMdiClose(win.id); };
  btns.appendChild(bMin);
  btns.appendChild(bMax);
  btns.appendChild(bClose);
  title.appendChild(name);
  title.appendChild(btns);

  var body = document.createElement("div");
  body.className = "obs-win-body";

  var resize = document.createElement("div");
  resize.className = "obs-win-resize";

  el.appendChild(title);
  el.appendChild(body);
  el.appendChild(resize);
  host.appendChild(el);

  win.el = el;
  win.titleEl = title;
  win.nameEl = name;
  win.bodyEl = body;

  el.addEventListener("mousedown", function () { obsMdiActivate(win.id); });
  obsMdiMakeDraggable(win, title);
  obsMdiMakeResizable(win, resize);
  title.addEventListener("dblclick", function () { obsMdiToggleMax(win.id); });
}

function obsMdiMakeDraggable(win, handle) {
  handle.addEventListener("mousedown", function (e) {
    if (win.maximized) return;
    e.preventDefault();
    var sx = e.clientX, sy = e.clientY;
    var ox = win.x, oy = win.y;
    var host = document.getElementById("obsMdi");
    function move(ev) {
      var nx = ox + ev.clientX - sx;
      var ny = oy + ev.clientY - sy;
      var maxX = host ? host.clientWidth : 0;
      var maxY = host ? host.clientHeight : 0;
      var margin = 60;
      var minX = margin - win.w;
      var minY = 0;
      var limX = maxX - margin;
      var limY = maxY - 22;
      if (nx < minX) nx = minX;
      if (ny < minY) ny = minY;
      if (maxX && nx > limX) nx = limX;
      if (maxY && ny > limY) ny = limY;
      win.x = nx;
      win.y = ny;
      win.el.style.left = win.x + "px";
      win.el.style.top = win.y + "px";
    }
    function up() {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    }
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  });
}

function obsMdiMakeResizable(win, handle) {
  handle.addEventListener("mousedown", function (e) {
    if (win.maximized) return;
    e.preventDefault();
    e.stopPropagation();
    var sx = e.clientX, sy = e.clientY;
    var ow = win.w, oh = win.h;
    var host = document.getElementById("obsMdi");
    function move(ev) {
      var nw = ow + ev.clientX - sx;
      var nh = oh + ev.clientY - sy;
      if (nw < 280) nw = 280;
      if (nh < 160) nh = 160;
      if (host) {
        var maxW = host.clientWidth - win.x;
        var maxH = host.clientHeight - win.y;
        if (maxW > 280 && nw > maxW) nw = maxW;
        if (maxH > 160 && nh > maxH) nh = maxH;
      }
      win.w = nw;
      win.h = nh;
      win.el.style.width = win.w + "px";
      win.el.style.height = win.h + "px";
    }
    function up() {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    }
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  });
}

function obsMdiClampAll() {
  var host = document.getElementById("obsMdi");
  if (!host) return;
  var maxX = host.clientWidth;
  var maxY = host.clientHeight;
  if (!maxX || !maxY) return;
  var margin = 60;
  for (var i = 0; i < OBS_MDI.wins.length; i++) {
    var win = OBS_MDI.wins[i];
    if (win.maximized || win.minimized || !win.el) continue;
    var nx = win.x, ny = win.y;
    if (nx > maxX - margin) nx = maxX - margin;
    if (ny > maxY - 22) ny = maxY - 22;
    if (nx < margin - win.w) nx = margin - win.w;
    if (ny < 0) ny = 0;
    if (nx !== win.x || ny !== win.y) {
      win.x = nx; win.y = ny;
      win.el.style.left = nx + "px";
      win.el.style.top = ny + "px";
    }
  }
}

function obsMdiActivate(id) {
  var win = obsMdiFind(id);
  if (!win) return;
  if (win.minimized) {
    win.minimized = false;
    win.el.style.display = "flex";
  }
  if (OBS_MDI.activeId === id && OBS_MDI.owner[win.panel] === id) {
    win.el.style.zIndex = String(++OBS_MDI.z);
    obsMdiRender();
    return;
  }
  OBS_MDI.activeId = id;
  win.el.style.zIndex = String(++OBS_MDI.z);
  obsMdiAttachPanel(win);
  for (var i = 0; i < OBS_MDI.wins.length; i++) {
    OBS_MDI.wins[i].el.classList.toggle("active", OBS_MDI.wins[i].id === id);
  }
  obsMdiRender();
}

function obsMdiMinimize(id) {
  var win = obsMdiFind(id);
  if (!win) return;
  win.minimized = true;
  win.el.style.display = "none";
  if (OBS_MDI.activeId === id) {
    var next = null;
    for (var i = OBS_MDI.wins.length - 1; i >= 0; i--) {
      if (!OBS_MDI.wins[i].minimized) { next = OBS_MDI.wins[i]; break; }
    }
    OBS_MDI.activeId = next ? next.id : null;
    if (next) obsMdiActivate(next.id);
  }
  obsMdiRender();
}

function obsMdiToggleMax(id) {
  var win = obsMdiFind(id);
  if (!win) return;
  if (win.maximized) {
    win.maximized = false;
    win.el.classList.remove("maximized");
    win.el.style.left = win.px + "px";
    win.el.style.top = win.py + "px";
    win.el.style.width = win.pw + "px";
    win.el.style.height = win.ph + "px";
    win.x = win.px; win.y = win.py; win.w = win.pw; win.h = win.ph;
  } else {
    win.px = win.x; win.py = win.y; win.pw = win.w; win.ph = win.h;
    win.maximized = true;
    win.el.classList.add("maximized");
    win.el.style.left = "0px";
    win.el.style.top = "0px";
    win.el.style.width = "100%";
    win.el.style.height = "100%";
  }
  obsMdiActivate(id);
}

function obsMdiClose(id) {
  var win = obsMdiFind(id);
  if (!win) return;
  if (obsMdiIsDirty(win)) {
    var msg = obsMdiT("tabs.confirm.close",
      "Questa scheda contiene modifiche non salvate. Chiuderla comunque?");
    var title = obsMdiT("tabs.confirm.title", "Chiudi finestra");
    var okLabel = obsMdiT("tabs.confirm.ok", "Chiudi");
    if (typeof obsConfirm === "function") {
      obsConfirm(msg, title, okLabel).then(function (ok) {
        if (ok) obsMdiDoClose(id);
      });
      return;
    }
    if (!window.confirm(msg)) return;
  }
  obsMdiDoClose(id);
}

function obsMdiDoClose(id) {
  var win = obsMdiFind(id);
  if (!win) return;
  if (OBS_MDI.owner[win.panel] === id) {
    var el = obsMdiPanelEl(win.panel);
    var dock = document.getElementById("obsPanelDock");
    if (el && dock) { el.classList.remove("active"); dock.appendChild(el); }
    OBS_MDI.owner[win.panel] = null;
  }
  if (win.el && win.el.parentNode) win.el.parentNode.removeChild(win.el);
  var idx = -1;
  for (var i = 0; i < OBS_MDI.wins.length; i++) {
    if (OBS_MDI.wins[i].id === id) { idx = i; break; }
  }
  if (idx !== -1) OBS_MDI.wins.splice(idx, 1);
  if (OBS_MDI.activeId === id) OBS_MDI.activeId = null;
  if (!OBS_MDI.wins.length) {
    obsMdiExitMode();
    obsMdiRender();
    return;
  }
  var last = null;
  for (var j = OBS_MDI.wins.length - 1; j >= 0; j--) {
    if (!OBS_MDI.wins[j].minimized) { last = OBS_MDI.wins[j]; break; }
  }
  if (last) obsMdiActivate(last.id);
  obsMdiRender();
}

function obsMdiEnterMode() {
  document.body.classList.add("obs-mdi-mode");
  document.body.classList.remove("obs-intro-mode");
  var intro = document.getElementById("obsIntro");
  if (intro) intro.classList.add("hidden");
}

function obsMdiExitMode() {
  document.body.classList.remove("obs-mdi-mode");
  document.body.classList.add("obs-intro-mode");
  var intro = document.getElementById("obsIntro");
  if (intro) intro.classList.remove("hidden");
  window.OBS_ACTIVE_PANEL = null;
  document.querySelectorAll(".ntab").forEach(function (n) {
    n.classList.remove("active");
  });
}

function obsMdiRender() {
  var bar = document.getElementById("obsTaskbar");
  if (!bar) return;
  var html = "";
  for (var i = 0; i < OBS_MDI.wins.length; i++) {
    var win = OBS_MDI.wins[i];
    var cls = "obs-task";
    if (win.id === OBS_MDI.activeId && !win.minimized) cls += " active";
    if (win.minimized) cls += " minimized";
    html += '<div class="' + cls + '" onclick="obsMdiActivate(\'' + win.id + '\')" ' +
      'title="' + obsMdiEsc(win.label) + '">' +
      '<span class="obs-task-lbl">' + obsMdiEsc(win.label) + "</span></div>";
  }
  bar.innerHTML = html;
  document.querySelectorAll(".ntab").forEach(function (n) {
    n.classList.remove("active");
  });
  var act = obsMdiActive();
  if (act) {
    var nt = document.getElementById("tab-" + act.panel);
    if (nt) nt.classList.add("active");
  }
}

function obsMdiOnToolbar(panel) {
  if (OBS_MDI._internal) return false;
  obsMdiEnsureInit();
  var act = obsMdiActive();
  if (act && act.panel === panel && !act.minimized) return true;
  for (var i = 0; i < OBS_MDI.wins.length; i++) {
    if (OBS_MDI.wins[i].panel === panel && !OBS_MDI.wins[i].minimized) {
      obsMdiActivate(OBS_MDI.wins[i].id);
      return true;
    }
  }
  obsMdiNew(panel, true);
  return true;
}

function obsMdiRelabel() {
  for (var i = 0; i < OBS_MDI.wins.length; i++) {
    OBS_MDI.wins[i].label = obsMdiLabel(OBS_MDI.wins[i].panel);
    if (OBS_MDI.wins[i].nameEl) {
      OBS_MDI.wins[i].nameEl.textContent = OBS_MDI.wins[i].label;
    }
  }
  obsMdiRender();
}

if (typeof window !== "undefined") {
  window.addEventListener("resize", function () {
    if (typeof obsMdiClampAll === "function") obsMdiClampAll();
  });
}

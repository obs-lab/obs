var OBS_FS = {
  status: null,
  roots: [],
  path: "",
  parent: "",
  entries: [],
  file: null,
  busy: false,
  loaded: false
};

function obsFsFetch(url, options) {
  return fetch(url, options).then(function (r) {
    if (r.status === 204) return {};
    return r.json().then(function (data) {
      if (!r.ok) throw new Error(data && data.detail ? data.detail : "Request failed");
      return data;
    });
  });
}

function obsFsToast(message, type) {
  if (typeof toast === "function") toast(message, type);
}

function obsFsEsc(value) {
  if (typeof esc === "function") return esc(value);
  return String(value === undefined || value === null ? "" : value);
}

function obsFsSize(bytes) {
  if (!bytes) return "";
  var units = ["B", "KB", "MB", "GB"];
  var index = 0;
  var value = bytes;
  while (value >= 1024 && index < units.length - 1) {
    value = value / 1024;
    index = index + 1;
  }
  return (index === 0 ? value : value.toFixed(1)) + " " + units[index];
}

function initFsPanel() {
  if (OBS_FS.loaded) {
    obsFsLoadRoots();
    return;
  }
  OBS_FS.loaded = true;
  obsFsFetch("/api/fs/status").then(function (data) {
    OBS_FS.status = data;
    obsFsRenderStatus();
    if (!data.enabled) {
      var tree = document.getElementById("fsTree");
      if (tree) {
        tree.innerHTML = '<div class="ag-empty">The local files panel is disabled on this installation. ' +
          'Set OBS_FS_ENABLED=1 to turn it on.</div>';
      }
      return;
    }
    obsFsLoadRoots();
  }).catch(function (err) {
    obsFsToast(err.message, "error");
  });
}

function obsFsRenderStatus() {
  var host = document.getElementById("fsStatus");
  if (!host || !OBS_FS.status) return;
  var s = OBS_FS.status;
  var bits = [];
  bits.push(s.enabled ? "Read only, nothing is indexed" : "Disabled");
  bits.push("Max file size: " + obsFsSize(s.max_read_bytes));
  bits.push("Language model: " + obsFsEsc(s.llm_label));
  if (s.server_mode) bits.push("Server mode");
  host.textContent = bits.join("  |  ");
}

function obsFsLoadRoots() {
  obsFsFetch("/api/fs/roots").then(function (data) {
    OBS_FS.roots = data.roots || [];
    obsFsRenderRoots();
    if (!OBS_FS.path) obsFsBrowse("");
  }).catch(function (err) {
    obsFsToast(err.message, "error");
  });
}

function obsFsRenderRoots() {
  var host = document.getElementById("fsRoots");
  if (!host) return;
  if (!OBS_FS.roots.length) {
    host.innerHTML = '<div class="ag-empty">No folder registered. Add one below to let OBS read it.</div>';
    return;
  }
  host.innerHTML = OBS_FS.roots.map(function (root) {
    var cls = "fs-root" + (root.available ? "" : " gone");
    return '<div class="' + cls + '">' +
      '<span class="lb" onclick="obsFsBrowse(' + JSON.stringify(root.path).replace(/"/g, "&quot;") + ')">' +
      obsFsEsc(root.label) + '<span class="pt">' + obsFsEsc(root.path) + '</span></span>' +
      '<button class="fs-x" title="Remove" onclick="obsFsRemoveRoot(\'' + root.root_id + '\')">&times;</button>' +
      '</div>';
  }).join("");
}

function obsFsAddRoot() {
  var input = document.getElementById("fsNewRoot");
  var label = document.getElementById("fsNewLabel");
  if (!input || !input.value.trim()) {
    obsFsToast("Type the full path of the folder.", "error");
    return;
  }
  obsFsFetch("/api/fs/roots", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: input.value.trim(), label: label ? label.value.trim() : "" })
  }).then(function () {
    input.value = "";
    if (label) label.value = "";
    obsFsToast("Folder registered.", "success");
    obsFsLoadRoots();
  }).catch(function (err) {
    obsFsToast(err.message, "error");
  });
}

function obsFsRemoveRoot(rootId) {
  if (!window.confirm("Remove this folder from the allowed list?")) return;
  obsFsFetch("/api/fs/roots/" + rootId, { method: "DELETE" }).then(function () {
    OBS_FS.path = "";
    obsFsLoadRoots();
  }).catch(function (err) {
    obsFsToast(err.message, "error");
  });
}

function obsFsBrowse(path) {
  var url = "/api/fs/browse";
  if (path) url = url + "?path=" + encodeURIComponent(path);
  obsFsFetch(url).then(function (data) {
    OBS_FS.path = data.path || "";
    OBS_FS.parent = data.parent || "";
    OBS_FS.entries = data.entries || [];
    obsFsRenderTree(data);
  }).catch(function (err) {
    obsFsToast(err.message, "error");
  });
}

function obsFsUp() {
  if (OBS_FS.parent) {
    obsFsBrowse(OBS_FS.parent);
  } else {
    obsFsBrowse("");
  }
}

function obsFsRenderTree(data) {
  var pathBox = document.getElementById("fsPath");
  if (pathBox) pathBox.textContent = data.is_root_list ? "Registered folders" : data.path;
  var host = document.getElementById("fsTree");
  if (!host) return;
  if (!OBS_FS.entries.length) {
    host.innerHTML = '<div class="ag-empty">Nothing to show here.</div>';
    return;
  }
  host.innerHTML = OBS_FS.entries.map(function (entry) {
    var quoted = JSON.stringify(entry.path).replace(/"/g, "&quot;");
    var action = entry.is_dir ? "obsFsBrowse(" + quoted + ")" : "obsFsOpen(" + quoted + ")";
    var icon = entry.is_dir ? "[+]" : "[ ]";
    return '<div class="fs-row' + (entry.is_dir ? " dir" : "") + '" onclick="' + action + '">' +
      '<span class="ico">' + icon + '</span>' +
      '<span class="nm">' + obsFsEsc(entry.name) + '</span>' +
      '<span class="kd">' + obsFsEsc(entry.is_dir ? "" : entry.kind) + '</span>' +
      '<span class="sz">' + obsFsEsc(obsFsSize(entry.size)) + '</span></div>';
  }).join("");
  if (data.truncated) {
    host.innerHTML = host.innerHTML +
      '<div class="ag-empty">Listing truncated: this folder holds more entries than the panel shows.</div>';
  }
}

function obsFsSearch() {
  var pattern = document.getElementById("fsPattern");
  var contains = document.getElementById("fsContains");
  var body = {
    path: OBS_FS.path || null,
    pattern: pattern && pattern.value.trim() ? pattern.value.trim() : "*",
    contains: contains ? contains.value.trim() : "",
    max_results: 200
  };
  var host = document.getElementById("fsTree");
  if (host) host.innerHTML = '<div class="ag-empty">Scanning.</div>';
  obsFsFetch("/api/fs/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then(function (data) {
    OBS_FS.entries = data.results || [];
    obsFsRenderTree({ path: OBS_FS.path, is_root_list: false, truncated: data.truncated });
    var note = [];
    note.push(data.results.length + " match(es)");
    note.push(data.scanned + " file(s) scanned");
    if (data.timed_out) note.push("scan stopped at the safety limit");
    obsFsToast(note.join(", "), data.timed_out ? "error" : "success");
  }).catch(function (err) {
    obsFsToast(err.message, "error");
  });
}

function obsFsOpen(path) {
  obsFsFetch("/api/fs/read", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: path })
  }).then(function (data) {
    OBS_FS.file = data;
    obsFsRenderFile(data, "");
  }).catch(function (err) {
    obsFsToast(err.message, "error");
  });
}

function obsFsRenderFile(data, answer) {
  var head = document.getElementById("fsFileName");
  if (head) head.textContent = data.name;
  var host = document.getElementById("fsViewBody");
  if (!host) return;
  var parts = [];
  if (answer) {
    parts.push('<div class="fs-answer">' + obsFsEsc(answer) + '</div>');
    if (window.OBS_VOICE && OBS_VOICE.tts) {
      parts.push('<div class="ag-actions" style="margin-bottom:10px">' +
        '<button class="btn btng" onclick="obsVoiceSpeakText(document.querySelector(\'#fsViewBody .fs-answer\').textContent)">Read aloud</button></div>');
    }
  }
  parts.push('<div style="font-size:10px;color:var(--text3);margin-bottom:6px">' +
    obsFsEsc(data.path) + '  |  ' + obsFsEsc(obsFsSize(data.size)) + '  |  ' +
    obsFsEsc(data.kind) + (data.truncated ? "  |  truncated" : "") + '</div>');
  parts.push('<div class="fs-text">' + obsFsEsc(data.text) + '</div>');
  host.innerHTML = parts.join("");
}

function obsFsAnalyze() {
  if (!OBS_FS.file || OBS_FS.busy) {
    if (!OBS_FS.file) obsFsToast("Open a file first.", "error");
    return;
  }
  var question = document.getElementById("fsQuestion");
  var host = document.getElementById("fsViewBody");
  OBS_FS.busy = true;
  if (host) host.innerHTML = '<div class="ag-empty">Reading and analysing.</div>';
  obsFsFetch("/api/fs/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path: OBS_FS.file.path,
      question: question ? question.value.trim() : "",
      lang: "en"
    })
  }).then(function (data) {
    var payload = {
      name: data.name,
      path: data.path,
      size: OBS_FS.file.size,
      kind: OBS_FS.file.kind,
      truncated: data.truncated,
      text: data.text
    };
    obsFsRenderFile(payload, data.answer || data.note);
  }).catch(function (err) {
    obsFsToast(err.message, "error");
    if (OBS_FS.file) obsFsRenderFile(OBS_FS.file, "");
  }).then(function () {
    OBS_FS.busy = false;
  });
}

function obsFsClearView() {
  OBS_FS.file = null;
  var head = document.getElementById("fsFileName");
  if (head) head.textContent = "No file open";
  var host = document.getElementById("fsViewBody");
  if (host) {
    host.innerHTML = '<div class="ag-empty">Pick a file on the left. It is read from disk, ' +
      'never copied into the archive and never indexed.</div>';
  }
}

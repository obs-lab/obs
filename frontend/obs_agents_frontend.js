var OBS_AGENTS = {
  status: null,
  list: [],
  current: null,
  draft: null,
  runs: [],
  busy: false,
  loaded: false
};

function obsAgFetch(url, options) {
  return fetch(url, options).then(function (r) {
    if (r.status === 204) return {};
    return r.json().then(function (data) {
      if (!r.ok) throw new Error(data && data.detail ? data.detail : "Request failed");
      return data;
    });
  });
}

function obsAgToast(message, type) {
  if (typeof toast === "function") toast(message, type);
}

function obsAgEsc(value) {
  if (typeof esc === "function") return esc(value);
  return String(value === undefined || value === null ? "" : value);
}

function obsAgKindLabel(kind) {
  if (kind === "script") return "Script";
  if (kind === "assisted") return "Assisted";
  if (kind === "external") return "External";
  return kind;
}

function initAgentsPanel() {
  if (OBS_AGENTS.loaded) {
    obsAgentsLoadList();
    return;
  }
  OBS_AGENTS.loaded = true;
  obsAgFetch("/api/agents/status").then(function (data) {
    OBS_AGENTS.status = data;
    obsAgentsRenderStatus();
    obsAgentsLoadList();
  }).catch(function (err) {
    obsAgToast(err.message, "error");
  });
}

function obsAgentsRenderStatus() {
  var host = document.getElementById("agentStatus");
  if (!host || !OBS_AGENTS.status) return;
  var s = OBS_AGENTS.status;
  var bits = [];
  bits.push("Language model: " + obsAgEsc(s.llm_label));
  bits.push("Tools: " + (s.tools.length ? obsAgEsc(s.tools.join(", ")) : "none registered"));
  bits.push("External agents: " + (s.external_enabled ? "enabled" : "local targets only"));
  bits.push("Scheduler: " + (s.scheduler_enabled ? (s.scheduler_running ? "running" : "enabled") : "off"));
  host.textContent = bits.join("  |  ");
}

function obsAgentsLoadList() {
  obsAgFetch("/api/agents").then(function (data) {
    OBS_AGENTS.list = data.agents || [];
    obsAgentsRenderList();
    if (OBS_AGENTS.current) {
      var still = OBS_AGENTS.list.filter(function (a) {
        return a.agent_id === OBS_AGENTS.current.agent_id;
      });
      if (!still.length) obsAgentsClear();
    }
  }).catch(function (err) {
    obsAgToast(err.message, "error");
  });
}

function obsAgentsRenderList() {
  var host = document.getElementById("agentList");
  if (!host) return;
  if (!OBS_AGENTS.list.length) {
    host.innerHTML = '<div class="ag-empty">No agent yet. Create one from the buttons above.</div>';
    return;
  }
  var active = OBS_AGENTS.current ? OBS_AGENTS.current.agent_id : "";
  host.innerHTML = OBS_AGENTS.list.map(function (a) {
    var classes = "ag-item";
    if (a.agent_id === active) classes += " active";
    if (!a.enabled) classes += " off";
    var meta = obsAgKindLabel(a.kind);
    if (a.trigger === "interval") meta += " | every " + a.interval_s + "s";
    if (!a.enabled) meta += " | disabled";
    return '<div class="' + classes + '" onclick="obsAgentsSelect(\'' + a.agent_id + '\')">' +
      '<div class="ag-item-name">' + obsAgEsc(a.name) + '</div>' +
      '<div class="ag-item-meta">' + obsAgEsc(meta) + '</div></div>';
  }).join("");
}

function obsAgentsClear() {
  OBS_AGENTS.current = null;
  OBS_AGENTS.draft = null;
  OBS_AGENTS.runs = [];
  obsAgentsRenderList();
  var host = document.getElementById("agentMain");
  if (host) {
    host.innerHTML = '<div class="ag-empty">Select an agent on the left, or create a new one.</div>';
  }
}

function obsAgentsSelect(agentId) {
  obsAgFetch("/api/agents/" + agentId).then(function (agent) {
    OBS_AGENTS.current = agent;
    OBS_AGENTS.draft = null;
    obsAgentsRenderList();
    obsAgentsRenderEditor(agent);
    obsAgentsLoadRuns(agentId);
  }).catch(function (err) {
    obsAgToast(err.message, "error");
  });
}

function obsAgentsNew(kind) {
  var draft = {
    agent_id: null,
    name: "",
    kind: kind,
    description: "",
    trigger: "manual",
    interval_s: 300,
    enabled: true,
    config: {}
  };
  if (kind === "script") {
    draft.config = { language: "python", source: "", with_obs: true, input_mode: "stdin" };
  } else if (kind === "assisted") {
    draft.config = { objective: "", tools: [], max_steps: 6, lang: "en" };
  } else {
    draft.config = { url: "", method: "POST", headers: {}, timeout_s: 30 };
  }
  OBS_AGENTS.current = null;
  OBS_AGENTS.draft = draft;
  OBS_AGENTS.runs = [];
  obsAgentsRenderList();
  obsAgentsRenderEditor(draft);
}

function obsAgentsActive() {
  return OBS_AGENTS.draft || OBS_AGENTS.current;
}

function obsAgentsRenderEditor(agent) {
  var host = document.getElementById("agentMain");
  if (!host) return;
  var status = OBS_AGENTS.status || { languages: [], tools: [], scheduler_enabled: false, max_steps: 8 };
  var cfg = agent.config || {};
  var parts = [];

  parts.push('<div class="ag-card">');
  parts.push('<div class="ag-card-title">' + obsAgKindLabel(agent.kind) + ' agent</div>');
  parts.push(obsAgentsNoteFor(agent.kind));
  parts.push('<div class="ag-row">');
  parts.push('<div class="ag-field"><label>Name</label><input type="text" id="agName" value="' +
    obsAgEsc(agent.name) + '" placeholder="Weekly contract digest"></div>');
  parts.push('<div class="ag-field"><label>Description</label><input type="text" id="agDesc" value="' +
    obsAgEsc(agent.description) + '" placeholder="What this agent does"></div>');
  parts.push('</div>');

  if (agent.kind === "script") {
    var languages = status.languages || [];
    parts.push('<div class="ag-row">');
    parts.push('<div class="ag-field"><label>Language</label><select id="agLang">' +
      languages.map(function (l) {
        return '<option value="' + obsAgEsc(l) + '"' +
          (cfg.language === l ? " selected" : "") + '>' + obsAgEsc(l) + '</option>';
      }).join("") + '</select></div>');
    parts.push('<div class="ag-field"><label>Input</label><select id="agInputMode">' +
      '<option value="stdin"' + (cfg.input_mode !== "none" ? " selected" : "") + '>Pass input on stdin</option>' +
      '<option value="none"' + (cfg.input_mode === "none" ? " selected" : "") + '>Ignore input</option>' +
      '</select></div>');
    parts.push('</div>');
    parts.push('<div class="ag-field"><label><input type="checkbox" id="agWithObs"' +
      (cfg.with_obs === false ? "" : " checked") + '> Give the sandbox an OBS access token</label>' +
      '<div class="hint">The token lives for 120 seconds and carries only your own permissions.</div></div>');
    parts.push('<div class="ag-field"><label>Source</label><textarea id="agSource" class="code" spellcheck="false">' +
      obsAgEsc(cfg.source || "") + '</textarea></div>');
  } else if (agent.kind === "assisted") {
    var tools = status.tools || [];
    var chosen = cfg.tools || [];
    parts.push('<div class="ag-field"><label>Objective</label><textarea id="agObjective" placeholder="Find every supplier mentioned in the archive and group them by organisation.">' +
      obsAgEsc(cfg.objective || "") + '</textarea></div>');
    parts.push('<div class="ag-field"><label>Tools</label><div class="ag-tools">' +
      (tools.length ? tools.map(function (t) {
        var on = chosen.indexOf(t) !== -1 || !chosen.length;
        return '<label><input type="checkbox" class="ag-tool" value="' + obsAgEsc(t) + '"' +
          (on ? " checked" : "") + '> ' + obsAgEsc(t) + '</label>';
      }).join("") : '<span class="hint">No tool registered on the backend.</span>') +
      '</div></div>');
    parts.push('<div class="ag-row">');
    parts.push('<div class="ag-field"><label>Maximum steps</label><input type="number" id="agSteps" min="1" max="' +
      (status.max_steps || 16) + '" value="' + (cfg.max_steps || 6) + '"></div>');
    parts.push('<div class="ag-field"><label>Prompt language</label><select id="agPromptLang">' +
      '<option value="en"' + (cfg.lang !== "it" ? " selected" : "") + '>English</option>' +
      '<option value="it"' + (cfg.lang === "it" ? " selected" : "") + '>Italian</option>' +
      '</select></div>');
    parts.push('</div>');
  } else {
    parts.push('<div class="ag-field"><label>Endpoint</label><input type="text" id="agUrl" value="' +
      obsAgEsc(cfg.url || "") + '" placeholder="http://127.0.0.1:5001/run">' +
      '<div class="hint">Loopback and private network addresses work out of the box. Public hosts need OBS_AGENTS_EXTERNAL.</div></div>');
    parts.push('<div class="ag-row">');
    parts.push('<div class="ag-field"><label>Method</label><select id="agMethod">' +
      '<option value="POST"' + (cfg.method !== "GET" ? " selected" : "") + '>POST</option>' +
      '<option value="GET"' + (cfg.method === "GET" ? " selected" : "") + '>GET</option>' +
      '</select></div>');
    parts.push('<div class="ag-field"><label>Timeout (s)</label><input type="number" id="agTimeout" min="1" max="60" value="' +
      (cfg.timeout_s || 30) + '"></div>');
    parts.push('</div>');
    parts.push('<div class="ag-field"><label>Headers (one per line, name: value)</label><textarea id="agHeaders" spellcheck="false">' +
      obsAgEsc(obsAgentsHeadersToText(cfg.headers)) + '</textarea></div>');
  }

  parts.push('<div class="ag-row">');
  parts.push('<div class="ag-field"><label>Trigger</label><select id="agTrigger" onchange="obsAgentsToggleInterval()">' +
    '<option value="manual"' + (agent.trigger !== "interval" ? " selected" : "") + '>Manual</option>' +
    '<option value="interval"' + (agent.trigger === "interval" ? " selected" : "") + '>Every N seconds</option>' +
    '</select>' + (status.scheduler_enabled ? "" :
      '<div class="hint">The scheduler is off. Set OBS_AGENTS_SCHEDULER=1 to use periodic triggers.</div>') +
    '</div>');
  parts.push('<div class="ag-field" id="agIntervalField"><label>Interval (s)</label><input type="number" id="agInterval" min="' +
    (status.min_interval_s || 60) + '" value="' + (agent.interval_s || 300) + '"></div>');
  parts.push('</div>');

  parts.push('<div class="ag-actions">');
  parts.push('<button class="btn btng" onclick="obsAgentsSave()">Save</button>');
  if (agent.agent_id) {
    parts.push('<button class="btn btng" onclick="obsAgentsToggleEnabled()">' +
      (agent.enabled ? "Disable" : "Enable") + '</button>');
    parts.push('<button class="btn btng" onclick="obsAgentsDelete()">Delete</button>');
  }
  parts.push('</div>');
  parts.push('</div>');

  if (agent.agent_id) {
    parts.push('<div class="ag-card">');
    parts.push('<div class="ag-card-title">Run</div>');
    parts.push('<div class="ag-field"><label>Input</label><input type="text" id="agInput" placeholder="Optional text handed to the agent"></div>');
    parts.push('<div class="ag-actions"><button class="btn btng" id="agRunBtn" onclick="obsAgentsRun()">Run now</button></div>');
    parts.push('<div id="agResult" style="margin-top:10px"></div>');
    parts.push('</div>');
    parts.push('<div class="ag-card">');
    parts.push('<div class="ag-card-title">History</div>');
    parts.push('<div id="agRuns"><div class="ag-empty">No run recorded yet.</div></div>');
    parts.push('</div>');
  }

  host.innerHTML = parts.join("");
  obsAgentsToggleInterval();
}

function obsAgentsNoteFor(kind) {
  if (kind === "script") {
    return '<div class="ag-note">Runs your own code in a disposable container, with no access to the host. ' +
      'Same sandbox as the Code panel.</div>';
  }
  if (kind === "assisted") {
    return '<div class="ag-note">Works in steps: at each step the language model either calls one of the ' +
      'listed tools or returns a final answer. Every step is recorded in the run trace. ' +
      'Requires an active language model.</div>';
  }
  return '<div class="ag-note">Calls an agent you built elsewhere over HTTP. OBS sends a JSON body with ' +
    'the agent name, your input and your organisation, and shows whatever comes back.</div>';
}

function obsAgentsHeadersToText(headers) {
  if (!headers) return "";
  return Object.keys(headers).map(function (k) {
    return k + ": " + headers[k];
  }).join("\n");
}

function obsAgentsTextToHeaders(text) {
  var out = {};
  (text || "").split("\n").forEach(function (line) {
    var idx = line.indexOf(":");
    if (idx <= 0) return;
    var key = line.slice(0, idx).trim();
    var value = line.slice(idx + 1).trim();
    if (key) out[key] = value;
  });
  return out;
}

function obsAgentsToggleInterval() {
  var trigger = document.getElementById("agTrigger");
  var field = document.getElementById("agIntervalField");
  if (!trigger || !field) return;
  field.style.display = trigger.value === "interval" ? "" : "none";
}

function obsAgentsCollect() {
  var agent = obsAgentsActive();
  if (!agent) return null;
  var value = function (id) {
    var el = document.getElementById(id);
    return el ? el.value : "";
  };
  var payload = {
    agent_id: agent.agent_id,
    name: value("agName").trim(),
    kind: agent.kind,
    description: value("agDesc").trim(),
    trigger: value("agTrigger") || "manual",
    interval_s: parseInt(value("agInterval") || "0", 10) || 0,
    enabled: agent.enabled !== false,
    config: {}
  };
  if (agent.kind === "script") {
    var withObs = document.getElementById("agWithObs");
    payload.config = {
      language: value("agLang"),
      source: value("agSource"),
      with_obs: withObs ? withObs.checked : true,
      input_mode: value("agInputMode")
    };
  } else if (agent.kind === "assisted") {
    var picked = [];
    Array.prototype.forEach.call(document.querySelectorAll(".ag-tool"), function (box) {
      if (box.checked) picked.push(box.value);
    });
    payload.config = {
      objective: value("agObjective"),
      tools: picked,
      max_steps: parseInt(value("agSteps") || "6", 10) || 6,
      lang: value("agPromptLang")
    };
  } else {
    payload.config = {
      url: value("agUrl").trim(),
      method: value("agMethod"),
      timeout_s: parseInt(value("agTimeout") || "30", 10) || 30,
      headers: obsAgentsTextToHeaders(value("agHeaders"))
    };
  }
  return payload;
}

function obsAgentsSave() {
  var payload = obsAgentsCollect();
  if (!payload) return;
  if (!payload.name) {
    obsAgToast("The agent needs a name.", "error");
    return;
  }
  obsAgFetch("/api/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).then(function (agent) {
    OBS_AGENTS.draft = null;
    OBS_AGENTS.current = agent;
    obsAgToast("Agent saved.", "success");
    obsAgentsLoadList();
    obsAgentsRenderEditor(agent);
    obsAgentsLoadRuns(agent.agent_id);
  }).catch(function (err) {
    obsAgToast(err.message, "error");
  });
}

function obsAgentsToggleEnabled() {
  var agent = OBS_AGENTS.current;
  if (!agent) return;
  obsAgFetch("/api/agents/" + agent.agent_id, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: !agent.enabled })
  }).then(function (updated) {
    OBS_AGENTS.current = updated;
    obsAgentsLoadList();
    obsAgentsRenderEditor(updated);
  }).catch(function (err) {
    obsAgToast(err.message, "error");
  });
}

function obsAgentsDelete() {
  var agent = OBS_AGENTS.current;
  if (!agent) return;
  if (!window.confirm("Delete the agent " + agent.name + " and its history?")) return;
  obsAgFetch("/api/agents/" + agent.agent_id, { method: "DELETE" }).then(function () {
    obsAgToast("Agent deleted.", "success");
    obsAgentsClear();
    obsAgentsLoadList();
  }).catch(function (err) {
    obsAgToast(err.message, "error");
  });
}

function obsAgentsRun() {
  var agent = OBS_AGENTS.current;
  if (!agent || OBS_AGENTS.busy) return;
  var input = document.getElementById("agInput");
  var button = document.getElementById("agRunBtn");
  var result = document.getElementById("agResult");
  OBS_AGENTS.busy = true;
  if (button) {
    button.disabled = true;
    button.textContent = "Running";
  }
  if (result) result.innerHTML = '<div class="ag-empty">Working.</div>';

  obsAgFetch("/api/agents/" + agent.agent_id + "/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input: input ? input.value : "" })
  }).then(function (data) {
    obsAgentsRenderResult(data);
    obsAgentsLoadRuns(agent.agent_id);
  }).catch(function (err) {
    if (result) {
      result.innerHTML = '<div class="ag-out">' + obsAgEsc(err.message) + '</div>';
    }
    obsAgToast(err.message, "error");
  }).then(function () {
    OBS_AGENTS.busy = false;
    if (button) {
      button.disabled = false;
      button.textContent = "Run now";
    }
  });
}

function obsAgentsStatusBadge(status) {
  var cls = "wait";
  if (status === "ok") cls = "ok";
  if (status === "error" || status === "timeout") cls = "err";
  return '<span class="ag-badge ' + cls + '">' + obsAgEsc(status) + '</span>';
}

function obsAgentsRenderResult(data) {
  var host = document.getElementById("agResult");
  if (!host) return;
  var parts = [];
  parts.push('<div style="font-size:11px;margin-bottom:6px">Result' +
    obsAgentsStatusBadge(data.status) +
    '<span class="ag-badge">' + (data.steps || 0) + ' step(s)</span></div>');
  if (data.output) parts.push('<div class="ag-out">' + obsAgEsc(data.output) + '</div>');
  if (data.error) parts.push('<div class="ag-out" style="border-color:#b08a8a">' + obsAgEsc(data.error) + '</div>');
  if (data.trace && data.trace.length) {
    parts.push('<div class="ag-trace">' + data.trace.map(function (step) {
      return obsAgEsc(JSON.stringify(step));
    }).join("<br>") + '</div>');
  }
  if (data.output && window.OBS_VOICE && OBS_VOICE.tts) {
    parts.push('<div class="ag-actions"><button class="btn btng" onclick="obsVoiceSpeakText(document.querySelector(\'#agResult .ag-out\').textContent)">Read aloud</button></div>');
  }
  host.innerHTML = parts.join("");
}

function obsAgentsLoadRuns(agentId) {
  obsAgFetch("/api/agents/" + agentId + "/runs?limit=25").then(function (data) {
    OBS_AGENTS.runs = data.runs || [];
    var host = document.getElementById("agRuns");
    if (!host) return;
    if (!OBS_AGENTS.runs.length) {
      host.innerHTML = '<div class="ag-empty">No run recorded yet.</div>';
      return;
    }
    host.innerHTML = OBS_AGENTS.runs.map(function (run) {
      var when = new Date(run.started_at * 1000).toLocaleString();
      return '<div class="ag-runrow" onclick="obsAgentsShowRun(\'' + run.run_id + '\')">' +
        '<span class="rid">' + obsAgEsc(run.run_id.slice(0, 8)) + '</span>' +
        '<span style="flex:1">' + obsAgEsc(when) + '</span>' +
        '<span>' + obsAgEsc(run.trigger) + '</span>' +
        obsAgentsStatusBadge(run.status) + '</div>';
    }).join("");
  }).catch(function (err) {
    obsAgToast(err.message, "error");
  });
}

function obsAgentsShowRun(runId) {
  obsAgFetch("/api/agents/runs/" + runId).then(function (run) {
    obsAgentsRenderResult(run);
  }).catch(function (err) {
    obsAgToast(err.message, "error");
  });
}

(function(){
  "use strict";

  var OBS_AUTH = { user: null };

  function api(path, opts){
    opts = opts || {};
    opts.credentials = "same-origin";
    opts.headers = opts.headers || {};
    if(opts.body && typeof opts.body !== "string"){
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(path, opts);
  }

  function gotoLogin(){ window.location.href = "/login"; }

  function checkSession(){
    return api("/api/auth/me").then(function(r){
      if(!r.ok){ gotoLogin(); return null; }
      return r.json();
    }).then(function(u){
      if(u){ OBS_AUTH.user = u; renderUserBar(u); maybeShowAdmin(u); }
      return u;
    }).catch(function(){ gotoLogin(); });
  }

  function doLogout(){
    api("/api/auth/logout", {method:"POST"}).then(function(){ gotoLogin(); })
      .catch(function(){ gotoLogin(); });
  }

  function renderUserBar(u){
    var existing = document.getElementById("obsUserBar");
    if(existing) existing.remove();
    var bar = document.createElement("div");
    bar.id = "obsUserBar";
    bar.style.cssText = "position:fixed;top:7px;right:200px;z-index:9999;display:flex;"
      + "align-items:center;gap:14px;font-family:Tahoma,sans-serif;font-size:11px;color:#d6dce2";
    var label = document.createElement("span");
    label.textContent = u.username + " (" + u.role + ")";
    label.style.cssText = "color:#8aaccb;white-space:nowrap";
    bar.appendChild(label);

    if(u.role === "developer" || u.role === "admin"){
      var usersBtn = document.createElement("button");
      usersBtn.id = "obsAdminOpenBtn";
      usersBtn.textContent = "Users";
      usersBtn.style.cssText = "padding:3px 14px;border:1px solid #28323d;background:#33404e;"
        + "color:#d6dce2;font-family:Tahoma,sans-serif;font-size:11px;font-weight:bold;cursor:pointer;"
        + "white-space:nowrap";
      bar.appendChild(usersBtn);
    }

    var modelsBtn = document.createElement("button");
    modelsBtn.id = "obsModelsOpenBtn";
    modelsBtn.textContent = "Models";
    modelsBtn.style.cssText = "padding:3px 14px;border:1px solid #28323d;background:#33404e;"
      + "color:#d6dce2;font-family:Tahoma,sans-serif;font-size:11px;font-weight:bold;cursor:pointer;"
      + "white-space:nowrap";
    bar.appendChild(modelsBtn);

    var btn = document.createElement("button");
    btn.textContent = "Log out";
    btn.style.cssText = "padding:3px 14px;border:1px solid #28323d;background:#2f5fa6;color:#fff;"
      + "font-family:Tahoma,sans-serif;font-size:11px;font-weight:bold;cursor:pointer;white-space:nowrap";
    btn.onclick = doLogout;
    bar.appendChild(btn);
    document.body.appendChild(bar);
    setupModelsPanel(u);
  }

  function maybeShowAdmin(u){
    if(u.role !== "developer" && u.role !== "admin") return;
    var panel = document.getElementById("obsAdminPanel");
    if(!panel){
      panel = buildAdminPanel(u);
      document.body.appendChild(panel);
    }
    var openBtn = document.getElementById("obsAdminOpenBtn");
    if(openBtn && !openBtn.dataset.bound){
      openBtn.dataset.bound = "1";
      openBtn.onclick = function(){
        panel.style.display = (panel.style.display === "none") ? "block" : "none";
        if(panel.style.display === "block") loadUsers();
      };
    }
  }

  function buildAdminPanel(u){
    var panel = document.createElement("div");
    panel.id = "obsAdminPanel";
    panel.style.cssText = "position:fixed;top:34px;right:12px;width:560px;max-height:78vh;overflow:auto;"
      + "z-index:9998;background:#fff;border:1px solid #787878;box-shadow:0 6px 28px rgba(0,0,0,0.3);"
      + "font-family:Tahoma,sans-serif;font-size:12px;display:none";
    panel.innerHTML =
      '<div style="background:#3f4d5e;color:#d6dce2;padding:10px 14px;font-weight:bold">User management</div>'
      + '<div style="padding:14px">'
      + '  <div style="font-size:11px;font-weight:bold;margin-bottom:8px;color:#3a3a3a">New user</div>'
      + '  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px">'
      + '    <input id="obsNuEmail" placeholder="email" style="padding:6px;border:1px solid #9a9a9a">'
      + '    <input id="obsNuUser" placeholder="username" style="padding:6px;border:1px solid #9a9a9a">'
      + '    <input id="obsNuPw" placeholder="temporary password" style="padding:6px;border:1px solid #9a9a9a">'
      + '    <input id="obsNuAz" placeholder="company" style="padding:6px;border:1px solid #9a9a9a">'
      + '  </div>'
      + '  <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">'
      + '    <select id="obsNuRole" style="padding:6px;border:1px solid #9a9a9a"></select>'
      + '    <button id="obsNuBtn" style="padding:6px 14px;border:1px solid #28323d;background:#2f5fa6;color:#fff;font-weight:bold;cursor:pointer">Create</button>'
      + '    <span id="obsNuMsg" style="font-size:11px"></span>'
      + '  </div>'
      + '  <div style="font-size:11px;font-weight:bold;margin:12px 0 6px;color:#3a3a3a">Registered users</div>'
      + '  <div id="obsUserList"></div>'
      + '</div>';
    return panel;
  }

  function loadUsers(){
    var roleSel = document.getElementById("obsNuRole");
    if(roleSel && !roleSel.dataset.filled){
      var roles = (OBS_AUTH.user.role === "developer")
        ? ["user","admin","developer"] : ["user"];
      roleSel.innerHTML = roles.map(function(r){ return '<option value="'+r+'">'+r+'</option>'; }).join("");
      roleSel.dataset.filled = "1";
      document.getElementById("obsNuBtn").onclick = createUser;
    }
    api("/api/auth/users").then(function(r){ return r.json(); }).then(function(users){
      renderUserList(users);
    });
  }

  var _userCache = {};

  function renderUserList(users){
    var box = document.getElementById("obsUserList");
    if(!users || !users.length){ box.innerHTML = '<div style="color:#6b6b6b">No users.</div>'; return; }
    _userCache = {};
    users.forEach(function(u){ _userCache[u.id] = u; });
    var activeDevs = users.filter(function(u){ return u.role === "developer" && u.active; }).length;
    var rows = users.map(function(u){
      var locked = u.locked ? ' <span style="color:#b03a2e">[locked]</span>' : '';
      var inactive = u.active ? '' : ' <span style="color:#b03a2e">[inactive]</span>';
      var isLastDev = u.role === "developer" && u.active && activeDevs <= 1;
      var actions =
        '<button data-act="edit" data-id="'+u.id+'" style="margin-right:4px;cursor:pointer">Edit</button>'
        + '<button data-act="reset" data-id="'+u.id+'" style="margin-right:4px;cursor:pointer">Reset pw</button>'
        + (u.locked ? '<button data-act="unlock" data-id="'+u.id+'" style="margin-right:4px;cursor:pointer">Unlock</button>' : '')
        + (u.active
            ? (isLastDev ? '' : '<button data-act="deact" data-id="'+u.id+'" style="margin-right:4px;cursor:pointer">Deactivate</button>')
            : '<button data-act="act" data-id="'+u.id+'" style="margin-right:4px;cursor:pointer">Activate</button>')
        + (isLastDev ? '' : '<button data-act="del" data-id="'+u.id+'" style="color:#b03a2e;cursor:pointer">Delete</button>');
      var lastDevNote = isLastDev ? ' <span style="color:#888;font-size:12px">(last developer, protected)</span>' : '';
      return '<div style="padding:7px 0;border-bottom:1px solid #eee" data-urow="'+u.id+'">'
        + '<div><b>'+esc(u.email)+'</b> ('+esc(u.role)+') - '+esc(u.username)
        + (u.azienda ? ' / '+esc(u.azienda) : '')
        + (u.initials ? ' <span style="color:#888">['+esc(u.initials)+']</span>' : '')
        + locked + inactive + lastDevNote + '</div>'
        + '<div style="margin-top:4px">'+actions+'</div></div>';
    }).join("");
    box.innerHTML = rows;
    box.querySelectorAll("button[data-act]").forEach(function(b){
      b.onclick = function(){ userAction(b.getAttribute("data-act"), parseInt(b.getAttribute("data-id"),10)); };
    });
  }

  function uiConfirm(message, title){
    if(typeof window.obsConfirm === "function"){ return window.obsConfirm(message, title); }
    return Promise.resolve(window.confirm(message));
  }
  function uiPrompt(message, value, title){
    if(typeof window.obsPrompt === "function"){ return window.obsPrompt(message, value, title); }
    return Promise.resolve(window.prompt(message, value || ""));
  }
  function uiToast(message, kind){
    if(typeof window.toast === "function"){ window.toast(message, kind || "info"); return; }
    if(kind === "error"){ alert(message); }
  }

  function userAction(act, id){
    if(act === "edit"){
      openEditForm(id);
      return;
    }
    if(act === "reset"){
      uiPrompt("New temporary password (min 6 characters):", "", "Reset password").then(function(pw){
        if(pw === null) return;
        pw = (pw || "").trim();
        if(pw.length < 6){ uiToast("Password must be at least 6 characters.", "error"); return; }
        api("/api/auth/users/reset-password", {method:"POST", body:{user_id:id, temp_password:pw}})
          .then(handleResp());
      });
    } else if(act === "unlock"){
      api("/api/auth/users/unlock", {method:"POST", body:{user_id:id}}).then(handleResp());
    } else if(act === "deact"){
      api("/api/auth/users/set-active", {method:"POST", body:{user_id:id, active:false}}).then(handleResp());
    } else if(act === "act"){
      api("/api/auth/users/set-active", {method:"POST", body:{user_id:id, active:true}}).then(handleResp());
    } else if(act === "del"){
      uiConfirm("Permanently delete this user? This cannot be undone.", "Delete user").then(function(ok){
        if(!ok) return;
        api("/api/auth/users/delete", {method:"POST", body:{user_id:id}}).then(handleResp());
      });
    }
  }

  function openEditForm(id){
    var u = _userCache[id];
    if(!u){ return; }
    var row = document.querySelector('[data-urow="'+id+'"]');
    if(!row){ return; }
    var existing = row.querySelector(".obs-edit-form");
    if(existing){ existing.remove(); return; }
    var isDev = OBS_AUTH.user && OBS_AUTH.user.role === "developer";
    var roleField = "";
    if(isDev){
      var opts = ["user","admin","developer"].map(function(r){
        return '<option value="'+r+'"'+(r===u.role?' selected':'')+'>'+r+'</option>';
      }).join("");
      roleField = '<label style="display:block;margin-top:6px">Role '
        + '<select id="ed-role-'+id+'">'+opts+'</select></label>'
        + '<label style="display:block;margin-top:6px">Active '
        + '<input type="checkbox" id="ed-active-'+id+'"'+(u.active?' checked':'')+'></label>';
    }
    var html = '<div class="obs-edit-form" style="margin-top:8px;padding:8px;background:#f7f7f7;border:1px solid #e0e0e0;border-radius:6px">'
      + '<label style="display:block;margin-bottom:6px">Email <input id="ed-email-'+id+'" value="'+esc(u.email)+'" style="width:100%"></label>'
      + '<label style="display:block;margin-bottom:6px">Username <input id="ed-user-'+id+'" value="'+esc(u.username)+'" style="width:100%"></label>'
      + '<label style="display:block;margin-bottom:6px">Company <input id="ed-az-'+id+'" value="'+esc(u.azienda||"")+'" style="width:100%"></label>'
      + '<label style="display:block;margin-bottom:6px">Initials <input id="ed-ini-'+id+'" value="'+esc(u.initials||"")+'" maxlength="3" style="width:80px"></label>'
      + roleField
      + '<div style="margin-top:8px"><button id="ed-save-'+id+'" style="margin-right:6px;cursor:pointer">Save</button>'
      + '<button id="ed-cancel-'+id+'" style="cursor:pointer">Cancel</button></div>'
      + '<div id="ed-msg-'+id+'" style="margin-top:6px;font-size:12px"></div></div>';
    row.insertAdjacentHTML("beforeend", html);
    document.getElementById("ed-save-"+id).onclick = function(){ submitEdit(id, isDev); };
    document.getElementById("ed-cancel-"+id).onclick = function(){
      var f = row.querySelector(".obs-edit-form"); if(f){ f.remove(); }
    };
  }

  function submitEdit(id, isDev){
    var body = {
      user_id: id,
      email: val("ed-email-"+id),
      username: val("ed-user-"+id),
      azienda: val("ed-az-"+id),
      initials: val("ed-ini-"+id)
    };
    if(isDev){
      body.role = val("ed-role-"+id);
      var chk = document.getElementById("ed-active-"+id);
      body.active = chk ? chk.checked : undefined;
    }
    var msg = document.getElementById("ed-msg-"+id);
    api("/api/auth/users/update", {method:"POST", body:body}).then(function(r){
      return r.json().then(function(d){ return {ok:r.ok, d:d}; });
    }).then(function(res){
      if(!res.ok){ msg.textContent = res.d.detail || "Error."; msg.style.color="#b03a2e"; return; }
      msg.textContent = "Saved."; msg.style.color="#3f8f3f";
      loadUsers();
    }).catch(function(){ msg.textContent = "Network error."; msg.style.color="#b03a2e"; });
  }

  function handleResp(){
    return function(r){
      return r.json().then(function(d){
        if(!r.ok){ uiToast(d.detail || "Operation failed.", "error"); return; }
        loadUsers();
      });
    };
  }

  function createUser(){
    var body = {
      email: val("obsNuEmail"), username: val("obsNuUser"),
      password: val("obsNuPw"), role: val("obsNuRole"), azienda: val("obsNuAz")
    };
    var msg = document.getElementById("obsNuMsg");
    api("/api/auth/users", {method:"POST", body:body}).then(function(r){
      return r.json().then(function(d){ return {ok:r.ok, d:d}; });
    }).then(function(res){
      if(!res.ok){ msg.textContent = res.d.detail || "Error."; msg.style.color="#b03a2e"; return; }
      msg.textContent = "Created."; msg.style.color="#3f8f3f";
      ["obsNuEmail","obsNuUser","obsNuPw","obsNuAz"].forEach(function(k){ document.getElementById(k).value=""; });
      loadUsers();
    });
  }

  function val(id){ return document.getElementById(id).value.trim(); }
  function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }

  function setupModelsPanel(u){
    var isAdmin = (u.role === "developer" || u.role === "admin");
    var panel = document.getElementById("obsModelsPanel");
    if(!panel){
      panel = document.createElement("div");
      panel.id = "obsModelsPanel";
      panel.style.cssText = "position:fixed;top:44px;right:16px;z-index:10000;width:420px;"
        + "background:#f4f5f7;border:1px solid #26303a;border-radius:4px;display:none;"
        + "font-family:Tahoma,sans-serif;color:#2a2a2a;box-shadow:0 6px 24px rgba(0,0,0,0.3)";
      panel.innerHTML =
          '<div style="background:#26303a;color:#e6ecf2;padding:8px 12px;font-size:12px;'
        + 'font-weight:bold;border-radius:4px 4px 0 0">Models</div>'
        + '<div style="padding:12px" id="obsModelsBody">'
        + '  <div style="font-size:11px;color:#555;margin-bottom:10px">'
        + '    Optional components used by some panels. They are downloaded on demand and '
        + '    stored on this machine. After a download or a removal, restart OBS to apply.'
        + '  </div>'
        + '  <div id="obsModelSpacy" style="border:1px solid #ccc;background:#fff;padding:10px;margin-bottom:8px">'
        + '    <div style="font-size:12px;font-weight:bold;color:#2b1c3f">Entity analysis model</div>'
        + '    <div style="font-size:11px;color:#666;margin:2px 0 8px">Italian NER model (it_core_news_lg, about 600 MB). '
        + '        Needed by the Investigate and Entities panels.</div>'
        + '    <div id="obsSpacyStatus" style="font-size:11px;margin-bottom:8px">Checking...</div>'
        + '    <div id="obsSpacyActions"></div>'
        + '    <div id="obsSpacyMsg" style="font-size:11px;margin-top:6px"></div>'
        + '  </div>'
        + '  <div id="obsModelClip" style="border:1px solid #ccc;background:#fff;padding:10px;margin-bottom:8px">'
        + '    <div style="font-size:12px;font-weight:bold;color:#2b1c3f">Image analysis model</div>'
        + '    <div style="font-size:11px;color:#666;margin:2px 0 8px">CLIP model (clip-ViT-B-32, about 600 MB). '
        + '        Used to search and cluster images by visual content.</div>'
        + '    <div id="obsClipStatus" style="font-size:11px;margin-bottom:8px">Checking...</div>'
        + '    <div id="obsClipActions"></div>'
        + '    <div id="obsClipMsg" style="font-size:11px;margin-top:6px"></div>'
        + '  </div>'
        + '  <div style="border:1px solid #ccc;background:#fbfbf5;padding:10px;margin-bottom:8px">'
        + '    <div style="font-size:12px;font-weight:bold;color:#2b1c3f">Text in images (OCR)</div>'
        + '    <div style="font-size:11px;color:#666;margin:2px 0 6px">Reading text inside images needs '
        + '        Tesseract, a free program installed on your system. OBS finds it automatically once installed.</div>'
        + '    <div style="font-size:11px;color:#444">Install on macOS with Homebrew:</div>'
        + '    <div style="font-family:monospace;font-size:11px;background:#f0f0f0;padding:5px 7px;margin:4px 0">brew install tesseract tesseract-lang</div>'
        + '    <div style="font-size:11px;color:#666">After installing, restart OBS. No download is needed inside OBS.</div>'
        + '  </div>'
        + '  <div style="border:1px solid #ccc;background:#fbfbf5;padding:10px;margin-bottom:8px">'
        + '    <div style="font-size:12px;font-weight:bold;color:#2b1c3f">Code execution (Docker)</div>'
        + '    <div style="font-size:11px;color:#666;margin:2px 0 6px">Running code in the Code panel needs '
        + '        Docker Desktop, a free program. OBS finds it automatically once installed and running.</div>'
        + '    <div style="font-size:11px;color:#444">Download Docker Desktop from:</div>'
        + '    <div style="font-family:monospace;font-size:11px;background:#f0f0f0;padding:5px 7px;margin:4px 0">https://www.docker.com/products/docker-desktop</div>'
        + '    <div style="font-size:11px;color:#666">Install it, start it, then restart OBS. Docker must be running when you use the Code panel.</div>'
        + '  </div>'
        + '  <div style="text-align:right;margin-top:6px">'
        + '    <button id="obsModelsClose" style="padding:4px 14px;border:1px solid #9a9a9a;'
        + 'background:#e2e2e2;font-size:11px;cursor:pointer">Close</button>'
        + '  </div>'
        + '</div>';
      document.body.appendChild(panel);
      panel.querySelector("#obsModelsClose").onclick = function(){ panel.style.display = "none"; };
    }
    panel.dataset.admin = isAdmin ? "1" : "0";

    var openBtn = document.getElementById("obsModelsOpenBtn");
    if(openBtn && !openBtn.dataset.bound){
      openBtn.dataset.bound = "1";
      openBtn.onclick = function(){
        panel.style.display = (panel.style.display === "none" || !panel.style.display) ? "block" : "none";
        if(panel.style.display === "block"){ refreshSpacy(); refreshClip(); }
      };
    }
  }

  function spacyMsg(text, color){
    var m = document.getElementById("obsSpacyMsg");
    if(m){ m.textContent = text || ""; m.style.color = color || "#666"; }
  }

  function refreshSpacy(){
    var statusEl = document.getElementById("obsSpacyStatus");
    var actEl = document.getElementById("obsSpacyActions");
    if(!statusEl || !actEl) return;
    api("/api/spacy/status").then(function(r){ return r.json(); }).then(function(s){
      var isAdmin = document.getElementById("obsModelsPanel").dataset.admin === "1";
      if(s.status === "running"){
        statusEl.textContent = "Downloading...";
        statusEl.style.color = "#b06e00";
        actEl.innerHTML = "";
        setTimeout(refreshSpacy, 2000);
        return;
      }
      if(s.ready){
        statusEl.textContent = "Installed.";
        statusEl.style.color = "#2b7a2b";
        if(isAdmin){
          actEl.innerHTML = '<button id="obsSpacyRemove" style="padding:5px 14px;border:1px solid #a33;'
            + 'background:#f3dede;color:#8a2020;font-size:11px;cursor:pointer">Remove</button>';
          document.getElementById("obsSpacyRemove").onclick = removeSpacy;
        } else {
          actEl.innerHTML = '<span style="font-size:11px;color:#888">Ask an administrator to remove it.</span>';
        }
      } else {
        statusEl.textContent = "Not installed.";
        statusEl.style.color = "#8a2020";
        actEl.innerHTML = '<button id="obsSpacyGet" style="padding:5px 14px;border:1px solid #2f5fa6;'
          + 'background:#2f5fa6;color:#fff;font-size:11px;font-weight:bold;cursor:pointer">Download</button>';
        document.getElementById("obsSpacyGet").onclick = downloadSpacy;
        if(s.error){ spacyMsg("Last error: " + s.error, "#8a2020"); }
      }
    }).catch(function(){
      statusEl.textContent = "Status unavailable.";
      statusEl.style.color = "#8a2020";
    });
  }

  function clipMsg(text, color){
    var m = document.getElementById("obsClipMsg");
    if(m){ m.textContent = text || ""; m.style.color = color || "#666"; }
  }

  function refreshClip(){
    var statusEl = document.getElementById("obsClipStatus");
    var actEl = document.getElementById("obsClipActions");
    if(!statusEl || !actEl) return;
    api("/api/clip/status").then(function(r){ return r.json(); }).then(function(s){
      var isAdmin = document.getElementById("obsModelsPanel").dataset.admin === "1";
      if(s.status === "running"){
        statusEl.textContent = "Downloading...";
        statusEl.style.color = "#b06e00";
        actEl.innerHTML = "";
        setTimeout(refreshClip, 2000);
        return;
      }
      if(s.ready){
        statusEl.textContent = "Installed.";
        statusEl.style.color = "#2b7a2b";
        if(isAdmin){
          actEl.innerHTML = '<button id="obsClipRemove" style="padding:5px 14px;border:1px solid #a33;'
            + 'background:#f3dede;color:#8a2020;font-size:11px;cursor:pointer">Remove</button>';
          document.getElementById("obsClipRemove").onclick = removeClip;
        } else {
          actEl.innerHTML = '<span style="font-size:11px;color:#888">Ask an administrator to remove it.</span>';
        }
      } else {
        statusEl.textContent = "Not installed.";
        statusEl.style.color = "#8a2020";
        actEl.innerHTML = '<button id="obsClipGet" style="padding:5px 14px;border:1px solid #2f5fa6;'
          + 'background:#2f5fa6;color:#fff;font-size:11px;font-weight:bold;cursor:pointer">Download</button>';
        document.getElementById("obsClipGet").onclick = downloadClip;
        if(s.error){ clipMsg("Last error: " + s.error, "#8a2020"); }
      }
    }).catch(function(){
      statusEl.textContent = "Status unavailable.";
      statusEl.style.color = "#8a2020";
    });
  }

  function downloadClip(){
    clipMsg("Starting download...", "#b06e00");
    api("/api/clip/download", {method:"POST"}).then(function(r){ return r.json(); }).then(function(res){
      if(res.started){
        clipMsg("Downloading. This can take a few minutes. Keep OBS open.", "#b06e00");
        setTimeout(refreshClip, 1500);
      } else {
        clipMsg("Could not start: " + (res.reason || "unknown"), "#8a2020");
      }
    }).catch(function(){ clipMsg("Request failed.", "#8a2020"); });
  }

  function removeClip(){
    if(!window.confirm("Remove the image analysis model? You can download it again later, but it will need to be downloaded from scratch.")) return;
    clipMsg("Removing...", "#b06e00");
    api("/api/clip/remove", {method:"POST"}).then(function(r){ return r.json(); }).then(function(res){
      if(res.removed){
        clipMsg("Removed. Restart OBS to apply.", "#2b7a2b");
        refreshClip();
      } else {
        clipMsg("Could not remove: " + (res.reason || "unknown"), "#8a2020");
      }
    }).catch(function(){ clipMsg("Request failed.", "#8a2020"); });
  }

  function downloadSpacy(){
    spacyMsg("Starting download...", "#b06e00");
    api("/api/spacy/download", {method:"POST"}).then(function(r){ return r.json(); }).then(function(res){
      if(res.started){
        spacyMsg("Downloading. This can take a few minutes. Keep OBS open.", "#b06e00");
        setTimeout(refreshSpacy, 1500);
      } else {
        spacyMsg("Could not start: " + (res.reason || "unknown"), "#8a2020");
      }
    }).catch(function(){ spacyMsg("Request failed.", "#8a2020"); });
  }

  function removeSpacy(){
    if(!window.confirm("Remove the entity analysis model? You can download it again later, but it will need to be downloaded from scratch.")) return;
    spacyMsg("Removing...", "#b06e00");
    api("/api/spacy/remove", {method:"POST"}).then(function(r){ return r.json(); }).then(function(res){
      if(res.removed){
        spacyMsg("Removed. Restart OBS to apply.", "#2b7a2b");
        refreshSpacy();
      } else {
        spacyMsg("Could not remove: " + (res.reason || "unknown"), "#8a2020");
      }
    }).catch(function(){ spacyMsg("Request failed.", "#8a2020"); });
  }

  if(document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", checkSession);
  } else {
    checkSession();
  }

  window.OBS_AUTH = OBS_AUTH;
  window.obsLogout = doLogout;
})();
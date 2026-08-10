(function(){
  "use strict";

  var OBS_SHARE = { collaborators: [], groups: [] };

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

  function uiToast(message, kind){
    if(typeof window.toast === "function"){ window.toast(message, kind || "info"); return; }
    if(kind === "error"){ alert(message); }
  }
  function uiConfirm(message, title){
    if(typeof window.obsConfirm === "function"){ return window.obsConfirm(message, title); }
    return Promise.resolve(window.confirm(message));
  }
  function uiPrompt(message, value, title){
    if(typeof window.obsPrompt === "function"){ return window.obsPrompt(message, value, title); }
    return Promise.resolve(window.prompt(message, value || ""));
  }
  function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }

  function loadCollaborators(){
    return api("/api/sharing/collaborators").then(function(r){ return r.ok ? r.json() : []; })
      .then(function(list){ OBS_SHARE.collaborators = list || []; return OBS_SHARE.collaborators; });
  }
  function loadGroups(){
    return api("/api/sharing/groups").then(function(r){ return r.ok ? r.json() : []; })
      .then(function(list){ OBS_SHARE.groups = list || []; return OBS_SHARE.groups; });
  }

  function userName(id){
    var u = OBS_SHARE.collaborators.find(function(c){ return c.id === id; });
    return u ? u.username + " (" + u.email + ")" : ("user #" + id);
  }
  function groupName(id){
    var g = OBS_SHARE.groups.find(function(x){ return x.id === id; });
    return g ? g.name : ("group #" + id);
  }

  function ensurePanel(){
    var panel = document.getElementById("obsSharePanel");
    if(panel) return panel;
    panel = document.createElement("div");
    panel.id = "obsSharePanel";
    panel.style.cssText = "position:fixed;top:34px;right:12px;width:560px;max-height:80vh;overflow:auto;"
      + "z-index:9998;background:#fff;border:1px solid #787878;box-shadow:0 6px 28px rgba(0,0,0,0.3);"
      + "font-family:Tahoma,sans-serif;font-size:12px;display:none";
    panel.innerHTML =
      '<div style="background:#3f4d5e;color:#d6dce2;padding:10px 14px;font-weight:bold;display:flex;'
      + 'justify-content:space-between;align-items:center">'
      + '  <span id="obsShareTitle">Share</span>'
      + '  <span id="obsShareClose" style="cursor:pointer;font-weight:bold">&times;</span>'
      + '</div>'
      + '<div style="padding:14px">'
      + '  <div id="obsShareContext" style="font-size:11px;color:#3a3a3a;margin-bottom:10px"></div>'
      + '  <div style="font-size:11px;font-weight:bold;margin-bottom:6px;color:#3a3a3a">Share with</div>'
      + '  <div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">'
      + '    <select id="obsShareRecipient" style="flex:1;padding:6px;border:1px solid #9a9a9a"></select>'
      + '    <button id="obsShareAddBtn" style="padding:6px 14px;border:1px solid #28323d;background:#2f5fa6;'
      + 'color:#fff;font-weight:bold;cursor:pointer">Share</button>'
      + '  </div>'
      + '  <div style="font-size:11px;font-weight:bold;margin:12px 0 6px;color:#3a3a3a">Already shared with</div>'
      + '  <div id="obsShareList"></div>'
      + '  <hr style="border:none;border-top:1px solid #e2e2e2;margin:14px 0">'
      + '  <div style="font-size:11px;font-weight:bold;margin-bottom:6px;color:#3a3a3a">Collaborator groups</div>'
      + '  <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">'
      + '    <input id="obsGroupName" placeholder="new group name" style="flex:1;padding:6px;border:1px solid #9a9a9a">'
      + '    <button id="obsGroupAddBtn" style="padding:6px 14px;border:1px solid #28323d;background:#33404e;'
      + 'color:#d6dce2;font-weight:bold;cursor:pointer">Create</button>'
      + '  </div>'
      + '  <div id="obsGroupList"></div>'
      + '</div>';
    document.body.appendChild(panel);
    panel.querySelector("#obsShareClose").onclick = function(){ panel.style.display = "none"; };
    panel.querySelector("#obsShareAddBtn").onclick = doShare;
    panel.querySelector("#obsGroupAddBtn").onclick = doCreateGroup;
    return panel;
  }

  function fillRecipients(){
    var sel = document.getElementById("obsShareRecipient");
    var opts = ['<option value="">choose a collaborator or group</option>'];
    if(OBS_SHARE.collaborators.length){
      opts.push('<optgroup label="People">');
      OBS_SHARE.collaborators.forEach(function(c){
        opts.push('<option value="user:'+c.id+'">'+esc(c.username)+' ('+esc(c.email)+')</option>');
      });
      opts.push('</optgroup>');
    }
    if(OBS_SHARE.groups.length){
      opts.push('<optgroup label="Groups">');
      OBS_SHARE.groups.forEach(function(g){
        opts.push('<option value="group:'+g.id+'">'+esc(g.name)+' ('+g.member_ids.length+')</option>');
      });
      opts.push('</optgroup>');
    }
    sel.innerHTML = opts.join("");
  }

  function renderShareList(){
    var box = document.getElementById("obsShareList");
    api("/api/sharing/shares").then(function(r){ return r.json(); }).then(function(shares){
      var here = (shares || []).filter(function(s){
        return s.target_type === OBS_SHARE.target_type && s.target_id === OBS_SHARE.target_id;
      });
      if(!here.length){ box.innerHTML = '<div style="color:#6b6b6b">Not shared yet.</div>'; return; }
      box.innerHTML = here.map(function(s){
        var who = (s.recipient_type === "group")
          ? ('Group: ' + esc(groupName(s.recipient_id)))
          : esc(userName(s.recipient_id));
        return '<div style="padding:6px 0;border-bottom:1px solid #eee;display:flex;'
          + 'justify-content:space-between;align-items:center">'
          + '<span>'+who+'</span>'
          + '<button data-share="'+s.id+'" style="color:#b03a2e;cursor:pointer">Revoke</button>'
          + '</div>';
      }).join("");
      box.querySelectorAll("button[data-share]").forEach(function(b){
        b.onclick = function(){
          var id = parseInt(b.getAttribute("data-share"), 10);
          api("/api/sharing/shares/"+id, {method:"DELETE"}).then(function(r){
            return r.json().then(function(d){
              if(!r.ok){ uiToast(d.detail || "Revoke failed.", "error"); return; }
              uiToast("Access revoked.", "success"); renderShareList();
            });
          });
        };
      });
    });
  }

  function doShare(){
    var sel = document.getElementById("obsShareRecipient");
    var v = sel.value;
    if(!v){ uiToast("Choose a recipient first.", "error"); return; }
    var parts = v.split(":");
    var body = {
      target_type: OBS_SHARE.target_type,
      target_id:   OBS_SHARE.target_id,
      recipient_type: parts[0],
      recipient_id:   parseInt(parts[1], 10)
    };
    api("/api/sharing/shares", {method:"POST", body:body}).then(function(r){
      return r.json().then(function(d){
        if(!r.ok){ uiToast(d.detail || "Share failed.", "error"); return; }
        uiToast(d.already ? "Already shared." : "Shared.", "success");
        renderShareList();
      });
    });
  }

  function renderGroupList(){
    var box = document.getElementById("obsGroupList");
    if(!OBS_SHARE.groups.length){ box.innerHTML = '<div style="color:#6b6b6b">No groups yet.</div>'; return; }
    box.innerHTML = OBS_SHARE.groups.map(function(g){
      var members = g.member_ids.map(function(id){
        return '<span style="display:inline-flex;align-items:center;gap:4px;background:#eef2f7;'
          + 'border:1px solid #d3dbe5;border-radius:2px;padding:1px 6px;margin:2px 4px 2px 0;font-size:11px">'
          + esc(userName(id))
          + '<b data-grm="'+g.id+'" data-usr="'+id+'" style="cursor:pointer;color:#b03a2e">&times;</b></span>';
      }).join("") || '<span style="color:#6b6b6b">no members</span>';
      return '<div style="padding:8px 0;border-bottom:1px solid #eee">'
        + '<div style="display:flex;justify-content:space-between;align-items:center">'
        + '<b>'+esc(g.name)+'</b>'
        + '<span>'
        + '<button data-gradd="'+g.id+'" style="margin-right:6px;cursor:pointer">Add member</button>'
        + '<button data-grdel="'+g.id+'" style="color:#b03a2e;cursor:pointer">Delete</button>'
        + '</span></div>'
        + '<div style="margin-top:6px">'+members+'</div></div>';
    }).join("");

    box.querySelectorAll("button[data-grdel]").forEach(function(b){
      b.onclick = function(){
        var id = parseInt(b.getAttribute("data-grdel"), 10);
        uiConfirm("Delete this group? Shares made to it will be removed.", "Delete group").then(function(ok){
          if(!ok) return;
          api("/api/sharing/groups/"+id, {method:"DELETE"}).then(function(r){
            return r.json().then(function(d){
              if(!r.ok){ uiToast(d.detail || "Delete failed.", "error"); return; }
              refreshGroups();
            });
          });
        });
      };
    });
    box.querySelectorAll("button[data-gradd]").forEach(function(b){
      b.onclick = function(){
        var gid = parseInt(b.getAttribute("data-gradd"), 10);
        pickCollaborator().then(function(uid){
          if(uid === null) return;
          api("/api/sharing/groups/"+gid+"/members", {method:"POST", body:{user_id:uid}}).then(function(r){
            return r.json().then(function(d){
              if(!r.ok){ uiToast(d.detail || "Could not add member.", "error"); return; }
              refreshGroups();
            });
          });
        });
      };
    });
    box.querySelectorAll("b[data-grm]").forEach(function(x){
      x.onclick = function(){
        var gid = parseInt(x.getAttribute("data-grm"), 10);
        var uid = parseInt(x.getAttribute("data-usr"), 10);
        api("/api/sharing/groups/"+gid+"/members/"+uid, {method:"DELETE"}).then(function(r){
          return r.json().then(function(d){
            if(!r.ok){ uiToast(d.detail || "Could not remove member.", "error"); return; }
            refreshGroups();
          });
        });
      };
    });
  }

  function pickCollaborator(){
    if(!OBS_SHARE.collaborators.length){
      uiToast("No collaborators in your company yet.", "error");
      return Promise.resolve(null);
    }
    var lines = OBS_SHARE.collaborators.map(function(c, i){
      return (i+1) + ") " + c.username + " (" + c.email + ")";
    }).join("\n");
    return uiPrompt("Add which collaborator? Type the number:\n" + lines, "", "Add member").then(function(ans){
      if(ans === null) return null;
      var n = parseInt((ans||"").trim(), 10);
      if(!n || n < 1 || n > OBS_SHARE.collaborators.length){ uiToast("Invalid choice.", "error"); return null; }
      return OBS_SHARE.collaborators[n-1].id;
    });
  }

  function doCreateGroup(){
    var inp = document.getElementById("obsGroupName");
    var name = (inp.value || "").trim();
    if(!name){ uiToast("Type a group name.", "error"); return; }
    api("/api/sharing/groups", {method:"POST", body:{name:name}}).then(function(r){
      return r.json().then(function(d){
        if(!r.ok){ uiToast(d.detail || "Could not create group.", "error"); return; }
        inp.value = ""; refreshGroups();
      });
    });
  }

  function refreshGroups(){
    return loadGroups().then(function(){ fillRecipients(); renderGroupList(); });
  }

  function openShare(targetType, targetId, label){
    OBS_SHARE.target_type = targetType;
    OBS_SHARE.target_id = String(targetId);
    var panel = ensurePanel();
    var adminPanel = document.getElementById("obsAdminPanel");
    if(adminPanel) adminPanel.style.display = "none";
    panel.style.display = "block";
    document.getElementById("obsShareTitle").textContent =
      (targetType === "folder") ? "Share folder" : "Share document";
    document.getElementById("obsShareContext").innerHTML =
      '<b>' + esc(label || targetId) + '</b>'
      + ((targetType === "folder")
          ? ', everyone you share with sees the documents you own in this folder, including ones you add later.'
          : '');
    Promise.all([loadCollaborators(), loadGroups()]).then(function(){
      fillRecipients(); renderShareList(); renderGroupList();
    });
  }

  window.obsShareDoc = function(id, title){ openShare("document", id, title); };
  window.obsShareFolder = function(id, name){ openShare("folder", id, name); };
  window.OBS_SHARE = OBS_SHARE;
})();

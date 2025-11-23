const $ = (id) => document.getElementById(id);
const api = (path, opts={}) => fetch(path, opts);

function logln(s) {
  const el = $("logs");
  el.textContent += s + "\n";
  el.scrollTop = el.scrollHeight;
}

async function octoLogin() {
  $("loginStatus").textContent = "Logging in...";
  try {
    const r = await api("/login");
    const j = await r.json();
    if (r.ok && j.access_token) {
      $("loginStatus").textContent = "Logged in ✓ (token cached)";
      logln("Login OK");
      return true;
    } else {
      $("loginStatus").textContent = "Login failed";
      logln("Login failed: " + JSON.stringify(j));
      return false;
    }
  } catch (e) {
    $("loginStatus").textContent = "Login error";
    logln("Login error: " + e);
    return false;
  }
}

async function loadGroups() {
  $("groupSelect").innerHTML = "";
  const opt = document.createElement("option");
  opt.value = "";
  opt.textContent = "Loading...";
  $("groupSelect").appendChild(opt);
  try {
    const r = await api("/octo/task-groups");
    const j = await r.json();
    $("groupSelect").innerHTML = "";
    (j.data || []).forEach(g => {
      const o = document.createElement("option");
      o.value = g.taskGroupId;
      o.textContent = `${g.taskGroupName} (${g.taskGroupId})`;
      $("groupSelect").appendChild(o);
    });
    if (($("groupSelect").options || []).length > 0) {
      await loadTasks();
    }
  } catch (e) {
    logln("Load groups error: " + e);
  }
}

async function loadTasks() {
  const gid = $("groupSelect").value;
  const box = $("tasksList");
  box.innerHTML = "Loading...";
  if (!gid) { box.textContent = "Pick a group"; return; }
  try {
    const r = await api(`/octo/tasks?taskGroupId=${encodeURIComponent(gid)}`);
    const j = await r.json();
    box.innerHTML = "";
    (j.data || []).forEach(t => {
      const div = document.createElement("div");
      div.style.display = "flex";
      div.style.gap = "8px";
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.value = t.taskId; cb.checked = true;
      const label = document.createElement("label");
      label.textContent = `${t.taskName} (${t.taskId})`;
      div.appendChild(cb);
      div.appendChild(label);
      box.appendChild(div);
    });
    if ((j.data || []).length === 0) {
      box.textContent = "No tasks in this group.";
    }
  } catch (e) {
    logln("Load tasks error: " + e);
  }
}

async function runAll(selectedOnly) {
  const gid = $("groupSelect").value;
  if (!gid) { alert("Pick a group first."); return; }

  let selectedTaskIds = null;
  if (selectedOnly) {
    const ids = [];
    $("tasksList").querySelectorAll('input[type="checkbox"]').forEach(cb => {
      if (cb.checked) ids.push(cb.value);
    });
    selectedTaskIds = ids;
    if (ids.length === 0) { alert("No tasks selected."); return; }
  }

  logln(`Running ${selectedOnly ? "selected" : "all"} tasks in group ${gid} ...`);
  const body = { taskGroupId: parseInt(gid, 10) };
  if (selectedTaskIds) body.selectedTaskIds = selectedTaskIds;

  try {
    const r = await fetch("/octo/run-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });

    if (!r.ok) {
      const err = await r.text();
      logln("Run error: " + err);
      alert("Run failed. Check logs.");
      return;
    }

    // Download the Excel file
    const blob = await r.blob();
    const disp = r.headers.get("Content-Disposition") || "";
    const m = /filename="?([^"]+)"?/.exec(disp);
    const fname = m ? m[1] : `jobpulse_octoparse_${Date.now()}.xlsx`;

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    logln("Export downloaded: " + fname);
  } catch (e) {
    logln("Run exception: " + e);
    alert("Run failed. Check logs.");
  }
}

function deselectAll() {
  const boxes = document.querySelectorAll('#tasksList input[type="checkbox"]');
  let n = 0;
  boxes.forEach(cb => { if (cb.checked) { cb.checked = false; n++; } });
  logln(`Deselected ${n} task(s).`);
}

function selectAll() {
  const boxes = document.querySelectorAll('#tasksList input[type="checkbox"]');
  let n = 0;
  boxes.forEach(cb => { if (!cb.checked) { cb.checked = true; n++; } });
  logln(`Selected ${n} task(s).`);
}

window.addEventListener("DOMContentLoaded", async () => {
  $("loginBtn").addEventListener("click", octoLogin);
  $("reloadGroups").addEventListener("click", loadGroups);
  $("groupSelect").addEventListener("change", loadTasks);
  $("runAll").addEventListener("click", () => runAll(false));
  $("runSelected").addEventListener("click", () => runAll(true));
  $("deselectAll").addEventListener("click", deselectAll);
  $("selectAll").addEventListener("click", selectAll);

  // auto login & load on first paint (best-effort)
  await octoLogin();
  await loadGroups();
});

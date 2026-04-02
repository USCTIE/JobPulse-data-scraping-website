const $ = (id) => document.getElementById(id);

function logln(s) {
  const el = $("logs");
  el.textContent += s + "\n";
  el.scrollTop = el.scrollHeight;
}

async function loadBackupTasks() {
  const meta = $("backupTasksMeta");
  const tbody = $("backupTasksBody");
  meta.textContent = "Loading...";
  tbody.innerHTML = "";
  try {
    const r = await fetch("/local-backup-tasks");
    if (!r.ok) { meta.textContent = "Error: HTTP " + r.status; return; }
    const j = await r.json();
    const items = j.items || [];
    meta.textContent = `${items.length} task(s)`;

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center">No backup tasks configured</td></tr>';
      return;
    }

    items.forEach(row => {
      const tr = document.createElement("tr");

      const tdId = document.createElement("td");
      tdId.textContent = row.task_id;
      tdId.style.fontFamily = "monospace";
      tr.appendChild(tdId);

      const tdName = document.createElement("td");
      tdName.textContent = row.task_name || "—";
      tr.appendChild(tdName);

      const tdDate = document.createElement("td");
      if (row.created_at) {
        const raw = row.created_at.endsWith("Z") ? row.created_at : row.created_at + "Z";
        const d = new Date(raw);
        tdDate.textContent = d.toLocaleString(undefined, {
          year: "numeric", month: "short", day: "numeric",
          hour: "numeric", minute: "2-digit"
        });
      }
      tr.appendChild(tdDate);

      const tdAction = document.createElement("td");
      const btn = document.createElement("button");
      btn.textContent = "Remove";
      btn.style.background = "#dc3545";
      btn.style.color = "#fff";
      btn.addEventListener("click", () => removeBackupTask(row.task_id));
      tdAction.appendChild(btn);
      tr.appendChild(tdAction);

      tbody.appendChild(tr);
    });
  } catch (e) {
    meta.textContent = "Error loading";
    logln("Load error: " + e);
  }
}

async function addBackupTask() {
  const input = $("newTaskId");
  const btn = $("addTaskIdBtn");
  const feedback = $("addFeedback");
  const taskId = input.value.trim();
  if (!taskId) { alert("Enter a Task ID"); return; }

  // Show validating state
  btn.disabled = true;
  btn.textContent = "Validating...";
  feedback.innerHTML = `<span style="color: #ffc107;">⏳ Validating task ID with Octoparse...</span>`;

  try {
    const r = await fetch("/local-backup-tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId })
    });
    const data = await r.json();

    if (!r.ok) {
      const errMsg = data.error || `HTTP ${r.status}`;
      feedback.innerHTML = `<span style="color: #dc3545;">❌ ${errMsg}</span>`;
      logln("Add error: " + errMsg);
      return;
    }

    // Success — show task name if available
    const nameInfo = data.task_name ? ` (${data.task_name})` : "";
    feedback.innerHTML = `<span style="color: #28a745;">✅ Added successfully${nameInfo}</span>`;
    logln(`Added: ${taskId}${nameInfo}`);
    input.value = "";
    await loadBackupTasks();

    // Clear success message after a few seconds
    setTimeout(() => { feedback.innerHTML = ""; }, 5000);
  } catch (e) {
    feedback.innerHTML = `<span style="color: #dc3545;">❌ Network error: ${e}</span>`;
    logln("Add exception: " + e);
  } finally {
    btn.disabled = false;
    btn.textContent = "Add";
  }
}

async function removeBackupTask(taskId) {
  if (!confirm(`Remove task "${taskId}" from local backup?`)) return;
  try {
    const r = await fetch(`/local-backup-tasks/${encodeURIComponent(taskId)}`, {
      method: "DELETE"
    });
    if (!r.ok) {
      const err = await r.json();
      logln("Remove error: " + (err.error || r.status));
      return;
    }
    logln("Removed: " + taskId);
    await loadBackupTasks();
  } catch (e) {
    logln("Remove exception: " + e);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  $("addTaskIdBtn").addEventListener("click", addBackupTask);
  $("refreshBtn").addEventListener("click", loadBackupTasks);
  $("newTaskId").addEventListener("keydown", (e) => {
    if (e.key === "Enter") addBackupTask();
  });
  loadBackupTasks();
});

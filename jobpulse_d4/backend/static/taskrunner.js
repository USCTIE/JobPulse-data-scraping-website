const $ = (id) => document.getElementById(id);
const api = (path, opts={}) => fetch(path, opts);

function logln(s) {
  const el = $("logs");
  el.textContent += s + "\n";
  el.scrollTop = el.scrollHeight;
}

async function octoLogin() {
  const username = $("username").value.trim();
  const password = $("password").value.trim();

  if (!username || !password) {
    $("loginStatus").textContent = "Enter username and password";
    logln("Login failed: Missing credentials");
    return false;
  }

  $("loginStatus").textContent = "Logging in...";
  try {
    const r = await api("/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const j = await r.json();
    if (r.ok && j.access_token) {
      $("loginStatus").textContent = "Logged in ✓ (token cached)";
      logln("Login OK");

      // Cache credentials in localStorage
      localStorage.setItem("octo_username", username);
      localStorage.setItem("octo_password", password);

      // Auto-load groups after successful login
      await loadGroups();

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

async function autoLogin() {
  const username = localStorage.getItem("octo_username");
  const password = localStorage.getItem("octo_password");

  if (!username || !password) {
    return false;
  }

  // Populate the input fields
  $("username").value = username;
  $("password").value = password;

  // Attempt login
  return await octoLogin();
}

function logout() {
  localStorage.removeItem("octo_username");
  localStorage.removeItem("octo_password");
  $("username").value = "";
  $("password").value = "";
  $("loginStatus").textContent = "Logged out";
  $("groupSelect").innerHTML = "";
  $("tasksList").innerHTML = "";
  logln("Logged out and cleared cache");
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
      o.textContent = `${g.taskGroupName}`;
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
      cb.type = "checkbox";
      cb.value = t.taskId;
      cb.dataset.taskName = t.taskName || "";
      cb.checked = true;
      const label = document.createElement("label");
      label.textContent = `${t.taskName}`;
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
  let selectedTaskNames = null;
  if (selectedOnly) {
    const ids = [];
    const names = [];
    $("tasksList").querySelectorAll('input[type="checkbox"]').forEach(cb => {
      if (cb.checked) {
        ids.push(cb.value);
        names.push(cb.dataset.taskName || "");
      }
    });
    selectedTaskIds = ids;
    selectedTaskNames = names;
    if (ids.length === 0) { alert("No tasks selected."); return; }
  } else {
    // Run all: collect all task names for the table
    const names = [];
    $("tasksList").querySelectorAll('input[type="checkbox"]').forEach(cb => {
      names.push(cb.dataset.taskName || "");
    });
    selectedTaskNames = names;
  }

  const taskGroupName = $("groupSelect").options[$("groupSelect").selectedIndex]?.textContent || "";
  logln(`Running ${selectedOnly ? "selected" : "all"} tasks in group ${gid} ...`);
  const body = { taskGroupId: parseInt(gid, 10), taskGroupName, selectedTaskNames: selectedTaskNames || [] };
  if (selectedTaskIds) body.selectedTaskIds = selectedTaskIds;

  try {
    const r = await fetch("/jobs", {
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

    const j = await r.json();
    const jobId = j.jobId;
    logln(`Job ${jobId} created. Polling for completion...`);

    // Track this job locally so we can highlight it after refresh
    const myJobs = JSON.parse(localStorage.getItem("jobpulse_jobs") || "[]");
    if (!myJobs.includes(jobId)) {
      myJobs.push(jobId);
      localStorage.setItem("jobpulse_jobs", JSON.stringify(myJobs));
    }

    // Start polling this job specifically
    await pollJobUntilDone(jobId);
  } catch (e) {
    logln("Run exception: " + e);
    alert("Run failed. Check logs.");
  }
}

async function pollJobUntilDone(jobId) {
  const pollIntervalMs = 4000;

  async function once() {
    try {
      const r = await api(`/jobs/${jobId}`);
      if (!r.ok) {
        logln(`Job ${jobId} poll error: HTTP ${r.status}`);
        return true;
      }
      const j = await r.json();
      renderJobsTableRow(j);

      if (j.status === "done") {
        logln(`Job ${jobId} completed. Downloading...`);
        await downloadJobFile(jobId);
        return true;
      }
      if (j.status === "failed") {
        logln(`Job ${jobId} failed: ${j.error || ""}`);
        return true;
      }
      return false;
    } catch (e) {
      logln(`Job ${jobId} poll exception: ${e}`);
      return true;
    }
  }

  (async () => {
    while (true) {
      const stop = await once();
      if (stop) break;
      await new Promise(res => setTimeout(res, pollIntervalMs));
    }
  })();
}

async function downloadJobFile(jobId) {
  try {
    const r = await fetch(`/jobs/${jobId}/download`);
    if (!r.ok) {
      const err = await r.text();
      logln(`Download for job ${jobId} failed: ${err}`);
      return;
    }
    const blob = await r.blob();
    const disp = r.headers.get("Content-Disposition") || "";
    const m = /filename="?([^"]+)"?/.exec(disp);
    const fname = m ? m[1] : `jobpulse_octoparse_${jobId}_${Date.now()}.xlsx`;

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    logln(`Export downloaded: ${fname}`);
  } catch (e) {
    logln(`Download for job ${jobId} exception: ${e}`);
  }
}

async function loadJobs() {
  try {
    const r = await api("/jobs");
    if (!r.ok) {
      logln("Load jobs error: HTTP " + r.status);
      return;
    }
    const j = await r.json();
    const items = j.items || [];
    $("jobsMeta").textContent = `${items.length} job(s) shown`;
    const tbody = $("jobsBody");
    tbody.innerHTML = "";
    items.forEach(job => {
      renderJobsTableRow(job);
    });
  } catch (e) {
    logln("Load jobs exception: " + e);
  }
}

function renderJobsTableRow(job) {
  const tbody = $("jobsBody");
  if (!tbody) return;
  const id = job.id || job.job_id || job.jobId;
  if (!id) return;

  let tr = tbody.querySelector(`tr[data-job-id="${id}"]`);
  if (!tr) {
    tr = document.createElement("tr");
    tr.dataset.jobId = id;
    for (let i = 0; i < 8; i++) {
      tr.appendChild(document.createElement("td"));
    }
    tbody.appendChild(tr);
  }

  const cells = tr.querySelectorAll("td");
  const taskNames = job.task_names;
  const taskNamesStr = Array.isArray(taskNames) ? taskNames.filter(Boolean).join(", ") : (taskNames || "");

  cells[0].textContent = id;
  cells[1].textContent = job.task_group_name ?? job.task_group_id ?? "";
  cells[2].textContent = taskNamesStr || "";
  cells[3].textContent = job.status ?? "";
  cells[4].textContent = job.progress ?? "";
  cells[5].textContent = job.created_at ?? "";
  cells[6].textContent = job.file_name ?? "";

  const downloadCell = cells[7];
  downloadCell.innerHTML = "";
  if (job.status === "done") {
    const btn = document.createElement("button");
    btn.textContent = "Download";
    btn.addEventListener("click", () => downloadJobFile(id));
    downloadCell.appendChild(btn);
  }
}

// --- Login Template Data ---
const LT_COLUMNS = ["scrape_date", "Title", "Company", "Location", "Salary", "Keyword", "Date", "Posted_time"];
const LT_PAGE_SIZE = 100;
let ltCurrentPage = 1;
let ltTotal = 0;

function ltFormatDate(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function ltSetDefaultDates() {
  const today = new Date();
  const thirtyAgo = new Date();
  thirtyAgo.setDate(today.getDate() - 30);
  $("ltEndDate").value = ltFormatDate(today);
  $("ltStartDate").value = ltFormatDate(thirtyAgo);
}

function ltBuildUrl(page) {
  const start = $("ltStartDate").value;
  const end = $("ltEndDate").value;
  let url = `/login-template-data?page=${page}&page_size=${LT_PAGE_SIZE}`;
  if (start) url += `&start_date=${encodeURIComponent(start)}`;
  if (end)   url += `&end_date=${encodeURIComponent(end)}`;
  return url;
}

function ltUpdatePagination() {
  const totalPages = Math.max(1, Math.ceil(ltTotal / LT_PAGE_SIZE));
  $("loginTemplatePrev").disabled = ltCurrentPage <= 1;
  $("loginTemplateNext").disabled = ltCurrentPage >= totalPages;
  $("loginTemplatePageInfo").textContent = ltTotal > 0
    ? `Page ${ltCurrentPage} of ${totalPages} (${ltTotal} total rows)`
    : "";
}

async function loadLoginTemplateData(page) {
  const meta   = $("loginTemplateMeta");
  const thead  = $("loginTemplateHead");
  const tbody  = $("loginTemplateBody");
  if (!thead || !tbody) return;
  if (page != null) ltCurrentPage = Math.max(1, parseInt(page, 10) || 1);
  meta.textContent = "Loading...";
  thead.innerHTML = "";
  tbody.innerHTML = "";
  $("loginTemplatePrev").disabled = true;
  $("loginTemplateNext").disabled = true;
  try {
    const r = await api(ltBuildUrl(ltCurrentPage));
    if (!r.ok) {
      meta.textContent = "Error: HTTP " + r.status;
      logln("Login template load error: HTTP " + r.status);
      ltUpdatePagination();
      return;
    }
    const j = await r.json();
    const items = j.items || [];
    ltTotal = j.total ?? 0;
    meta.textContent = `Showing ${items.length} of ${ltTotal} row(s)`;

    // Header
    const headRow = document.createElement("tr");
    LT_COLUMNS.forEach(k => {
      const th = document.createElement("th");
      th.textContent = k;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);

    if (items.length === 0) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td colspan="${LT_COLUMNS.length}" style="text-align:center">No data found for selected date range</td>`;
      tbody.appendChild(tr);
      ltUpdatePagination();
      return;
    }

    items.forEach(row => {
      const tr = document.createElement("tr");
      LT_COLUMNS.forEach(k => {
        const td = document.createElement("td");
        const full = row[k] == null ? "" : String(row[k]);
        const short = full.length > 60 ? full.slice(0, 60) + "…" : full;
        td.textContent = short;
        td.title = full;
        td.style.maxWidth = "180px";
        td.style.overflow = "hidden";
        td.style.textOverflow = "ellipsis";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    ltUpdatePagination();
  } catch (e) {
    meta.textContent = "Error loading";
    logln("Login template load exception: " + e);
    ltUpdatePagination();
  }
}

function ltPrevPage() {
  if (ltCurrentPage > 1) loadLoginTemplateData(ltCurrentPage - 1);
}

function ltNextPage() {
  const totalPages = Math.max(1, Math.ceil(ltTotal / LT_PAGE_SIZE));
  if (ltCurrentPage < totalPages) loadLoginTemplateData(ltCurrentPage + 1);
}

async function ltDownloadCsv() {
  const start = $("ltStartDate").value;
  const end   = $("ltEndDate").value;
  let url = "/login-template-data/export-csv";
  const params = [];
  if (start) params.push(`start_date=${encodeURIComponent(start)}`);
  if (end)   params.push(`end_date=${encodeURIComponent(end)}`);
  if (params.length) url += "?" + params.join("&");

  try {
    logln(`Downloading CSV (${start || "all"} → ${end || "all"})...`);
    const r = await fetch(url);
    if (!r.ok) {
      const err = await r.text();
      logln("CSV download failed: " + err);
      return;
    }
    const blob = await r.blob();
    const disp = r.headers.get("Content-Disposition") || "";
    const m = /filename="?([^"]+)"?/.exec(disp);
    const fname = m ? m[1] : `login_template_data_${Date.now()}.csv`;
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = blobUrl; a.download = fname;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(blobUrl);
    logln("CSV downloaded: " + fname);
  } catch (e) {
    logln("CSV download exception: " + e);
  }
}

// Kept for backward compatibility (old button listener name)
function loginTemplatePrevPage() { ltPrevPage(); }
function loginTemplateNextPage() { ltNextPage(); }

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
  $("loadLoginTemplateData").addEventListener("click", () => { ltCurrentPage = 1; loadLoginTemplateData(1); });
  $("ltFilterBtn").addEventListener("click", () => { ltCurrentPage = 1; loadLoginTemplateData(1); });
  $("ltDownloadCsvBtn").addEventListener("click", ltDownloadCsv);
  $("loginTemplatePrev").addEventListener("click", ltPrevPage);
  $("loginTemplateNext").addEventListener("click", ltNextPage);

  // Set default date range (today back 30 days) and load immediately
  ltSetDefaultDates();

  // Auto-login if credentials are cached
  await autoLogin();

  // Initial jobs load + periodic refresh for global table
  await loadJobs();
  setInterval(loadJobs, 10000);

  // Auto-load login template data on startup, then sync every 5 minutes
  await loadLoginTemplateData(1);
  setInterval(() => loadLoginTemplateData(ltCurrentPage), 5 * 60 * 1000);
});
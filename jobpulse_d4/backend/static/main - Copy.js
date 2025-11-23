let state = { page: 1, pageSize: 25, total: 0 };

function qs(id){ return document.getElementById(id); }
function params(obj){ return new URLSearchParams(obj).toString(); }

async function search(p=state.page){
  const q = qs('q').value.trim();
  const geo = qs('geo').value.trim();
  const employment = qs('employment').value;
  const seniority = qs('seniority').value;
  const start = qs('start').value;
  const end = qs('end').value;
  const sort = qs('sort').value;
  const order = qs('order').value;

  const url = `/search?${params({q, geo, employment, seniority, start, end, sort, order, page: p, page_size: state.pageSize})}`;
  const res = await fetch(url);
  const data = await res.json();

  state.page = p;
  state.total = data.total || 0;

  const tbody = document.querySelector("#results tbody");
  tbody.innerHTML = "";
  (data.items || []).forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.job_title || ""}</td>
      <td>${r.company || ""}</td>
      <td>${r.job_location || ""}</td>
      <td>${r.post_time || ""}</td>
      <td>${r.job_link ? `<a href="${r.job_link}" target="_blank">View</a>` : ""}</td>
    `;
    tbody.appendChild(tr);
  });

  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
  qs("meta").textContent = `Total: ${state.total} • Page ${state.page} / ${totalPages}`;

  qs("prev").disabled = state.page <= 1;
  qs("next").disabled = state.page >= totalPages;
}

function exportFmt(fmt){
  const q = qs('q').value.trim();
  const geo = qs('geo').value.trim();
  const employment = qs('employment').value;
  const seniority = qs('seniority').value;
  const start = qs('start').value;
  const end = qs('end').value;
  const sort = qs('sort').value;
  const order = qs('order').value;
  const url = `/export?${params({q, geo, employment, seniority, start, end, sort, order, page: state.page, page_size: state.pageSize, format: fmt})}`;
  window.location = url;
}

qs("searchBtn").addEventListener("click", () => search(1));
qs("prev").addEventListener("click", () => search(state.page - 1));
qs("next").addEventListener("click", () => search(state.page + 1));
qs("csvBtn").addEventListener("click", () => exportFmt("csv"));
qs("jsonBtn").addEventListener("click", () => exportFmt("json"));

search(1);

"use strict";

const state = { pipelines: [], runs: [], jobs: [], clusters: [], poll: 3000 };
let selectedPipeline = null;
let selectedRun = null;
let selectedJob = null;
const jobDetailOpenStates = new Map();

const $ = (sel) => document.querySelector(sel);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (e) {}
    throw new Error(`${res.status}: ${msg}`);
  }
  return res.status === 204 ? null : res.json();
}

function statusIcon(status) {
  const map = {
    COMPLETED: ["success", "✔"],
    FAILED: ["failure", "✖"],
    CANCELLED: ["failure", "✖"],
    RUNNING: ["running", "●"],
    PENDING: ["queued", "…"],
  };
  const [cls, ch] = map[status] || ["unknown", "?"];
  return `<span class="status-icon ${cls} ${cls === "running" ? "spin" : ""}">${ch}</span>`;
}

function badge(status) {
  return status ? `<span class="badge ${esc(status)}">${esc(status)}</span>` : "";
}

function resultUrl(path) {
  return `/results/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function resultTree(entries) {
  if (!entries.length) return `<span class="sub">No files pulled.</span>`;
  return `<ul class="result-tree">${entries.map((entry) => {
    if (entry.directory) {
      return `<li><details open><summary>${esc(entry.name)}</summary>${resultTree(entry.children)}</details></li>`;
    }
    return `<li><a href="${resultUrl(entry.path)}" target="_blank">${esc(entry.name)}</a></li>`;
  }).join("")}</ul>`;
}

function executionTimeline(execution) {
  if (!execution) return "";
  const active = execution.active ? `<span class="sub">${esc(execution.active)}</span>` : "";
  const steps = (execution.steps || []).map((step) => `
    <li class="execution-${esc(step.state)}"><span></span>${esc(step.name)}</li>`).join("");
  return `<div class="execution"><div class="execution-active">${active}</div><ol>${steps}</ol></div>`;
}

function progressArtifacts(artifacts) {
  const thumbnails = (artifacts || []).filter((artifact) => artifact.thumbnail);
  if (!thumbnails.length) return "";
  return `<div class="progress-artifacts">${thumbnails.map((artifact) => `
    <a href="${resultUrl(artifact.path)}" target="_blank" title="${esc(artifact.path)}">
      <img src="${resultUrl(artifact.path)}" alt="${esc(artifact.path)}" loading="lazy">
    </a>`).join("")}</div>`;
}

function arrayChildren(children) {
  if (!children || !children.length) return "";
  const counts = children.reduce((total, child) => {
    total[child.state] = (total[child.state] || 0) + 1;
    return total;
  }, {});
  const summary = Object.entries(counts).map(([state, count]) =>
    `<span class="badge ${esc(state)}">${esc(state)} ${count}</span>`).join("");
  const rows = children.map((child) => `
    <tr>
      <td>${esc(child.array_index)}</td>
      <td>${badge(child.state)}</td>
      <td>${esc(child.job_id || "-")}</td>
      <td>${esc(child.node || "-")}</td>
      <td>${esc(child.updated || "-")}</td>
      <td>${esc(child.message || "-")}</td>
    </tr>`).join("");
  return `
    <details class="array-children" open>
      <summary>Array tasks <span class="array-summary">${summary}</span></summary>
      <div class="array-table-wrap"><table class="data"><thead><tr>
        <th>index</th><th>state</th><th>Slurm job</th><th>node</th><th>updated</th><th>message</th>
      </tr></thead><tbody>${rows}</tbody></table></div>
    </details>`;
}

async function loadResultTree(container, namespace) {
  try {
    const data = await api(`/api/jobs/${encodeURIComponent(namespace)}/results`);
    container.innerHTML = resultTree(data.entries || []);
  } catch (e) {
    container.textContent = "Results unavailable.";
  }
}

function fmtTags(job) {
  const tags = [];
  if (job.job_id) tags.push(`slurm:${esc(job.job_id)}`);
  if (job.node) tags.push(`node:${esc(job.node)}`);
  if (job.partition) tags.push(`part:${esc(job.partition)}`);
  if (job.discovered) tags.push(`<span class="badge">discovered</span>`);
  if (job.artifacts_pulled) tags.push(`<span class="badge success">results pulled</span>`);
  return tags.join(" ");
}

function renderPipelines() {
  const ul = $("#pipeline-list");
  ul.innerHTML = "";
  const all = document.createElement("li");
  all.innerHTML = `<span class="pip-enabled"></span><span class="pip-name">All runs</span>`;
  all.className = selectedPipeline === null ? "selected" : "";
  all.onclick = () => {
    selectedPipeline = null;
    selectedRun = null;
    selectedJob = null;
    switchView("runs");
    refresh();
  };
  ul.appendChild(all);
  state.pipelines.forEach((p) => {
    const li = document.createElement("li");
    li.className = selectedPipeline === p.id ? "selected" : "";
    const dot = p.enabled ? "pip-enabled" : "pip-disabled";
    const cron = p.cron ? `<span class="pip-cron" title="next: ${esc(p.next_run_at_iso)}">⏱</span>` : "";
    li.innerHTML = `<span class="${dot}"></span><span class="pip-name">${esc(p.name)}</span>${cron}`;
    li.onclick = () => {
      selectedPipeline = p.id;
      selectedRun = null;
      selectedJob = null;
      switchView("runs");
      refresh();
    };
    ul.appendChild(li);
  });
}

function runRow(r, pipelineName) {
  const el = document.createElement("div");
  el.className = "card run-row";
  const jobsRun = (r.jobs || []).length;
  const trigger = r.trigger === "cron" ? `<span class="badge cron">cron</span>` : `<span class="badge">${esc(r.trigger || "manual")}</span>`;
  el.innerHTML = `
    ${statusIcon(r.status)}
    <div>
      <div class="run-title">${esc(pipelineName)} <span class="sub">run #${r.id}</span></div>
      <div class="run-meta"><span>${r.created_at_iso || ""}</span><span>${jobsRun} job${jobsRun === 1 ? "" : "s"}</span></div>
    </div>
    <div class="run-spacer"></div>
    ${trigger}
    <span class="badge">${esc(r.status)}</span>`;
  el.onclick = () => {
    selectedRun = r.id;
    selectedJob = null;
    switchView("detail");
    renderDetail();
  };
  return el;
}

function discoveredJobRow(job) {
  const el = document.createElement("div");
  el.className = "card run-row";
  el.innerHTML = `
    ${statusIcon(job.state)}
    <div>
      <div class="run-title">${esc(job.task)} <span class="sub">${esc(job.namespace)}</span></div>
      <div class="run-meta">${fmtTags(job)} <span>${esc(job.updated || "")}</span></div>
    </div>
    <div class="run-spacer"></div>
    <span class="badge">discovered</span>
    ${badge(job.state)}
    <button class="btn small" data-pull="${esc(job.namespace)}">pull results</button>`;
  const pullButton = el.querySelector("[data-pull]");
  pullButton.onclick = async (event) => {
    event.stopPropagation();
    pullButton.disabled = true;
    pullButton.textContent = "pulling...";
    try {
      await api(`/api/jobs/${encodeURIComponent(job.namespace)}/pull`, { method: "POST" });
    } finally {
      refresh();
    }
  };
  el.onclick = () => {
    selectedJob = job.namespace;
    selectedRun = null;
    switchView("detail");
    renderDetail();
  };
  return el;
}

function renderRuns() {
  const list = $("#runs-list");
  const title = $("#runs-title");
  list.innerHTML = "";
  let pipelines = state.pipelines;
  let runs = state.runs;
  let discovered = [];
  if (selectedPipeline !== null) {
    const p = state.pipelines.find((x) => x.id === selectedPipeline);
    pipelines = p ? [p] : [];
    runs = runs.filter((r) => r.pipeline_id === selectedPipeline);
    title.textContent = p ? `Runs — ${p.name}` : "Runs";
    const btn = $("#dispatch-all-none");
    btn.hidden = !p;
    btn.textContent = "Dispatch now";
    btn.onclick = async () => {
      await api(`/api/pipelines/${selectedPipeline}/dispatch`, { method: "POST" });
      refresh();
    };
  } else {
    title.textContent = "All runs";
    $("#dispatch-all-none").hidden = true;
    discovered = state.jobs.filter((job) => job.discovered && !job.run_id);
  }
  if (!runs.length && !discovered.length) {
    list.innerHTML = `<div class="card run-row" style="cursor:default">No runs yet. Create a pipeline and dispatch it.</div>`;
    return;
  }
  const names = Object.fromEntries(state.pipelines.map((p) => [p.id, p.name]));
  runs.forEach((r) => list.appendChild(runRow(r, names[r.pipeline_id] || `pipeline ${r.pipeline_id}`)));
  if (discovered.length) {
    const heading = document.createElement("h3");
    heading.className = "section-title";
    heading.textContent = "Discovered jobs";
    list.appendChild(heading);
    discovered.forEach((job) => list.appendChild(discoveredJobRow(job)));
  }
}

function renderClusters() {
  const list = $("#clusters-list");
  if (!state.clusters.length) {
    list.innerHTML = `<div class="card">No cluster snapshots yet - they appear once monitoring queries an ssh config (e.g. hpc).</div>`;
    return;
  }
  list.innerHTML = state.clusters.map((c) => `
    <div class="card" style="margin-bottom:16px">
      <h3 style="margin:2px 0 10px">${esc(c.ssh)} <span class="sub">updated ${esc(c.updated || "")}</span></h3>
      <table class="data"><thead><tr>
        <th>job id</th><th>name</th><th>state</th><th>time</th><th>node</th><th>partition</th>
      </tr></thead><tbody>
        ${(c.jobs || []).map((j) => `<tr><td>${esc(j.job_id)}</td><td>${esc(j.name)}</td><td>${badge(j.state)}</td><td>${esc(j.time)}</td><td>${esc(j.nodes)}</td><td>${esc(j.partition)}</td></tr>`).join("") || "<tr><td colspan=\"6\">no active slurm jobs</td></tr>"}
      </tbody></table>
      <table class="data" style="margin-top:12px"><thead><tr>
        <th>node</th><th>state</th><th>cpus (free/total)</th><th>gpus (free/total)</th><th>mem free MB</th><th>reason</th>
      </tr></thead><tbody>
        ${(c.nodes || []).map((n) => `<tr><td>${esc(n.name)}</td><td>${esc(n.state)}</td><td>${esc(n.cap_cpu_free)}/${esc(n.cap_cpu_total)}</td><td>${esc(n.cap_gpu_free)}/${esc(n.cap_gpu_total)}</td><td>${esc(n.cap_mem_free_mb)}</td><td>${esc(n.reason || "")}</td></tr>`).join("") || "<tr><td colspan=\"6\">no nodes</td></tr>"}
      </tbody></table>
    </div>`).join("");
}

function jobDetail(job, collapsible = true) {
  const isOpen = jobDetailOpenStates.has(job.namespace)
    ? jobDetailOpenStates.get(job.namespace)
    : Boolean(job.execution && job.execution.active);
  const canCollapse = collapsible !== false;
  const tileStart = canCollapse
    ? `<details class="job-step" data-job-namespace="${esc(job.namespace)}" ${isOpen ? "open" : ""}>`
    : `<section class="job-step">`;
  const headerTag = canCollapse ? "summary" : "div";
  const tileEnd = canCollapse ? "</details>" : "</section>";
  return `
    ${tileStart}
      <${headerTag} class="job-step-head">${statusIcon(job.state)}
        <strong>${esc(job.task)}</strong>
        <span class="sub">${esc(job.namespace)}</span>
        <div class="run-spacer"></div>${badge(job.state)}
      </${headerTag}>
      <div class="job-step-body">
        ${executionTimeline(job.execution)}
        ${progressArtifacts(job.progress_artifacts)}
        <div class="fields">
          <span class="k">ssh</span><code>${esc(job.ssh)}</code>
          <span class="k">slurm job</span><code>${esc(job.job_id || "-")}</code>
          <span class="k">node</span><code>${esc(job.node || "-")}</code>
          <span class="k">partition</span><code>${esc(job.partition || "-")}</code>
          <span class="k">updated</span><code>${esc(job.updated || "-")}</code>
          <span class="k">message</span><code>${esc(job.message || "-")}</code>
          <span class="k">results</span><div class="result-files">${job.artifacts_pulled ? `<span data-result-tree="${esc(job.namespace)}">Loading results...</span>` : "pending"}</div>
        </div>
      </div>
    ${tileEnd}`;
}

function rememberJobDetailState(event) {
  const details = event.target;
  if (!details.isConnected || !details.matches("details[data-job-namespace]")) return;
  jobDetailOpenStates.set(details.dataset.jobNamespace, details.open);
}

function captureJobDetailStates(box) {
  for (const details of box.querySelectorAll("details[data-job-namespace]")) {
    jobDetailOpenStates.set(details.dataset.jobNamespace, details.open);
  }
}

function renderDetail() {
  const box = $("#run-detail");
  captureJobDetailStates(box);
  if (selectedRun === null && selectedJob === null) { switchView("runs"); return; }
  if (selectedJob !== null) {
    const job = state.jobs.find((item) => item.namespace === selectedJob);
    if (!job) { box.innerHTML = `<div class="card">job is no longer in view</div>`; return; }
    box.innerHTML = `
      <div class="detail-head">
        <a href="javascript:void(0)" id="back-link" style="color:var(--accent);text-decoration:none">&larr; back</a>
        <h2>Discovered job <span class="sub">${esc(job.namespace)}</span></h2>
        ${badge(job.state)}
      </div>
      <div class="card-list">${jobDetail(job, false)}</div>`;
    box.querySelectorAll("[data-result-tree]").forEach((container) => {
      loadResultTree(container, container.dataset.resultTree);
    });
    $("#back-link").onclick = () => {
      selectedJob = null;
      switchView("runs");
    };
    return;
  }
  const run = state.runs.find((r) => r.id === selectedRun);
  if (!run) { box.innerHTML = `<div class="card">run #${selectedRun} no longer in view</div>`; return; }
  const pipeline = state.pipelines.find((p) => p.id === run.pipeline_id);
  box.innerHTML = `
    <div class="detail-head">
      <a href="javascript:void(0)" id="back-link" style="color:var(--accent);text-decoration:none">&larr; back</a>
      <h2>${esc(pipeline ? pipeline.name : `pipeline ${run.pipeline_id}`)} <span class="sub">run #${run.id}</span></h2>
      <span class="badge">${esc(run.trigger || "manual")}</span>
      ${badge(run.status)}
      <div class="run-spacer"></div>
      <span class="run-meta">${run.created_at_iso || ""}${run.finished_at_iso ? " → " + run.finished_at_iso : ""}</span>
    </div>
    <div class="card-list">
      ${(run.jobs || []).map(jobDetail).join("") || `<div class="card">no jobs recorded for this run</div>`}
    </div>`;
  box.querySelectorAll("[data-result-tree]").forEach((container) => {
    loadResultTree(container, container.dataset.resultTree);
  });
  const back = $("#back-link");
  back.onclick = () => { selectedRun = null; switchView("runs"); };
}

function switchView(view) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === view));
  ["runs", "clusters", "detail"].forEach((v) => {
    const el = $(`#view-${v}`);
    if (el) el.classList.toggle("hidden", v !== view);
  });
}

function refreshOnce(data) {
  state.pipelines = data.pipelines || [];
  state.runs = data.runs || [];
  state.jobs = data.jobs || [];
  state.clusters = data.clusters || [];
  state.poll = data.poll_interval_ms || 3000;
  renderPipelines();
  if (!$("#view-detail").classList.contains("hidden")) renderDetail();
  if (!$("#view-runs").classList.contains("hidden")) renderRuns();
  if (!$("#view-clusters").classList.contains("hidden")) renderClusters();
}

let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const data = await api("/api/state");
    refreshOnce(data);
  } catch (e) {
    $("#pollhint").textContent = `connection error: ${e.message}`;
  } finally {
    refreshing = false;
  }
}

/* pipeline dialog ************************************************************/

$("#run-detail").addEventListener("toggle", rememberJobDetailState, true);

const dialog = $("#pipeline-dialog");
$("#new-pipeline-btn").onclick = () => { $("#pipeline-form").reset(); dialog.showModal(); };
$("#dialog-cancel").onclick = () => dialog.close();
$("#pipeline-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const form = new FormData(ev.target);
  let assets = {};
  const raw = (form.get("assets") || "").toString().trim();
  if (raw) {
    try { assets = JSON.parse(raw); }
    catch (e) { $("#form-error").textContent = "assets must be valid JSON"; return; }
  }
  const body = {
    name: form.get("name"),
    wes_yaml: form.get("wes_yaml"),
    ssh: form.get("ssh") || "",
    cron: form.get("cron") || "",
    enabled: form.get("enabled") === "on",
    assets,
  };
  try {
    await api("/api/pipelines", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    dialog.close();
    $("#form-error").textContent = "";
    refresh();
  } catch (e) {
    $("#form-error").textContent = e.message;
  }
};

document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => {
    selectedRun = null;
    selectedJob = null;
    switchView(t.dataset.view);
  };
});

refresh();
setInterval(refresh, 4000);

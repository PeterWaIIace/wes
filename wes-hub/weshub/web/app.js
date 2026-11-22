"use strict";

const state = { pipelines: [], runs: [], jobs: [], clusters: [], poll: 3000 };
let selectedPipeline = null;
let selectedRun = null;
let selectedJob = null;
const jobDetailOpenStates = new Map();
const resultFolderStates = new Map();
const resultTreeCache = new Map();
const pendingPulls = new Set();
const sweepOpenStates = new Map();
let detailSignature = "";
let runsSignature = "";
let dispatchPending = false;
let refreshTimer = null;
let searchText = "";
let statusFilter = "";

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
  const classes = { COMPLETED: "success", FAILED: "failure", CANCELLED: "cancelled", RUNNING: "running", PENDING: "queued" };
  return status ? `<span class="badge ${classes[status] || ""}">${esc(status)}</span>` : "";
}

function resultUrl(path) {
  return `/results/${path.split("/").map(encodeURIComponent).join("/")}`;
}

function resultTree(entries) {
  if (!entries.length) return `<span class="sub">No files pulled.</span>`;
  return `<ul class="result-tree">${entries.map((entry) => {
    if (entry.directory) {
      const isOpen = resultFolderStates.get(entry.path) !== false;
      return `<li><details data-result-path="${esc(entry.path)}" ${isOpen ? "open" : ""}><summary>${esc(entry.name)}</summary>${resultTree(entry.children)}</details></li>`;
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
      <img src="${resultUrl(artifact.path)}?v=${encodeURIComponent(artifact.version || "")}" alt="${esc(artifact.path)}" loading="lazy">
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
  container.dataset.remoteTree = namespace;
  try {
    const job = state.jobs.find((item) => item.namespace === namespace);
    const key = `${namespace}:${job && job.transfer_updated || ""}`;
    let data = resultTreeCache.get(key);
    if (!data) {
      data = await api(`/api/jobs/${encodeURIComponent(namespace)}/artifacts`);
      resultTreeCache.set(key, data);
    }
    if (!container.isConnected) return;
    container.innerHTML = `<button class="btn small" data-refresh-tree="${esc(namespace)}">Refresh listing</button>` + remoteResultTree(data, namespace);
    loadExpandedArtifactDirectories(container);
  } catch (e) {
    container.textContent = `Remote results unavailable: ${e.message}`;
  }
}

function fmtTags(job) {
  const tags = [];
  if (job.job_id) tags.push(`slurm:${esc(job.job_id)}`);
  if (job.node) tags.push(`node:${esc(job.node)}`);
  if (job.partition) tags.push(`part:${esc(job.partition)}`);
  if (job.discovered) tags.push(`<span class="badge">discovered</span>`);
  if (job.transfer_state === "partial") tags.push(`<span class="badge">some artifacts missing</span>`);
  else if (job.artifacts_pulled) tags.push(`<span class="badge success">results pulled</span>`);
  return tags.join(" ");
}

function renderPipelines() {
  const ul = $("#pipeline-list");
  ul.innerHTML = "";
  const all = document.createElement("li");
  makeRowAccessible(all);
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
    makeRowAccessible(li);
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
  makeRowAccessible(el);
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
  makeRowAccessible(el);
  el.innerHTML = `
    ${statusIcon(job.state)}
    <div>
      <div class="run-title">${esc(job.task)} <span class="sub">${esc(job.namespace)}</span></div>
      <div class="run-meta">${fmtTags(job)} <span>${esc(job.updated || "")}</span></div>
    </div>
    <div class="run-spacer"></div>
    <span class="badge">discovered</span>
    ${badge(job.state)}
    <button class="btn small" data-pull="${esc(job.namespace)}">browse results</button>`;
  const pullButton = el.querySelector("[data-pull]");
  pullButton.onclick = (event) => {
    event.stopPropagation();
    selectedJob = job.namespace;
    selectedRun = null;
    switchView("detail");
    renderDetail();
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
  const signature = JSON.stringify([selectedPipeline, state.runs, state.jobs, state.pipelines, dispatchPending, [...pendingPulls], searchText, statusFilter]);
  if (signature === runsSignature) return;
  runsSignature = signature;
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
    discovered = state.jobs.filter((job) => job.discovered && !job.run_id && job.pipeline_id === selectedPipeline);
    title.textContent = p ? `Runs — ${p.name}` : "Runs";
    const btn = $("#dispatch-all-none");
    btn.hidden = !p;
    btn.textContent = "Dispatch now";
    btn.disabled = dispatchPending;
    btn.onclick = dispatchSelectedPipeline;
  } else {
    title.textContent = "All runs";
    $("#dispatch-all-none").hidden = true;
    discovered = state.jobs.filter((job) => job.discovered && !job.run_id);
  }
  discovered = discovered.filter(jobMatchesFilters);
  runs = runs.filter(runMatchesFilters);
  if (!runs.length && !discovered.length) {
    list.innerHTML = `<div class="card">${searchText || statusFilter ? "No jobs match these filters." : "No runs yet. Create a pipeline and dispatch it."}</div>`;
    return;
  }
  const names = Object.fromEntries(state.pipelines.map((p) => [p.id, p.name]));
  runs.forEach((r) => list.appendChild(runRow(r, names[r.pipeline_id] || `pipeline ${r.pipeline_id}`)));
  if (discovered.length) {
    const heading = document.createElement("h3");
    heading.className = "section-title";
    heading.textContent = "Discovered jobs";
    list.appendChild(heading);
    appendSweepRows(list, discovered);
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
          <span class="k">downloads</span><div>${esc(job.transfer_state || "not requested")}${job.transfer_error ? `<p class="error">${esc(job.transfer_error)}</p>` : ""}${transferOutcomes(job.transfer_outcomes)}</div>
          <span class="k">progress sync</span><div>${esc(job.progress_updated || "not checked yet")}${transferOutcomes(job.progress_outcomes)}</div>
          <span class="k">artifact config</span><div>${esc(job.artifact_config_source)}<br><code>${esc((job.artifact_patterns || []).join(", "))}</code><br><code>${esc((job.progress_patterns || []).join(", "))}</code><br><button class="btn small" data-refresh-artifacts="${esc(job.namespace)}">Use current workflow patterns</button></div>
          <span class="k">results</span><div class="result-files" data-result-tree="${esc(job.namespace)}">Loading remote listing...</div>
        </div>
      </div>
    ${tileEnd}`;
}

function rememberJobDetailState(event) {
  const details = event.target;
  if (!details.isConnected || details.tagName !== "DETAILS") return;
  if (details.dataset.jobNamespace) jobDetailOpenStates.set(details.dataset.jobNamespace, details.open);
  if (details.dataset.resultPath) resultFolderStates.set(details.dataset.resultPath, details.open);
  if (details.dataset.sweep) sweepOpenStates.set(details.dataset.sweep, details.open);
  if (details.dataset.remoteNamespace && details.open) loadRemoteDirectory(details);
}

function captureJobDetailStates(box) {
  for (const details of box.querySelectorAll("details[data-job-namespace]")) {
    jobDetailOpenStates.set(details.dataset.jobNamespace, details.open);
  }
}

function renderDetail() {
  const box = $("#run-detail");
  captureJobDetailStates(box);
  const data = selectedJob !== null ? state.jobs.find((job) => job.namespace === selectedJob) : state.runs.find((run) => run.id === selectedRun);
  const signature = JSON.stringify([selectedJob, selectedRun, data]);
  if (signature === detailSignature && box.children.length) return;
  detailSignature = signature;
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
      ${groupedJobDetails(run.jobs || []) || `<div class="card">no jobs recorded for this run</div>`}
    </div>`;
  box.querySelectorAll("[data-result-tree]").forEach((container) => {
    loadResultTree(container, container.dataset.resultTree);
  });
  const back = $("#back-link");
  back.onclick = () => { selectedRun = null; switchView("runs"); };
}

function switchView(view) {
  const route = selectedJob !== null ? `#job/${encodeURIComponent(selectedJob)}` : selectedRun !== null ? `#run/${selectedRun}` : view === "clusters" ? "#clusters" : selectedPipeline !== null ? `#pipeline/${selectedPipeline}` : "#runs";
  if (location.hash !== route) history.pushState(null, "", route);
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
    $("#pollhint").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    $("#pollhint").textContent = `connection error: ${e.message}`;
  } finally {
    refreshing = false;
  }
}

function transferOutcomes(outcomes) {
  return (outcomes || []).map((item) => `<div><code>${esc(item.pattern || item.path)}</code> — ${esc(item.state)}, ${Number(item.matched || 0)} matched</div>`).join("");
}

function remoteResultTree(page, namespace) {
  let html = '<ul class="result-tree">';
  for (const entry of page.entries || []) {
    const pull = `<button class="btn small" data-pull-artifact="${esc(entry.path)}" data-artifact-namespace="${esc(namespace)}">Pull${entry.directory ? " folder" : ""}</button>`;
    if (entry.directory) {
      const key = `${namespace}:${entry.path}`;
      const open = resultFolderStates.get(key) === true ? "open" : "";
      html += `<li><details data-remote-path="${esc(entry.path)}" data-remote-namespace="${esc(namespace)}" data-result-path="${esc(key)}" ${open}><summary>${esc(entry.name)}/</summary>${pull}<div data-remote-children>Expand to list files.</div></details></li>`;
    } else {
      const label = entry.downloaded
        ? `<a href="${resultUrl(entry.local_path)}" target="_blank" rel="noopener">${esc(entry.name)}</a>`
        : `<span>${esc(entry.name)}</span>`;
      html += `<li>${label} <span class="sub">${formatFileSize(entry.size)}</span> ${pull}</li>`;
    }
  }
  html += '</ul>';
  if (!(page.entries || []).length) html += '<span class="sub">No matching remote artifacts.</span>';
  if (page.next_offset !== null && page.next_offset !== undefined) {
    html += `<button class="btn small" data-load-more-ns="${esc(namespace)}" data-load-more-path="${esc(page.path || "")}" data-load-more-offset="${page.next_offset}">Load next 200 entries</button>`;
  }
  return html;
}

function formatFileSize(bytes) {
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MiB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${Number(bytes || 0)} B`;
}

function loadExpandedArtifactDirectories(container) {
  for (const details of container.querySelectorAll("details[data-remote-namespace][open]")) {
    loadRemoteDirectory(details);
  }
}

async function loadRemoteDirectory(details) {
  if (details.dataset.remoteLoading === "true" || details.dataset.remoteLoaded === "true") return;
  details.dataset.remoteLoading = "true";
  const namespace = details.dataset.remoteNamespace;
  const path = details.dataset.remotePath;
  const container = details.querySelector("[data-remote-children]");
  container.textContent = "Listing remote directory...";
  try {
    const job = state.jobs.find((item) => item.namespace === namespace);
    const key = `directory:${namespace}:${path}:${job && job.transfer_updated || ""}`;
    let page = resultTreeCache.get(key);
    if (!page) {
      page = await api(`/api/jobs/${encodeURIComponent(namespace)}/artifacts?path=${encodeURIComponent(path)}`);
      resultTreeCache.set(key, page);
    }
    if (!container.isConnected) return;
    container.innerHTML = remoteResultTree(page, namespace);
    details.dataset.remoteLoaded = "true";
    loadExpandedArtifactDirectories(container);
  } catch (error) {
    container.textContent = `Listing failed: ${error.message}. Close and reopen to retry.`;
  } finally {
    details.dataset.remoteLoading = "false";
  }
}

async function handleArtifactActions(event) {
  const pull = event.target.closest("[data-pull-artifact]");
  const more = event.target.closest("[data-load-more-ns]");
  const reload = event.target.closest("[data-refresh-tree]");
  const button = pull || more || reload;
  if (!button) return;
  event.preventDefault();
  event.stopPropagation();
  button.disabled = true;
  try {
    if (pull) {
      await api(`/api/jobs/${encodeURIComponent(pull.dataset.artifactNamespace)}/pull`, {
        method: "POST", headers: {"content-type": "application/json"},
        body: JSON.stringify({paths: [pull.dataset.pullArtifact]}),
      });
      showNotice(`Download queued: ${pull.dataset.pullArtifact}`);
      await refresh();
    } else if (more) {
      const namespace = more.dataset.loadMoreNs;
      const page = await api(`/api/jobs/${encodeURIComponent(namespace)}/artifacts?path=${encodeURIComponent(more.dataset.loadMorePath)}&offset=${more.dataset.loadMoreOffset}`);
      const container = more.parentElement;
      more.remove();
      container.insertAdjacentHTML("beforeend", remoteResultTree(page, namespace));
      loadExpandedArtifactDirectories(container);
    } else {
      resultTreeCache.clear();
      await loadResultTree(reload.closest("[data-remote-tree]"), reload.dataset.refreshTree);
    }
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function showNotice(message, isError = false) {
  const notice = $("#action-notice");
  notice.textContent = message;
  notice.classList.toggle("error", isError);
}

async function dispatchSelectedPipeline() {
  if (dispatchPending) return;
  dispatchPending = true;
  renderRuns();
  try {
    await api(`/api/pipelines/${selectedPipeline}/dispatch`, { method: "POST" });
    showNotice("Run submitted.");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    dispatchPending = false;
    runsSignature = "";
    await refresh();
  }
}

function activateRowWithKeyboard(event) {
  if (event.target !== event.currentTarget || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  event.currentTarget.click();
}

function makeRowAccessible(element) {
  element.tabIndex = 0;
  element.setAttribute("role", "button");
  element.addEventListener("keydown", activateRowWithKeyboard);
}

function sweepGroups(jobs) {
  const groups = new Map();
  for (const job of jobs) {
    const key = job.parent_namespace || job.namespace;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(job);
  }
  return groups;
}

function compareTaskIndices(left, right) {
  return Number(left.array_index || -1) - Number(right.array_index || -1);
}

function sweepSummary(namespace, jobs) {
  const counts = {};
  for (const job of jobs) counts[job.state || "unknown"] = (counts[job.state || "unknown"] || 0) + 1;
  return `<strong>Sweep</strong> <span class="sub">${esc(namespace)}</span> ${Object.entries(counts).map(([status, count]) => `${badge(status)} ${count}`).join(" ")}`;
}

function rememberSweepState(event) {
  if (event.target.dataset.sweep) sweepOpenStates.set(event.target.dataset.sweep, event.target.open);
}

function appendSweepRows(list, jobs) {
  for (const [namespace, tasks] of sweepGroups(jobs)) {
    if (!tasks.some((job) => job.parent_namespace)) {
      for (const job of tasks) list.appendChild(discoveredJobRow(job));
      continue;
    }
    const group = document.createElement("details");
    group.className = "sweep-group";
    group.dataset.sweep = namespace;
    group.open = sweepOpenStates.get(namespace) === true;
    group.innerHTML = `<summary>${sweepSummary(namespace, tasks)}</summary>`;
    group.addEventListener("toggle", rememberSweepState);
    for (const job of tasks.sort(compareTaskIndices)) group.appendChild(discoveredJobRow(job));
    list.appendChild(group);
  }
}

function groupedJobDetails(jobs) {
  let html = "";
  for (const [namespace, tasks] of sweepGroups(jobs)) {
    const children = tasks.filter((job) => job.parent_namespace);
    if (!children.length) {
      for (const job of tasks) html += jobDetail(job);
      continue;
    }
    html += `<details class="sweep-group" data-sweep="${esc(namespace)}" ${sweepOpenStates.get(namespace) ? "open" : ""}><summary>${sweepSummary(namespace, children)}</summary>`;
    for (const job of children.sort(compareTaskIndices)) html += jobDetail(job);
    html += "</details>";
  }
  return html;
}

function restoreRoute() {
  const [kind, value] = location.hash.slice(1).split("/");
  selectedJob = kind === "job" ? decodeURIComponent(value || "") : null;
  selectedRun = kind === "run" ? Number(value) : null;
  selectedPipeline = kind === "pipeline" ? Number(value) : null;
  detailSignature = "";
  runsSignature = "";
  switchView(kind === "clusters" ? "clusters" : selectedJob !== null || selectedRun !== null ? "detail" : "runs");
  if (selectedJob !== null || selectedRun !== null) renderDetail();
  else renderRuns();
}

function toggleSidebar() {
  const sidebar = $("#pipeline-sidebar");
  sidebar.hidden = !sidebar.hidden;
  $("#sidebar-toggle").setAttribute("aria-expanded", String(!sidebar.hidden));
}

function jobMatchesFilters(job) {
  if (statusFilter && job.state !== statusFilter) return false;
  return [job.task, job.namespace, job.parent_namespace, job.job_id].join(" ").toLowerCase().includes(searchText);
}

function runMatchesFilters(run) {
  if (!searchText && !statusFilter) return true;
  return (run.jobs || []).some(jobMatchesFilters);
}

function updateListFilters() {
  searchText = $("#job-search").value.trim().toLowerCase();
  statusFilter = $("#job-status-filter").value;
  renderRuns();
}

async function refreshAndSchedule() {
  await refresh();
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refreshAndSchedule, state.poll);
}

async function refreshArtifactPatterns(event) {
  const button = event.target.closest("[data-refresh-artifacts]");
  if (!button) return;
  button.disabled = true;
  try {
    await api(`/api/jobs/${encodeURIComponent(button.dataset.refreshArtifacts)}/artifacts/refresh`, { method: "POST" });
    resultTreeCache.clear();
    showNotice("Workflow artifact patterns applied; progress refresh queued. Results stay remote until you pull them.");
    await refresh();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    button.disabled = false;
  }
}

/* pipeline dialog ************************************************************/

$("#run-detail").addEventListener("toggle", rememberJobDetailState, true);
$("#run-detail").addEventListener("click", refreshArtifactPatterns);
$("#run-detail").addEventListener("click", handleArtifactActions);
$("#sidebar-toggle").addEventListener("click", toggleSidebar);
$("#job-search").addEventListener("input", updateListFilters);
$("#job-status-filter").addEventListener("change", updateListFilters);

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

window.addEventListener("popstate", restoreRoute);
restoreRoute();
refreshAndSchedule();

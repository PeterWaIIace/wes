"use strict";

const state = { pipelines: [], runs: [], jobs: [], clusters: [], poll: 3000 };
let selectedPipeline = null;
let selectedRun = null;

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
  status = status || "queued";
  const map = {
    success: ["success", "✔"], COMPLETED: ["success", "✔"],
    failure: ["failure", "✖"], FAILED: ["failure", "✖"],
    cancelled: ["failure", "✖"], CANCELLED: ["failure", "✖"],
    running: ["running", "●"], RUNNING: ["running", "●"],
    queued: ["queued", "…"], PENDING: ["queued", "…"],
  };
  const [cls, ch] = map[status] || ["queued", "…"];
  return `<span class="status-icon ${cls} ${cls === "running" ? "spin" : ""}">${ch}</span>`;
}

function badge(status) {
  return `<span class="badge ${esc(status)}">${esc(status || "queued")}</span>`;
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
  all.onclick = () => { selectedPipeline = null; selectedRun = null; switchView("runs"); refresh(); };
  ul.appendChild(all);
  state.pipelines.forEach((p) => {
    const li = document.createElement("li");
    li.className = selectedPipeline === p.id ? "selected" : "";
    const dot = p.enabled ? "pip-enabled" : "pip-disabled";
    const cron = p.cron ? `<span class="pip-cron" title="next: ${esc(p.next_run_at_iso)}">⏱</span>` : "";
    li.innerHTML = `<span class="${dot}"></span><span class="pip-name">${esc(p.name)}</span>${cron}`;
    li.onclick = () => { selectedPipeline = p.id; selectedRun = null; switchView("runs"); refresh(); };
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
  el.onclick = () => { selectedRun = r.id; switchView("detail"); renderDetail(); };
  return el;
}

function renderRuns() {
  const list = $("#runs-list");
  const title = $("#runs-title");
  list.innerHTML = "";
  let pipelines = state.pipelines;
  let runs = state.runs;
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
  }
  if (!runs.length) {
    list.innerHTML = `<div class="card run-row" style="cursor:default">No runs yet. Create a pipeline and dispatch it.</div>`;
    return;
  }
  const names = Object.fromEntries(state.pipelines.map((p) => [p.id, p.name]));
  state.runs.forEach((r) => list.appendChild(runRow(r, names[r.pipeline_id] || `pipeline ${r.pipeline_id}`)));
}

function renderJobs() {
  const list = $("#jobs-list");
  list.innerHTML = "";
  if (!state.jobs.length) {
    list.innerHTML = `<div class="card run-row" style="cursor:default">No jobs known. Jobs appear here after dispatch or discovery.</div>`;
    return;
  }
  state.jobs.forEach((j) => {
    const el = document.createElement("div");
    const pre = esc((j.message || "").replace(/</g, ""));
    const msg = j.message ? `<code>${esc(j.message.slice(0, 120))}</code>` : "";
    el.innerHTML = `
      <div class="card run-row" style="cursor:default">
        ${statusIcon(j.state)}
        <div>
          <div class="run-title">${esc(j.task)} <span class="sub">${esc(j.namespace)}</span></div>
          <div class="run-meta">${fmtTags(j)} <span>${esc(j.updated || "")}</span></div>
          ${msg ? `<div class="run-meta">${msg}</div>` : ""}
        </div>
        <div class="run-spacer"></div>
        ${j.run_id ? `<span class="badge">run #${j.run_id}</span>` : ""}
        ${badge(j.state)}
        <button class="btn small" data-pull="${esc(j.namespace)}">pull results</button>
      </div>`;
    const btnEl = el.querySelector("[data-pull]");
    btnEl.onclick = async (ev) => {
      ev.stopPropagation();
      btnEl.disabled = true;
      btnEl.textContent = "pulling…";
      try {
        await api(`/api/jobs/${encodeURIComponent(j.namespace)}/pull`, { method: "POST" });
      } catch (e) {}
      refresh();
    };
    list.appendChild(el);
  });
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

function renderDetail() {
  const box = $("#run-detail");
  if (selectedRun === null) { switchView("runs"); return; }
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
      ${(run.jobs || []).map((j) => `
        <div class="job-step">
          <div class="job-step-head">${statusIcon(j.state)}
            <strong>${esc(j.task)}</strong>
            <span class="sub">${esc(j.namespace)}</span>
            <div class="run-spacer"></div>${badge(j.state)}
          </div>
          <div class="job-step-body">
            <div class="fields">
              <span class="k">ssh</span><code>${esc(j.ssh)}</code>
              <span class="k">slurm job</span><code>${esc(j.job_id || "-")}</code>
              <span class="k">node</span><code>${esc(j.node || "-")}</code>
              <span class="k">partition</span><code>${esc(j.partition || "-")}</code>
              <span class="k">updated</span><code>${esc(j.updated || "-")}</code>
              <span class="k">message</span><code>${esc(j.message || "-")}</code>
              <span class="k">results</span><code>${j.artifacts_pulled ? `<a style="color:var(--accent)" href="/results/${esc(j.job_name)}/${esc(j.task)}_config.json" target="_blank">browse /results</a>` : "pending"}</code>
            </div>
          </div>
        </div>`).join("") || `<div class="card">no jobs recorded for this run</div>`}
    </div>`;
  const back = $("#back-link");
  back.onclick = () => { selectedRun = null; switchView("runs"); };
}

function switchView(view) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === view));
  ["runs", "jobs", "clusters", "detail"].forEach((v) => {
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
  if (!$("#view-jobs").classList.contains("hidden")) renderJobs();
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
  t.onclick = () => { selectedRun = null; switchView(t.dataset.view); };
});

refresh();
setInterval(refresh, 4000);

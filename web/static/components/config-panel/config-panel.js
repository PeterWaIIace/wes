import { WesComponent } from "../base/WesComponent.js";
import "../time-chips/time-chips.js";
import "../resource-slider/resource-slider.js";

class ConfigPanel extends WesComponent {
    constructor() {
        super();
        this._templates = [];
    }

    async connectedCallback() {
        await this.loadTemplate("config-panel");
        this._panel = this.$("#panel");
        this._title = this.$("#title");
        this._name = this.$("#name");
        this._job = this.$("#job");
        this._gitUrl = this.$("#git-url");
        this._branch = this.$("#branch");
        this._ssh = this.$("#ssh");
        this._nodelist = this.$("#nodelist");
        this._memSlider = this.$("resource-slider#mem-slider");
        this._cpuSlider = this.$("resource-slider#cpu-slider");
        this._gpuSlider = this.$("resource-slider#gpu-slider");
        this._timeChips = this.$("time-chips#time-chips");
        this._templateSelect = this.$("#template-select");
        this._templateSection = this.$("#template-section");

        this.$("#cancel-btn").addEventListener("click", () => this.close());
        this.$("#close-btn").addEventListener("click", () => this.close());
        this.$("#submit-btn").addEventListener("click", () => this._submit());
        this._templateSelect.addEventListener("change", () => this._loadFromTemplate());

        this.addEventListener("node-change", (e) => {
            this._nodelist.value = e.detail || "";
        });

        if (this._readyData !== undefined) this._dispatch(this._readyData);
    }

    _dispatch(data) {
        if (!this._ready) { this._readyData = data; return; }
        this._readyData = undefined;

        if (data.editing) {
            this._title.textContent = "Edit Task";
            this._editName = data.name;
            this._name.value = data.name || "";
            this._job.value = data.job || "";
            this._gitUrl.value = data.git_url || "";
            this._branch.value = data.branch || "";
            this._ssh.value = data.ssh || "";
            this._nodelist.value = data.nodelist || "";
            if (this._memSlider) this._memSlider.value = parseInt(data.memory) || 4;
            if (this._cpuSlider) this._cpuSlider.value = data.cpus || 1;
            if (this._gpuSlider) this._gpuSlider.value = data.gpus || 0;
            if (this._timeChips) this._timeChips.value = data.time || "";
        } else {
            this._title.textContent = "New Task";
            this._editName = null;
            this._name.value = "";
            this._job.value = "";
            this._gitUrl.value = "";
            this._branch.value = "";
            this._ssh.value = "";
            this._nodelist.value = "";
            if (this._memSlider) this._memSlider.value = 4;
            if (this._cpuSlider) this._cpuSlider.value = 1;
            if (this._gpuSlider) this._gpuSlider.value = 0;
            if (this._timeChips) this._timeChips.value = "";
        }

        this._panel.classList.remove("hidden");
        this._panel.scrollIntoView({ behavior: "smooth", block: "start" });
        this._fetchTemplates();
        this._fetchAutocomplete();
    }

    open(data) {
        this._dispatch(data);
    }

    loadNodeOptions(nodes) {
        if (!this._nodelist) return;
        this._nodelist.innerHTML = '<option value="">any</option>';
        this._nodelist.innerHTML += '<option value="local">local</option>';
        nodes.forEach(n => {
            const opt = document.createElement("option");
            opt.value = n.name;
            const cpus = n.ncpus || n.cpus || '?';
            const gpus = n.ngpus || n.gpus || '?';
            const mem = n.mem_gb || n.memory || '?';
            opt.textContent = `${n.name} (${cpus} cpus, ${gpus} gpus, ${mem})`;
            this._nodelist.appendChild(opt);
        });
    }

    close() {
        this._panel.classList.add("hidden");
        this._readyData = undefined;
    }

    async _fetchTemplates() {
        try {
            const resp = await fetch("/api/tasks");
            this._templates = await resp.json();
            this._renderTemplates();
        } catch (e) {
            this._templates = [];
        }
    }

    async _fetchAutocomplete() {
        try {
            const resp = await fetch("/api/settings");
            const data = await resp.json();
            this._fillDatalist("dl-git-url", data.form_history?.git_url || []);
            this._fillDatalist("dl-branch", data.form_history?.branch || []);
            this._fillDatalist("dl-ssh", data.form_history?.ssh || []);
            this._fillDatalist("dl-job", data.form_history?.job || []);
        } catch (e) { /* ignore */ }
    }

    _fillDatalist(id, values) {
        const dl = this.$(`#${id}`);
        if (!dl) return;
        dl.innerHTML = values.map(v => `<option value="${v}">`).join("");
    }

    _renderTemplates() {
        if (!this._templates.length) {
            this._templateSection.style.display = "none";
            return;
        }
        this._templateSection.style.display = "";
        this._templateSelect.innerHTML = '<option value="">-- select a task to copy --</option>';
        this._templates.forEach((t, i) => {
            const opt = document.createElement("option");
            opt.value = i;
            opt.textContent = t.name || `task ${i + 1}`;
            if (t.job) opt.textContent += ` (${t.job})`;
            this._templateSelect.appendChild(opt);
        });
    }

    _loadFromTemplate() {
        const idx = this._templateSelect.value;
        if (idx === "") return;
        const t = this._templates[parseInt(idx)];
        if (!t) return;
        this._name.value = t.name || "";
        this._job.value = t.job || "";
        this._gitUrl.value = t.git_url || "";
        this._branch.value = t.branch || "";
        this._ssh.value = t.ssh || "";
        if (this._nodelist) this._nodelist.value = t.nodelist || "";
        if (t.memory && this._memSlider) this._memSlider.value = parseInt(t.memory) || 4;
        if (t.cpus && this._cpuSlider) this._cpuSlider.value = parseInt(t.cpus) || 1;
        if (t.gpus !== undefined && t.gpus !== "" && this._gpuSlider) this._gpuSlider.value = parseInt(t.gpus) || 0;
        if (t.time && this._timeChips) {
            const parts = t.time.split(":");
            this._timeChips.value = parseInt(parts[0]) + parseInt(parts[1] || 0) / 60;
        }
    }

    async _submit() {
        const name = this._name.value.trim();
        const job = this._job.value.trim();
        const git_url = this._gitUrl.value.trim();
        const branch = this._branch.value.trim();
        const ssh = this._ssh.value.trim();

        if (!name) { this._name.focus(); return; }
        if (!git_url) { this._gitUrl.focus(); return; }

        const payload = {
            name, job, git_url, branch, ssh,
            memory: `${this._memSlider.value}G`,
            cpus: String(this._cpuSlider.value),
            gpus: String(this._gpuSlider.value),
            time: String(this._timeChips.value || ""),
            nodelist: this._nodelist.value || "",
        };

        this.close();
        try {
            const method = this._editName ? "PUT" : "POST";
            const url = this._editName ? `/api/tasks/${encodeURIComponent(this._editName)}` : "/api/tasks";
            const resp = await fetch(url, {
                method,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (resp.ok) {
                try {
                    await fetch("/api/settings/history", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ git_url, branch, ssh, job }),
                    });
                } catch (_) {}
                this.emit("config-success", { name: payload.name, message: data.message || `Task '${payload.name}' saved` });
            } else {
                this.emit("config-error", { name: payload.name, message: data.detail || "Failed to save task" });
            }
        } catch (e) {
            this.emit("config-error", { name: payload.name, message: e.message });
        }
    }
}

customElements.define("config-panel", ConfigPanel);

import { WesComponent } from '../base/WesComponent.js';

class SlurmDesigner extends WesComponent {
    constructor() {
        super();
        this.clusterNodes = [];
        this.clusterCapacity = [];
        this.selectedNodes = [];
    }

    async connectedCallback() {
        await this.loadTemplate('slurm-designer');

        this._shadow.getElementById('query-btn').addEventListener('click', () => this.loadNodes());
        this._shadow.getElementById('ssh-input').addEventListener('keydown', e => { if (e.key === 'Enter') this.loadNodes(); });
        this._shadow.getElementById('add-env-btn').addEventListener('click', () => this.addEnvVar());
        this._shadow.getElementById('copy-script-btn').addEventListener('click', () => {
            navigator.clipboard.writeText(this._shadow.getElementById('script-output').textContent);
        });
        this._shadow.getElementById('copy-args-btn').addEventListener('click', () => {
            navigator.clipboard.writeText(this._shadow.getElementById('args-output').textContent);
        });

        this._shadow.getElementById('time-slider').addEventListener('input', () => {
            this._shadow.querySelectorAll('.tc-btn').forEach(b => b.classList.remove('active'));
            this._updateTimeDisplay();
            this._updatePreview();
        });

        const timeChips = this._shadow.getElementById('time-chips');
        timeChips.addEventListener('time-change', () => {
            const hours = timeChips.value;
            this._shadow.getElementById('time-slider').value = hours;
            this._updateTimeDisplay();
            this._updatePreview();
        });

        ['cpu-slider', 'gpu-slider', 'mem-slider'].forEach(id => {
            this._shadow.getElementById(id).addEventListener('slider-change', () => this._updatePreview());
        });

        this._updateTimeDisplay();
        this._updatePreview();
    }

    _updateTimeDisplay() {
        const hours = parseFloat(this._shadow.getElementById('time-slider').value);
        const h = Math.floor(hours);
        const m = Math.round((hours - h) * 60);
        this._shadow.getElementById('time-display').textContent =
            String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':00';
    }

    async loadNodes() {
        const ssh = this._shadow.getElementById('ssh-input').value.trim();
        if (!ssh) return;
        const none = this._shadow.getElementById('node-none');
        none.textContent = 'Loading...';
        none.classList.remove('sd-hidden');
        this._shadow.getElementById('node-grid').innerHTML = '';

        try {
            const resp = await fetch('/api/cluster?ssh=' + encodeURIComponent(ssh));
            const data = await resp.json();
            if (data.error) { none.textContent = 'Error: ' + data.error; return; }
            this.clusterNodes = data.nodes || [];
            this.clusterCapacity = data.capacity || [];
            this.selectedNodes = [];
            this._renderPartitions();
            this._renderNodeGrid();
        } catch (err) {
            none.textContent = 'Error: ' + err.message;
        }
    }

    _renderPartitions() {
        const chips = this._shadow.getElementById('partition-chips');
        const parts = [...new Set(this.clusterNodes.map(n => n.partition).filter(Boolean))];
        if (!parts.length) { chips.classList.add('sd-hidden'); return; }
        chips.classList.remove('sd-hidden');
        const items = [{ label: 'All', value: 'all' }, ...parts.map(p => ({ label: p, value: p }))];
        chips.setOptions(items);
        chips.value = 'all';
        chips.addEventListener('chip-select', e => {
            this._renderNodeGrid(e.detail.value === 'all' ? null : e.detail.value);
        });
    }

    _renderNodeGrid(filterPart) {
        const grid = this._shadow.getElementById('node-grid');
        const none = this._shadow.getElementById('node-none');
        const nodes = filterPart ? this.clusterNodes.filter(n => n.partition === filterPart) : this.clusterNodes;

        if (!nodes.length) { grid.innerHTML = ''; none.textContent = 'No nodes found'; none.classList.remove('sd-hidden'); return; }
        none.classList.add('sd-hidden');

        const fmt = mb => mb >= 1024 ? (mb / 1024).toFixed(1).replace(/\.0$/, '') + 'G' : mb + 'M';
        grid.innerHTML = nodes.map(n => {
            const cap = this.clusterCapacity.find(c => c.name === n.name);
            const sel = this.selectedNodes.includes(n.name);
            const stateClass = n.state === 'idle' ? 'ns-idle' : n.state === 'alloc' || n.state === 'allocated' ? 'ns-alloc' : n.state === 'mix' || n.state === 'node-mix' ? 'ns-mix' : 'ns-other';

            let capHtml = '';
            if (cap) {
                const cpuPct = cap.cpu_total ? Math.round(cap.cpu_free / cap.cpu_total * 100) : 0;
                const memPct = cap.mem_total_mb ? Math.round(cap.mem_free_mb / cap.mem_total_mb * 100) : 0;
                const gpuPct = cap.gpu_total ? Math.round(cap.gpu_free / cap.gpu_total * 100) : 0;
                capHtml = `<div class="sd-ns-stats">
                    <div class="sd-ns-stat"><span class="sd-ns-stat-label">CPU</span><div class="sd-ns-bar"><div class="sd-ns-bar-fill sd-bar-free" style="width:${cpuPct}%"></div></div><span class="sd-ns-stat-val">${cap.cpu_free}/${cap.cpu_total}</span></div>
                    ${cap.gpu_total > 0 ? `<div class="sd-ns-stat"><span class="sd-ns-stat-label">GPU</span><div class="sd-ns-bar"><div class="sd-ns-bar-fill sd-bar-gpu" style="width:${gpuPct}%"></div></div><span class="sd-ns-stat-val">${cap.gpu_free}/${cap.gpu_total}</span></div>` : ''}
                    <div class="sd-ns-stat"><span class="sd-ns-stat-label">MEM</span><div class="sd-ns-bar"><div class="sd-ns-bar-fill sd-bar-mem" style="width:${memPct}%"></div></div><span class="sd-ns-stat-val">${fmt(cap.mem_free_mb)}/${fmt(cap.mem_total_mb)}</span></div>
                </div>`;
            } else {
                let meta = n.cpus + ' CPUs';
                if (n.gpus !== '-') meta += ' · ' + n.gpus + ' GPUs';
                meta += ' · ' + n.memory;
                capHtml = `<div class="sd-ns-meta">${meta}</div>`;
            }

            return `<div class="sd-ns-tile ${stateClass}${sel ? ' sd-ns-selected' : ''}" data-name="${n.name}">
                <div class="sd-ns-name">${n.name}</div>
                ${capHtml}
                <div class="sd-ns-state">${n.state}</div>
            </div>`;
        }).join('');

        grid.querySelectorAll('.sd-ns-tile').forEach(tile => {
            tile.addEventListener('click', () => this._toggleNode(tile.dataset.name));
        });
    }

    _toggleNode(name) {
        const idx = this.selectedNodes.indexOf(name);
        if (idx >= 0) this.selectedNodes.splice(idx, 1); else this.selectedNodes.push(name);
        const activeChip = this._shadow.querySelector('chip-select');
        this._renderNodeGrid(activeChip?.value === 'all' ? null : activeChip?.value);
        this._updatePreview();
    }

    _collectSpec() {
        const envVars = {};
        this._shadow.querySelectorAll('.sd-env-row').forEach(row => {
            const k = row.querySelector('.sd-env-key').value.trim();
            const v = row.querySelector('.sd-env-val').value.trim();
            if (k) envVars[k] = v;
        });

        const cpuPerTask = parseInt(this._shadow.getElementById('cpu-slider').value) || 1;
        const gpuCount = parseInt(this._shadow.getElementById('gpu-slider').value) || 0;
        const memGB = parseInt(this._shadow.getElementById('mem-slider').value) || 4;
        const hours = parseFloat(this._shadow.getElementById('time-slider').value) || 4;
        const h = Math.floor(hours);
        const m = Math.round((hours - h) * 60);
        const timeStr = String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':00';

        return {
            name: this._shadow.getElementById('job-name').value,
            partition: this.selectedNodes.length ? (this.clusterNodes.find(n => this.selectedNodes.includes(n.name))?.partition || '') : '',
            nodes: 1,
            ntasks: parseInt(this._shadow.getElementById('ntasks').value) || 1,
            cpus_per_task: cpuPerTask,
            gres: gpuCount > 0 ? 'gpu:' + gpuCount : '',
            memory: memGB + 'G',
            time: timeStr,
            nodelist: this.selectedNodes.join(','),
            account: this._shadow.getElementById('account').value,
            qos: this._shadow.getElementById('qos').value,
            output: this._shadow.getElementById('output').value,
            error: this._shadow.getElementById('error').value,
            script_path: this._shadow.getElementById('script-path').value,
            command: this._shadow.getElementById('command').value,
            env_vars: envVars,
        };
    }

    async _updatePreview() {
        const spec = this._collectSpec();
        try {
            const resp = await fetch('/api/slurm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(spec),
            });
            const data = await resp.json();
            this._shadow.getElementById('script-output').textContent = data.script;
            this._shadow.getElementById('args-output').textContent = 'sbatch ' + data.args.map(a => ' ' + a).join('');
        } catch (err) {
            this._shadow.getElementById('script-output').textContent = 'Error: ' + err.message;
        }
    }

    addEnvVar(key, val) {
        const list = this._shadow.getElementById('env-vars-list');
        const row = document.createElement('div');
        row.className = 'sd-env-row';
        row.innerHTML = `<input type="text" class="sd-env-key sd-env-input" placeholder="KEY" value="${key || ''}">
            <span class="sd-env-eq">=</span>
            <input type="text" class="sd-env-val sd-env-input" placeholder="value" value="${val || ''}">
            <button type="button" class="sd-env-del">&times;</button>`;
        list.appendChild(row);
        row.querySelectorAll('input').forEach(inp => inp.addEventListener('input', () => this._updatePreview()));
        row.querySelector('.sd-env-del').addEventListener('click', () => { row.remove(); this._updatePreview(); });
    }
}

customElements.define('slurm-designer', SlurmDesigner);

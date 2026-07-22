import { WesComponent } from '../base/WesComponent.js';

class ClusterPanel extends WesComponent {
    constructor() {
        super();
        this.allJobs = [];
        this.allNodes = [];
        this.allCapacity = [];
        this.selectedNode = null;
        this._timer = null;
        this._intervalSec = 10;
    }

    async connectedCallback() {
        await this.loadTemplate('cluster-panel');

        const savedSsh = localStorage.getItem('wes_ssh');
        if (savedSsh) this._shadow.getElementById('ssh-input').value = savedSsh;

        this._shadow.getElementById('query-btn').addEventListener('click', () => this.query());
        this._shadow.getElementById('ssh-input').addEventListener('keydown', e => { if (e.key === 'Enter') this.query(); });
        this._shadow.getElementById('show-all-btn').addEventListener('click', () => this.selectNode(null));

        await this._loadSettings();
        this._restoreCache();
        if (savedSsh) {
            this.query(true);
        }
        this._startAutoRefresh();
    }

    disconnectedCallback() {
        if (this._timer) clearInterval(this._timer);
    }

    async _loadSettings() {
        try {
            const resp = await fetch('/api/settings');
            const data = await resp.json();
            if (data.query_interval) this._intervalSec = data.query_interval;
        } catch (_) {}
    }

    _startAutoRefresh() {
        if (this._timer) clearInterval(this._timer);
        this._timer = setInterval(() => {
            const ssh = this._shadow.getElementById('ssh-input').value.trim();
            if (ssh) this.query(true);
        }, this._intervalSec * 1000);
    }

    refreshInterval() {
        this._loadSettings().then(() => this._startAutoRefresh());
    }

    _restoreCache() {
        try {
            const raw = localStorage.getItem('wes_cluster');
            if (!raw) return;
            const data = JSON.parse(raw);
            this.allNodes = data.nodes || [];
            this.allJobs = data.jobs || [];
            this.allCapacity = data.capacity || [];
            this._renderNodes();
            this._renderJobs();
        } catch (_) {}
    }

    async query(silent) {
        const ssh = this._shadow.getElementById('ssh-input').value.trim();
        if (!ssh) return;
        const btn = this._shadow.getElementById('query-btn');
        const status = this._shadow.getElementById('cluster-status');
        const errDiv = this._shadow.getElementById('cluster-error');
        if (!silent) { btn.disabled = true; status.textContent = 'Querying...'; }
        errDiv.innerHTML = '';

        try {
            const resp = await fetch('/api/cluster?ssh=' + encodeURIComponent(ssh));
            const data = await resp.json();
            if (data.error) {
                if (!silent) errDiv.innerHTML = `<div class="cp-error">${data.error}</div>`;
                return;
            }
            this.allNodes = data.nodes || [];
            this.allJobs = data.jobs || [];
            this.allCapacity = data.capacity || [];
            this.selectedNode = null;
            this._renderNodes();
            this._renderJobs();
            localStorage.setItem('wes_ssh', ssh);
            localStorage.setItem('wes_cluster', JSON.stringify({ nodes: this.allNodes, jobs: this.allJobs, capacity: this.allCapacity }));
        } catch (err) {
            if (!silent) errDiv.innerHTML = `<div class="cp-error">${err.message}</div>`;
        } finally {
            btn.disabled = false;
            status.textContent = this.allNodes.length + ' nodes, ' + this.allJobs.length + ' jobs';
        }
    }

    selectNode(name) {
        this.selectedNode = name;
        this._renderNodes();
        this._renderJobs();
    }

    _renderNodes() {
        const grid = this._shadow.getElementById('node-grid');
        const section = this._shadow.getElementById('nodes-section');
        if (!this.allNodes.length) { section.style.display = 'none'; return; }
        section.style.display = '';

        const idle = this.allNodes.filter(n => n.state === 'idle').length;
        const alloc = this.allNodes.filter(n => n.state === 'alloc' || n.state === 'allocated').length;
        const mix = this.allNodes.filter(n => n.state === 'mix' || n.state === 'node-mix').length;
        this._shadow.getElementById('node-count').textContent = idle + ' idle · ' + alloc + ' alloc · ' + mix + ' mix';

        grid.innerHTML = '';
        this.allNodes.forEach(n => {
            const el = document.createElement('node-card');
            const stateClass = n.state === 'idle' ? 'ns-idle' : n.state === 'alloc' || n.state === 'allocated' ? 'ns-alloc' : n.state === 'mix' || n.state === 'node-mix' ? 'ns-mix' : 'ns-other';
            el.className = stateClass;
            if (this.selectedNode === n.name) el.setAttribute('selected', '');
            el.data = {
                name: n.name,
                state: n.state,
                jobCount: this.allJobs.filter(j => j.nodes && j.nodes.includes(n.name)).length,
                capacity: this.allCapacity.find(c => c.name === n.name) || null,
                cpus: n.cpus,
                gpus: n.gpus,
                memory: n.memory,
                partition: n.partition,
            };
            el.addEventListener('node-click', e => this.selectNode(e.detail.name));
            grid.appendChild(el);
        });
    }

    _renderJobs() {
        const panel = this._shadow.getElementById('jobs-panel');
        const tbl = this._shadow.getElementById('jobs-tbl');
        const controls = this._shadow.getElementById('jobs-controls');
        const title = this._shadow.getElementById('jobs-title');

        let jobs = this.allJobs;
        if (this.selectedNode) {
            jobs = this.allJobs.filter(j => j.nodes && j.nodes.includes(this.selectedNode));
            title.textContent = 'Jobs — ' + this.selectedNode;
            controls.style.display = '';
        } else {
            title.textContent = 'All Jobs';
            controls.style.display = 'none';
        }

        panel.style.display = '';
        if (tbl) tbl.data = jobs;
    }
}

customElements.define('cluster-panel', ClusterPanel);

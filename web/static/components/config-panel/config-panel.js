import { WesComponent } from '../base/WesComponent.js';

class ConfigPanel extends WesComponent {
    constructor() {
        super();
        this._editing = false;
        this._data = null;
    }

    async connectedCallback() {
        await this.loadTemplate('config-panel');

        this._shadow.getElementById('close-btn').addEventListener('click', () => this.close());
        this._shadow.getElementById('cancel-btn').addEventListener('click', () => this.close());
        this._shadow.getElementById('submit-btn').addEventListener('click', () => this._submit());

        this._shadow.getElementById('time-chips').addEventListener('time-change', e => {
            this._time = e.detail.time;
        });

        this._shadow.getElementById('mem-slider').addEventListener('slider-change', e => {
            this._mem = e.detail.value;
        });
        this._shadow.getElementById('cpu-slider').addEventListener('slider-change', e => {
            this._cpus = e.detail.value;
        });
        this._shadow.getElementById('gpu-slider').addEventListener('slider-change', e => {
            this._gpus = e.detail.value;
        });
    }

    open(data) {
        this._data = data;
        this._editing = !!data.editing;
        const panel = this._shadow.getElementById('panel');
        const title = this._shadow.getElementById('title');
        panel.classList.remove('hidden');

        const tc = this._shadow.getElementById('time-chips');

        if (data.editing) {
            title.textContent = data.name;
            this._shadow.getElementById('name').value = data.name || '';
            this._shadow.getElementById('git-url').value = data.git_url || '';
            this._shadow.getElementById('branch').value = data.branch || '';
            this._shadow.getElementById('ssh').value = data.ssh || '';
            this._shadow.getElementById('job').value = data.job || '';
            this._shadow.getElementById('nodelist').value = data.nodelist || '';

            this._mem = this._parseMemGB(data.memory) || 4;
            this._cpus = parseInt(data.cpus) || 1;
            this._gpus = parseInt(data.gpus) || 0;
            this._time = data.time || '04:00:00';
        } else {
            title.textContent = 'New Task';
            this._shadow.getElementById('name').value = '';
            this._shadow.getElementById('git-url').value = '';
            this._shadow.getElementById('branch').value = '';
            this._shadow.getElementById('ssh').value = '';
            this._shadow.getElementById('job').value = '';
            this._shadow.getElementById('nodelist').value = '';
            this._mem = 4;
            this._cpus = 1;
            this._gpus = 0;
            this._time = '04:00:00';
        }

        const memSlider = this._shadow.getElementById('mem-slider');
        memSlider.value = this._mem;
        const cpuSlider = this._shadow.getElementById('cpu-slider');
        cpuSlider.value = this._cpus;
        const gpuSlider = this._shadow.getElementById('gpu-slider');
        gpuSlider.value = this._gpus;
        tc.value = tc.parseTime(this._time);
    }

    close() {
        this._shadow.getElementById('panel').classList.add('hidden');
        this._editing = false;
        this._data = null;
    }

    async loadNodeOptions(nodes) {
        const select = this._shadow.getElementById('nodelist');
        const current = select.value;
        let html = '<option value="">any</option>';
        nodes.forEach(n => {
            const sel = n.name === current ? ' selected' : '';
            html += `<option value="${n.name}"${sel}>${n.name} (${n.state})</option>`;
        });
        select.innerHTML = html;
        if (current) select.value = current;
    }

    async _submit() {
        const btn = this._shadow.getElementById('submit-btn');
        btn.disabled = true;
        btn.textContent = '...';

        const name = this._shadow.getElementById('name').value.trim();
        if (!name) {
            btn.disabled = false;
            btn.textContent = 'Run';
            this.emit('config-error', { message: 'Task name is required' });
            return;
        }

        const tc = this._shadow.getElementById('time-chips');
        const time = tc.formatTime(tc.value);

        const payload = {
            name,
            git_url: this._shadow.getElementById('git-url').value.trim(),
            branch: this._shadow.getElementById('branch').value.trim(),
            ssh: this._shadow.getElementById('ssh').value.trim(),
            job: this._shadow.getElementById('job').value.trim() || name,
            memory: this._mem + 'G',
            cpus: String(this._cpus),
            gpus: String(this._gpus),
            time,
            nodelist: this._shadow.getElementById('nodelist').value.trim(),
        };

        try {
            let resp;
            if (this._editing) {
                const overrides = {};
                if (payload.nodelist) overrides.nodelist = payload.nodelist;
                overrides.memory = payload.memory;
                overrides.cpus = payload.cpus;
                overrides.gpus = payload.gpus;
                overrides.time = payload.time;
                resp = await fetch('/api/submit', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ name, overrides }),
                });
            } else {
                resp = await fetch('/api/tasks', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload),
                });
            }
            const data = await resp.json();
            if (resp.ok) {
                this.emit('config-success', { message: data.message || (data.task + ': ' + data.state) });
                this.close();
            } else {
                this.emit('config-error', { message: 'Error: ' + (data.detail || 'Unknown error') });
            }
        } catch (err) {
            this.emit('config-error', { message: 'Error: ' + err.message });
        } finally {
            btn.disabled = false;
            btn.textContent = 'Run';
        }
    }

    _parseMemGB(s) {
        if (!s) return 0;
        s = s.trim().toUpperCase();
        if (s.endsWith('G')) return parseFloat(s);
        if (s.endsWith('M')) return Math.round(parseInt(s) / 1024) || 1;
        return parseInt(s) || 0;
    }
}

customElements.define('config-panel', ConfigPanel);

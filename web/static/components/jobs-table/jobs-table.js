import { WesComponent } from '../base/WesComponent.js';

const COLUMNS = [
    { key: 'job_id', label: 'ID' },
    { key: 'name', label: 'Name' },
    { key: 'user', label: 'User' },
    { key: 'state', label: 'State' },
    { key: 'priority', label: 'Priority' },
    { key: 'time', label: 'Time' },
    { key: 'cpus', label: 'CPUs' },
    { key: 'memory', label: 'Memory' },
    { key: 'nodes', label: 'Nodes' },
    { key: 'partition', label: 'Partition' },
];

class JobsTable extends WesComponent {
    constructor() {
        super();
        this._sortKey = 'priority';
        this._sortAsc = false;
    }

    async connectedCallback() {
        await this.loadTemplate('jobs-table');
        this.render(this._jobs || []);
    }

    set data(jobs) { this._jobs = jobs; if (this._ready) this.render(jobs); }

    _renderHeaders() {
        this._headerRow.innerHTML = COLUMNS.map(col => {
            let label = col.label;
            if (col.key === this._sortKey) {
                label += ' <i data-lucide="' + (this._sortAsc ? 'chevron-up' : 'chevron-down') + '"></i>';
            }
            return `<th data-key="${col.key}" class="${col.key === this._sortKey ? 'sorted' : ''}">${label}</th>`;
        }).join('');
        WesComponent.icons(this._shadow);
        this._headerRow.addEventListener('click', e => {
            const th = e.target.closest('th');
            if (!th) return;
            const key = th.getAttribute('data-key');
            if (this._sortKey === key) this._sortAsc = !this._sortAsc;
            else { this._sortKey = key; this._sortAsc = false; }
            this.render(this._jobs);
        });
    }

    render(jobs) {
        if (!this._headerRow) {
            this._headerRow = this._shadow.getElementById('header-row');
            this._tbody = this._shadow.getElementById('tbody');
        }
        if (this._headerRow) this._renderHeaders();
        const tbody = this._tbody;
        if (!tbody) return;
        if (!jobs || !jobs.length) {
            tbody.innerHTML = '<tr><td colspan="' + COLUMNS.length + '" class="jt-empty">No jobs found</td></tr>';
            return;
        }

        const sorted = [...jobs].sort((a, b) => {
            let va, vb;
            if (this._sortKey === 'priority' || this._sortKey === 'cpus') {
                va = parseInt(a[this._sortKey]) || 0;
                vb = parseInt(b[this._sortKey]) || 0;
            } else if (this._sortKey === 'state') {
                const order = { RUNNING: 0, PENDING: 1, COMPLETED: 2, FAILED: 3, CANCELLED: 4 };
                va = order[a.state] ?? 99;
                vb = order[b.state] ?? 99;
            } else {
                va = (a[this._sortKey] || '').toLowerCase();
                vb = (b[this._sortKey] || '').toLowerCase();
            }
            const cmp = typeof va === 'number' ? va - vb : va.localeCompare(vb);
            return this._sortAsc ? cmp : -cmp;
        });

        const stateColor = s => s === 'RUNNING' ? 'running' : s === 'PENDING' ? 'pending' : s === 'FAILED' ? 'failed' : 'completed';
        tbody.innerHTML = sorted.map(j => {
            const sc = stateColor(j.state);
            return `<tr>
                <td><span class="dot dot-${sc}"></span> ${j.job_id || ''}</td>
                <td class="jt-name mono">${j.name || ''}</td>
                <td style="color:var(--text-secondary,#5f6368)">${j.user || ''}</td>
                <td><span class="badge badge-${sc}">${j.state || ''}</span></td>
                <td class="mono" style="color:var(--text-secondary,#5f6368)">${j.priority != null && j.priority !== '' ? j.priority : ''}</td>
                <td class="mono" style="color:var(--text-secondary,#5f6368)">${j.time || ''}</td>
                <td class="mono" style="color:var(--text-secondary,#5f6368)">${j.cpus || ''}</td>
                <td class="mono" style="color:var(--text-secondary,#5f6368)">${j.memory || ''}</td>
                <td class="mono" style="color:var(--text-secondary,#5f6368);max-width:120px">${j.nodes || '-'}</td>
                <td style="color:var(--text-secondary,#5f6368)">${j.partition || ''}</td>
            </tr>`;
        }).join('');
    }
}

customElements.define('jobs-table', JobsTable);

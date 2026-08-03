import { WesComponent } from '../base/WesComponent.js';

class TaskTable extends WesComponent {
    async connectedCallback() {
        await this.loadTemplate('task-table');
        this._initEvents();
        if (this._tasks) this.render();
    }

    set data(tasks) { this._tasks = tasks; if (this._ready) this.render(); }

    _initEvents() {
        this._shadow.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-act]');
            if (btn) {
                e.preventDefault();
                e.stopPropagation();
                const x = this._tasks && this._tasks[btn.dataset.i];
                if (!x) return;
                const act = btn.dataset.act;
                if (act === 'launch') this.emit('task-launch', { name: x.name, task: x });
                else if (act === 'edit') this.emit('task-edit', { index: parseInt(btn.dataset.i, 10), name: x.name });
                else this.emit('task-delete', { name: x.name, run_id: x.run_id || '' });
                return;
            }
            const row = e.target.closest('[data-launch]');
            if (row) {
                e.preventDefault();
                const x = this._tasks && this._tasks[row.dataset.launch];
                if (x) this.emit('task-launch', { name: x.name, task: x });
            }
        });
    }

    _esc(s) {
        return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    _res(x) {
        const r = [];
        if (x.cpus) r.push(x.cpus + ' CPU');
        if (x.gpus && x.gpus !== '0') r.push(x.gpus + ' GPU');
        if (x.memory) r.push(x.memory);
        if (x.time) r.push(x.time);
        return r;
    }

    _actions(i) {
        return `<span class="tt-actions">
            <button class="tt-btn" data-act="launch" data-i="${i}" title="Launch"><i data-lucide="play"></i></button>
            <button class="tt-btn" data-act="edit" data-i="${i}" title="Configure"><i data-lucide="settings"></i></button>
            <button class="tt-btn tt-del" data-act="delete" data-i="${i}" title="Remove"><i data-lucide="trash-2"></i></button>
        </span>`;
    }

    _repoBranch(x) {
        return (x.repo ? this._esc(x.repo) + '<span class="tt-at">@</span>' : '') + this._esc(x.branch || '');
    }

    _row(x, i) {
        return `<tr class="tt-row" data-launch="${i}">
            <td class="tt-tname">${this._esc(x.name)}</td>
            <td class="mono">${this._esc(x.job || '')}</td>
            <td class="mono">${this._repoBranch(x)}</td>
            <td class="mono">${this._esc(x.partition || '')}</td>
            <td class="mono">${this._res(x).map(r => this._esc(r)).join(' · ')}</td>
            <td class="mono">${(x.artifacts || []).map(a => this._esc(a)).join(', ')}</td>
            <td>${this._actions(i)}</td>
        </tr>`;
    }

    render() {
        const rows = this._shadow.getElementById('rows');
        if (!rows) return;
        rows.innerHTML = (this._tasks || []).map((x, i) => this._row(x, i)).join('');
        WesComponent.icons(this._shadow);
    }
}

customElements.define('task-table', TaskTable);

import { WesComponent } from '../base/WesComponent.js';

class TaskTile extends WesComponent {
    async connectedCallback() {
        await this.loadTemplate('task-tile');
        if (this._data) this.render();
    }

    set data(d) { this._data = d; if (this._ready) this.render(); }

    render() {
        const d = this._data;
        if (!d) return;

        const tile = this._shadow.getElementById('tile');
        if (!tile) return;
        tile.href = '#';

        this._shadow.getElementById('name').textContent = d.name;

        const dot = this._shadow.getElementById('dot');
        dot.className = 'dot dot-' + (d.status || 'pending').toLowerCase();

        const artifacts = this._shadow.getElementById('artifacts');
        artifacts.textContent = d.artifactCount > 0 ? d.artifactCount + ' files' : '';
        artifacts.style.display = d.artifactCount > 0 ? '' : 'none';

        this._shadow.getElementById('repo').textContent = d.repo || '';
        this._shadow.getElementById('repo').style.display = d.repo ? '' : 'none';

        this._shadow.getElementById('branch').textContent = d.branch || '';
        this._shadow.getElementById('branch').style.display = d.branch ? '' : 'none';

        const res = this._shadow.getElementById('resources');
        let resHtml = '';
        if (d.memory) resHtml += `<span>${d.memory}</span>`;
        if (d.cpus) resHtml += `<span>${d.cpus} CPU</span>`;
        if (d.gpus && d.gpus !== '0') resHtml += `<span>${d.gpus} GPU</span>`;
        if (d.time) resHtml += `<span>${d.time}</span>`;
        res.innerHTML = resHtml;

        this._shadow.getElementById('launch-btn').onclick = e => {
            e.preventDefault();
            e.stopPropagation();
            this.emit('task-launch', { name: d.name, task: d });
        };

        this._shadow.getElementById('edit-btn').onclick = e => {
            e.preventDefault();
            e.stopPropagation();
            this.emit('task-edit', { index: d.index, name: d.name });
        };

        this._shadow.getElementById('delete-btn').onclick = e => {
            e.preventDefault();
            e.stopPropagation();
            this.emit('task-delete', { name: d.name });
        };
    }
}

customElements.define('task-tile', TaskTile);

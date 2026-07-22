import { WesComponent } from '../base/WesComponent.js';

class NodeCard extends WesComponent {
    static get observedAttributes() { return ['name', 'state', 'selected']; }

    async connectedCallback() {
        await this.loadTemplate('node-card');
        if (this._data) this.render();
    }

    set data(d) { this._data = d; if (this._ready) this.render(); }

    render() {
        const d = this._data;
        if (!d) return;

        const nameEl = this._shadow.getElementById('name');
        if (!nameEl) return;

        nameEl.textContent = d.name;
        this._shadow.getElementById('state').textContent = d.state;

        const card = this._shadow.getElementById('card');
        card.classList.toggle('selected', this.hasAttribute('selected'));

        const countEl = this._shadow.getElementById('count');
        if (d.jobCount > 0) {
            countEl.textContent = d.jobCount;
            countEl.style.display = '';
        } else {
            countEl.style.display = 'none';
        }

        const capEl = this._shadow.getElementById('cap');
        const metaEl = this._shadow.getElementById('meta');
        const partEl = this._shadow.getElementById('partition');

        if (d.capacity) {
            const fmt = mb => mb >= 1024 ? Math.round(mb / 1024) + 'G' : mb + 'M';
            const cpuPct = d.capacity.cpu_total ? Math.round(d.capacity.cpu_alloc / d.capacity.cpu_total * 100) : 0;
            let capHtml = `<div class="nc-cap-row"><span class="nc-cap-label">CPU</span><div class="nc-cap-bar"><div class="nc-cap-bar-fill cpu" style="width:${cpuPct}%"></div></div><span class="nc-cap-text">${d.capacity.cpu_alloc}/${d.capacity.cpu_total}</span></div>`;
            if (d.capacity.gpu_total > 0) {
                const gpuPct = Math.round(d.capacity.gpu_alloc / d.capacity.gpu_total * 100);
                capHtml += `<div class="nc-cap-row"><span class="nc-cap-label">GPU</span><div class="nc-cap-bar"><div class="nc-cap-bar-fill gpu" style="width:${gpuPct}%"></div></div><span class="nc-cap-text">${d.capacity.gpu_alloc}/${d.capacity.gpu_total}</span></div>`;
            }
            const memPct = d.capacity.mem_total_mb ? Math.round(d.capacity.mem_alloc_mb / d.capacity.mem_total_mb * 100) : 0;
            capHtml += `<div class="nc-cap-row"><span class="nc-cap-label">MEM</span><div class="nc-cap-bar"><div class="nc-cap-bar-fill mem" style="width:${memPct}%"></div></div><span class="nc-cap-text">${fmt(d.capacity.mem_alloc_mb)}/${fmt(d.capacity.mem_total_mb)}</span></div>`;
            capEl.innerHTML = capHtml;
            metaEl.innerHTML = '';
        } else {
            capEl.innerHTML = '';
            let meta = d.cpus + ' CPUs';
            if (d.gpus && d.gpus !== '-') meta += ' · ' + d.gpus + ' GPUs';
            meta += ' · ' + d.memory;
            metaEl.textContent = meta;
        }

        partEl.textContent = d.partition || '';
        partEl.style.display = d.partition ? '' : 'none';

        card.onclick = () => this.emit('node-click', { name: d.name });
    }
}

customElements.define('node-card', NodeCard);

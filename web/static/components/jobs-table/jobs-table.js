import { WesComponent } from '../base/WesComponent.js';

class JobsTable extends WesComponent {
    async connectedCallback() {
        await this.loadTemplate('jobs-table');
        this.render([]);
    }

    set data(jobs) { this._jobs = jobs; this.render(jobs); }

    render(jobs) {
        const tbody = this._shadow.getElementById('tbody');
        if (!jobs || !jobs.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="jt-empty">No jobs found</td></tr>';
            return;
        }
        const stateColor = s => s === 'RUNNING' ? 'running' : s === 'PENDING' ? 'pending' : s === 'FAILED' ? 'failed' : 'completed';
        tbody.innerHTML = jobs.map(j => `
            <tr>
                <td><span class="dot dot-${stateColor(j.state)}"></span></td>
                <td class="jt-name mono">${j.name}</td>
                <td style="color:var(--text-secondary,#5f6368)">${j.user}</td>
                <td><span class="badge badge-${stateColor(j.state)}">${j.state}</span></td>
                <td class="mono" style="color:var(--text-secondary,#5f6368)">${j.time}</td>
                <td class="mono" style="color:var(--text-secondary,#5f6368)">${j.cpus}</td>
                <td class="mono" style="color:var(--text-secondary,#5f6368)">${j.memory}</td>
                <td class="mono" style="color:var(--text-secondary,#5f6368);max-width:120px">${j.nodes || '-'}</td>
                <td style="color:var(--text-secondary,#5f6368)">${j.partition}</td>
            </tr>
        `).join('');
    }
}

customElements.define('jobs-table', JobsTable);

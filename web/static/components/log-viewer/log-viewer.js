import { WesComponent } from '../base/WesComponent.js';

class LogViewer extends WesComponent {
    constructor() {
        super();
        this._tabs = [];
        this._active = null;
    }

    async connectedCallback() {
        await this.loadTemplate('log-viewer');
    }

    set tabs(t) {
        this._tabs = t;
        this._active = t[0]?.name || null;
        this._renderTabs();
    }

    setLogs(name, content) {
        if (!this._shadow.querySelector(`[data-log="${name}"]`)) {
            const body = this._shadow.querySelector('.lv-body');
            const pre = document.createElement('div');
            pre.className = 'lv-log';
            pre.dataset.log = name;
            pre.textContent = content || '(empty)';
            pre.style.display = name === this._active ? '' : 'none';
            body.appendChild(pre);
        }
    }

    _renderTabs() {
        const tabs = this._shadow.getElementById('tabs');
        tabs.innerHTML = this._tabs.map(t =>
            `<button class="lv-tab${t.name === this._active ? ' active' : ''}" data-tab="${t.name}">${t.label}</button>`
        ).join('');

        tabs.querySelectorAll('.lv-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                this._active = btn.dataset.tab;
                this._shadow.querySelectorAll('.lv-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === this._active));
                this._shadow.querySelectorAll('[data-log]').forEach(el => el.style.display = el.dataset.log === this._active ? '' : 'none');
            });
        });
    }
}

customElements.define('log-viewer', LogViewer);

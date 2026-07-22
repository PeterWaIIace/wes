import { WesComponent } from '../base/WesComponent.js';

class LogViewer extends WesComponent {
    constructor() {
        super();
        this._tabs = [];
        this._active = null;
        this._logs = {};
    }

    async connectedCallback() {
        await this.loadTemplate('log-viewer');
        if (this._tabs.length) this._renderTabs();
        Object.entries(this._logs).forEach(([name, content]) => this._setLog(name, content));
    }

    set tabs(t) {
        this._tabs = t;
        this._active = t[0]?.name || null;
        if (this._ready) this._renderTabs();
    }

    setLogs(name, content) {
        this._logs[name] = content;
        if (this._ready) this._setLog(name, content);
    }

    _setLog(name, content) {
        let pre = this._shadow.querySelector(`[data-log="${name}"]`);
        if (!pre) {
            pre = document.createElement('div');
            pre.className = 'lv-log';
            pre.dataset.log = name;
            this._shadow.querySelector('.lv-body').appendChild(pre);
        }
        pre.textContent = content || '(empty)';
        pre.style.display = name === this._active ? '' : 'none';
    }

    _renderTabs() {
        const tabs = this._shadow.getElementById('tabs');
        if (!tabs) return;
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

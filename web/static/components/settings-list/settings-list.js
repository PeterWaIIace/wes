import { WesComponent } from '../base/WesComponent.js';

class SettingsList extends WesComponent {
    async connectedCallback() {
        await this.loadTemplate('settings-list');
    }

    set items(arr) {
        this._items = arr;
        this.render();
    }

    render() {
        const list = this._shadow.getElementById('list');
        const empty = this._shadow.getElementById('empty');

        if (!this._items || !this._items.length) {
            list.innerHTML = '';
            empty.style.display = '';
            return;
        }

        empty.style.display = 'none';
        list.innerHTML = this._items.map((item, i) => `
            <div class="sl-item">
                <span class="mono">${item}</span>
                <button class="sl-btn" data-index="${i}" title="Remove">&#x2715;</button>
            </div>
        `).join('');

        list.querySelectorAll('.sl-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.emit('settings-remove', { index: parseInt(btn.dataset.index) });
            });
        });
    }
}

customElements.define('settings-list', SettingsList);

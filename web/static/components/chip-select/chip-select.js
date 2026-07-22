import { WesComponent } from '../base/WesComponent.js';

class ChipSelect extends WesComponent {
    constructor() {
        super();
        this._value = null;
    }

    async connectedCallback() {
        await this.loadTemplate('chip-select');
        this.render();
    }

    setOptions(items) {
        this._items = items;
        this.render();
    }

    get value() { return this._value; }
    set value(v) { this._value = v; this._highlight(); }

    render() {
        const container = this._shadow.getElementById('chips');
        if (!this._items) return;
        container.innerHTML = this._items.map((item, i) =>
            `<span class="cs-chip${item.value === this._value ? ' active' : ''}" data-value="${item.value}">${item.label}</span>`
        ).join('');

        container.querySelectorAll('.cs-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                this._value = chip.dataset.value;
                this._highlight();
                this.emit('chip-select', { value: this._value });
            });
        });
    }

    _highlight() {
        this._shadow.querySelectorAll('.cs-chip').forEach(chip => {
            chip.classList.toggle('active', chip.dataset.value === this._value);
        });
    }
}

customElements.define('chip-select', ChipSelect);

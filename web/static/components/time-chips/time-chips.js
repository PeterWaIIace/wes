import { WesComponent } from '../base/WesComponent.js';

const PRESETS = [
    { label: '30m', hours: 0.5 },
    { label: '1h', hours: 1 },
    { label: '2h', hours: 2 },
    { label: '4h', hours: 4 },
    { label: '8h', hours: 8 },
    { label: '24h', hours: 24 },
    { label: '2d', hours: 48 },
    { label: '7d', hours: 168 },
];

class TimeChips extends WesComponent {
    static get observedAttributes() { return ['value']; }

    constructor() {
        super();
        this._value = 4;
    }

    async connectedCallback() {
        await this.loadTemplate('time-chips');
        this.render();
    }

    get value() { return this._value; }
    set value(h) { this._value = h; this.render(); }

    formatTime(hours) {
        const h = Math.floor(hours);
        const m = Math.round((hours - h) * 60);
        return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0') + ':00';
    }

    parseTime(s) {
        if (!s) return 0;
        const parts = s.trim().split(':');
        if (parts.length === 3) return parseInt(parts[0]) + parseInt(parts[1]) / 60;
        return parseFloat(s) || 0;
    }

    render() {
        const container = this._shadow.querySelector('.tc-chips');
        container.innerHTML = PRESETS.map(p =>
            `<button type="button" class="tc-btn${p.hours === this._value ? ' active' : ''}" data-hours="${p.hours}">${p.label}</button>`
        ).join('');

        container.querySelectorAll('.tc-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this._value = parseFloat(btn.dataset.hours);
                this.render();
                this.emit('time-change', { hours: this._value, time: this.formatTime(this._value) });
            });
        });
    }
}

customElements.define('time-chips', TimeChips);

import { WesComponent } from '../base/WesComponent.js';

class ResourceSlider extends WesComponent {
    static get observedAttributes() { return ['min', 'max', 'value', 'suffix', 'color']; }

    constructor() {
        super();
        this._min = 1;
        this._max = 64;
        this._value = 1;
        this._suffix = '';
    }

    async connectedCallback() {
        const minAttr = this.getAttribute('min');
        const maxAttr = this.getAttribute('max');
        const valAttr = this.getAttribute('value');
        const parsedMin = minAttr !== null ? parseInt(minAttr) : NaN;
        const parsedMax = maxAttr !== null ? parseInt(maxAttr) : NaN;
        const parsedVal = valAttr !== null ? parseInt(valAttr) : NaN;
        this._min = Number.isFinite(parsedMin) ? parsedMin : 1;
        this._max = Number.isFinite(parsedMax) ? parsedMax : 64;
        this._value = Number.isFinite(parsedVal) ? parsedVal : 1;
        this._suffix = this.getAttribute('suffix') || '';

        await this.loadTemplate('resource-slider');

        const slider = this._shadow.getElementById('slider');
        slider.min = this._min;
        slider.max = this._max;
        slider.value = this._value;
        this._shadow.getElementById('val').textContent = this._value + this._suffix;

        slider.addEventListener('input', () => {
            this._value = parseInt(slider.value);
            this._shadow.getElementById('val').textContent = this._value + this._suffix;
            this.emit('slider-change', { value: this._value });
        });
    }

    get value() { return this._value; }
    set value(v) {
        this._value = v;
        const slider = this._shadow.getElementById('slider');
        if (slider) {
            slider.value = v;
            this._shadow.getElementById('val').textContent = v + this._suffix;
        }
    }
}

customElements.define('resource-slider', ResourceSlider);

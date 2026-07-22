export class WesComponent extends HTMLElement {
    constructor() {
        super();
        this._shadow = this.attachShadow({ mode: 'open' });
    }

    async loadTemplate(name) {
        const base = `/static/components/${name}`;
        const [html, css] = await Promise.all([
            fetch(`${base}/${name}.html`).then(r => r.text()),
            fetch(`${base}/${name}.css`).then(r => r.text()),
        ]);
        this._shadow.innerHTML = `<style>${css}</style>${html}`;
    }

    $(sel) { return this._shadow.querySelector(sel); }
    $$(sel) { return this._shadow.querySelectorAll(sel); }

    emit(name, detail) {
        this.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail }));
    }
}

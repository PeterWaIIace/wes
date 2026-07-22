import { WesComponent } from '../base/WesComponent.js';

class ArtifactList extends WesComponent {
    async connectedCallback() {
        await this.loadTemplate('artifact-list');
        this._shadow.getElementById('refresh-btn').addEventListener('click', () => {
            this.emit('artifacts-refresh');
        });
        if (this._artifacts) this.render();
    }

    set data(artifacts) { this._artifacts = artifacts; if (this._ready) this.render(); }

    render() {
        const content = this._shadow.getElementById('content');
        if (!content) return;
        const a = this._artifacts;
        if (!a || !a.length) {
            content.innerHTML = '<div class="al-body"><p class="al-empty">No artifacts found</p></div>';
            return;
        }

        const videos = a.filter(x => x.kind === 'video');
        const models = a.filter(x => x.kind === 'model');
        const csvs = a.filter(x => x.kind === 'csv');
        const images = a.filter(x => x.kind === 'image');

        let html = '';

        if (videos.length) {
            html += `<div class="al-section-header"><h2>Videos</h2><span class="al-meta">${videos.length}</span></div>`;
            html += '<div class="al-body"><div class="al-video-grid">';
            videos.reverse().forEach(v => {
                html += `<div class="al-video-item"><video controls preload="metadata"><source src="${v.url}" type="video/mp4"></video><div class="al-video-label">${v.name}</div></div>`;
            });
            html += '</div></div>';
        }

        if (models.length) {
            html += `<div class="al-section-header"><h2>Models</h2><span class="al-meta">${models.length}</span></div>`;
            html += '<div class="al-body flush"><div class="al-model-list">';
            models.reverse().forEach(m => {
                html += `<div class="al-model-item"><a href="${m.url}" download>${m.name}</a><span class="al-size">${m.sizeLabel}</span></div>`;
            });
            html += '</div></div>';
        }

        if (images.length) {
            html += `<div class="al-section-header"><h2>Images</h2><span class="al-meta">${images.length}</span></div>`;
            html += '<div class="al-body"><div class="al-image-grid">';
            images.forEach(img => {
                html += `<div class="al-image-item"><img src="${img.url}" alt="${img.name}" loading="lazy"></div>`;
            });
            html += '</div></div>';
        }

        if (csvs.length) {
            html += `<div class="al-section-header"><h2>Data Files</h2><span class="al-meta">${csvs.length}</span></div>`;
            html += '<div class="al-body flush"><div class="al-model-list">';
            csvs.forEach(c => {
                html += `<div class="al-model-item"><a href="${c.url}">${c.name}</a><span class="al-size">${c.sizeLabel}</span></div>`;
            });
            html += '</div></div>';
        }

        content.innerHTML = html;
    }
}

customElements.define('artifact-list', ArtifactList);

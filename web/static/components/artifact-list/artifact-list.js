import { WesComponent } from '../base/WesComponent.js';

class ArtifactList extends WesComponent {
    async connectedCallback() {
        await this.loadTemplate('artifact-list');
        this._initHeader();
        const content = this._shadow.getElementById('content');
        if (content) this._initTree(content);
        if (this._artifacts) this.render();
    }

    set data(artifacts) {
        this._artifacts = artifacts;
        if (!this._defaultDone) {
            this._defaultDone = true;
            const tree = this._buildTree();
            if (this._countEntries(tree) <= 10) {
                this._open = new Set(this._allFolderKeys(tree));
            } else {
                this._open = new Set();
            }
        }
        if (this._ready) this.render();
    }

    _initHeader() {
        const header = this._shadow.querySelector('.al-header');
        if (!header) return;
        header.innerHTML = '<h2>Artifacts</h2><div class="al-actions"></div>';
    }

    _initTree(content) {
        content.addEventListener('click', (e) => {
            const line = e.target.closest('.al-line');
            if (!line) return;
            if (line.parentElement.classList.contains('al-folder')) {
                const key = line.parentElement.getAttribute('data-key');
                if (this._open.has(key)) this._open.delete(key);
                else this._open.add(key);
                line.parentElement.classList.toggle('open');
                return;
            }
            const video = line.closest('.al-video-toggle');
            if (video) {
                const inline = video.nextElementSibling;
                if (inline && inline.classList.contains('al-video-inline')) {
                    if (inline.hasAttribute('hidden')) inline.removeAttribute('hidden');
                    else inline.setAttribute('hidden', '');
                }
            }
        });
    }

    _esc(s) {
        return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    _formatSize(bytes) {
        if (!bytes) return '';
        const units = ['B', 'KB', 'MB', 'GB'];
        let i = 0, v = bytes;
        while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
        return (i === 0 ? v : v.toFixed(1)) + ' ' + units[i];
    }

    _buildTree() {
        const root = { name: '', children: {}, files: [] };
        this._artifacts.forEach(a => {
            const parts = a.path.split('/').filter(Boolean);
            let node = root;
            let key = '';
            parts.forEach((part, i) => {
                if (i === parts.length - 1) {
                    node.files.push(a);
                } else {
                    key = key ? key + '/' + part : part;
                    if (!node.children[key]) node.children[key] = { name: part, children: {}, files: [] };
                    node = node.children[key];
                }
            });
        });
        return root;
    }

    _allFolderKeys(node, out = []) {
        for (const k in node.children) {
            out.push(k);
            this._allFolderKeys(node.children[k], out);
        }
        return out;
    }

    _countEntries(node) {
        let n = node.files.length;
        for (const k in node.children) n += 1 + this._countEntries(node.children[k]);
        return n;
    }

    _renderNode(node, prefix) {
        const folders = Object.keys(node.children).sort();
        const files = [...node.files].sort((x, y) => x.name.localeCompare(y.name));
        const entries = [
            ...folders.map(k => ({ type: 'folder', key: k, folder: node.children[k] })),
            ...files.map(f => ({ type: 'file', file: f })),
        ];

        let html = '';
        entries.forEach((entry, i) => {
            const last = i === entries.length - 1;
            const branch = last ? '└── ' : '├── ';
            const childPrefix = prefix + (last ? '    ' : '│   ');
            if (entry.type === 'folder') {
                const open = this._open.has(entry.key);
                html += `<div class="al-folder${open ? ' open' : ''}" data-key="${this._esc(entry.key)}">
                    <div class="al-line"><span class="al-conn">${prefix}${branch}</span><span class="al-folder-name">${this._esc(entry.folder.name)}</span><span class="al-meta"> ${entry.folder.files.length}</span></div>
                    <div class="al-children">${this._renderNode(entry.folder, childPrefix)}</div>
                </div>`;
            } else {
                html += this._renderFile(entry.file, prefix + branch);
            }
        });
        return html;
    }

    _renderFile(a, conn) {
        const size = this._formatSize(a.size);
        const sizeEl = size ? `<span class="al-size">${size}</span>` : '';
        const name = `<span class="al-file-name">${this._esc(a.name)}</span>`;
        const connEl = `<span class="al-conn">${conn}</span>`;

        if (a.kind === 'video') {
            return `<span class="al-line al-video-toggle">${connEl}${name}${sizeEl}</span>
                <div class="al-video-inline" hidden><video controls preload="none" src="${a.url}"></video></div>`;
        }
        const download = a.kind === 'model' || a.kind === 'csv' ? ' download' : '';
        const target = download ? '' : ' target="_blank" rel="noopener"';
        return `<a class="al-line" href="${a.url}"${download}${target}>${connEl}${name}${sizeEl}</a>`;
    }

    render() {
        const content = this._shadow.getElementById('content');
        if (!content) return;
        const actions = this._shadow.querySelector('.al-actions');
        const a = this._artifacts;
        if (!a || !a.length) {
            content.innerHTML = '<div class="al-body"><p class="al-empty">No artifacts found</p></div>';
            if (actions) actions.innerHTML = '';
            return;
        }

        const tree = this._buildTree();
        content.innerHTML = `<div class="al-tree">${this._renderNode(tree, '')}</div>`;

        if (actions) {
            const keys = this._allFolderKeys(tree);
            actions.innerHTML = `
                <button class="al-btn" id="al-expand">Expand all</button>
                <button class="al-btn" id="al-collapse">Collapse all</button>`;
            actions.querySelector('#al-expand').onclick = () => { this._open = new Set(keys); this.render(); };
            actions.querySelector('#al-collapse').onclick = () => { this._open.clear(); this.render(); };
        }
    }
}

customElements.define('artifact-list', ArtifactList);

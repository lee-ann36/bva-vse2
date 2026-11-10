/*
 * Reacties voor het wedstrijdarchief en de plays-pagina.
 *
 * - Plaatsen: de server geeft een geheime bewerk-sleutel terug, die we in localStorage bewaren.
 * - Bewerken/verwijderen: alleen zichtbaar voor reacties waarvan deze browser de sleutel heeft
 *   (of voor ingelogde moderators). De server controleert de sleutel ook zelf.
 * - Alle reactietekst wordt als tekst in de pagina gezet, nooit als HTML.
 *
 * Verwacht per kaart: .match-content-card met id "<iets>-<index>" en een iframe
 * "youtube-player-<index>"; per reactie: .comment-item[data-id] met .comment-text en .comment-actions.
 */
(function () {
    const TOKEN_KEY = 'bva_reactie_tokens';
    const TIME_REGEX = /\b(\d{1,2}:\d{2}(?::\d{2})?)\b/g;

    // ---------- Sleutels in de browser ----------
    function getTokens() {
        try { return JSON.parse(localStorage.getItem(TOKEN_KEY)) || {}; } catch (e) { return {}; }
    }
    function setToken(id, token) {
        try {
            const tokens = getTokens();
            tokens[id] = token;
            localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
        } catch (e) { /* localStorage niet beschikbaar: reactie is dan niet meer te bewerken */ }
    }
    function removeToken(id) {
        try {
            const tokens = getTokens();
            delete tokens[id];
            localStorage.setItem(TOKEN_KEY, JSON.stringify(tokens));
        } catch (e) { /* negeren */ }
    }

    function isModerator() {
        return document.body.dataset.moderator === '1';
    }

    // ---------- API ----------
    function csrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    async function post(url, body) {
        const response = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
            body: JSON.stringify(body),
        });
        let data = {};
        try { data = await response.json(); } catch (e) { /* geen JSON */ }
        if (!response.ok || data.status !== 'success') {
            throw new Error(data.message || 'Er ging iets mis (' + response.status + ').');
        }
        return data;
    }

    // ---------- Zichtbaarheid bewerk/verwijder-menu ----------
    function updateActions(root) {
        const tokens = getTokens();
        const moderator = isModerator();
        (root || document).querySelectorAll('.comment-item').forEach(item => {
            const actions = item.querySelector('.comment-actions');
            if (!actions) return;
            const magBeheren = moderator || Boolean(tokens[item.dataset.id]);
            actions.classList.toggle('d-none', !magBeheren);
        });
    }

    // ---------- Tijdstippen klikbaar maken (veilig, zonder innerHTML) ----------
    function parseTimeToSeconds(timeStr) {
        const parts = timeStr.split(':').map(Number);
        if (parts.length === 2) return parts[0] * 60 + parts[1];
        if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
        return 0;
    }

    function renderCommentText(p, text) {
        p.textContent = '';
        const card = p.closest('.match-content-card');
        const index = card ? card.id.split('-').pop() : null;

        let last = 0;
        text.replace(TIME_REGEX, (match, _g, offset) => {
            p.appendChild(document.createTextNode(text.slice(last, offset)));
            const a = document.createElement('a');
            a.href = '#';
            a.className = 'badge text-decoration-none border px-2 py-1 mx-1 align-middle';
            a.style.cssText = 'background-color: #58A6C2 !important; color: white !important;';
            const icon = document.createElement('i');
            icon.className = 'bi bi-play-fill me-1';
            a.appendChild(icon);
            a.appendChild(document.createTextNode(match));
            const seconds = parseTimeToSeconds(match);
            a.addEventListener('click', e => { e.preventDefault(); if (index !== null) window.seekVideo(index, seconds); });
            p.appendChild(a);
            last = offset + match.length;
            return match;
        });
        p.appendChild(document.createTextNode(text.slice(last)));
    }

    function convertTimestampsInComments() {
        document.querySelectorAll('.comment-item').forEach(item => {
            const p = item.querySelector('.comment-text');
            if (!p || p.dataset.parsed) return;
            renderCommentText(p, item.dataset.tekst !== undefined ? item.dataset.tekst : p.textContent);
            p.dataset.parsed = 'true';
        });
    }

    // ---------- Video doorspoelen ----------
    window.seekVideo = function (index, totalSeconds) {
        const iframe = document.getElementById('youtube-player-' + index);
        if (!iframe) return;
        const url = new URL(iframe.src);
        url.searchParams.set('start', String(totalSeconds));
        url.searchParams.set('autoplay', '1');
        iframe.src = url.toString();
    };

    // ---------- Formulier ----------
    window.openAddCommentModal = function (containerId) {
        const footer = document.getElementById(containerId).closest('.card-footer');
        footer.querySelector('.add-comment-form').classList.toggle('d-none');
    };

    window.cancelComment = function (btn) {
        const form = btn.closest('.add-comment-form');
        form.classList.add('d-none');
        form.querySelector('.author-input').value = '';
        form.querySelector('.text-input').value = '';
    };

    window.saveCommentToDatabase = async function (btn, pageId, blockId) {
        const form = btn.closest('.add-comment-form');
        const authorInput = form.querySelector('.author-input');
        const textInput = form.querySelector('.text-input');
        const author = authorInput.value.trim();
        const text = textInput.value.trim();
        if (!author) { authorInput.reportValidity(); return; }
        if (!text) { textInput.reportValidity(); return; }

        btn.disabled = true;
        try {
            const data = await post('/api/sla-reactie/', {
                page_id: pageId,
                block_id: blockId,
                auteur: author,
                rol: form.querySelector('.role-input').value,
                tekst: text,
            });
            setToken(data.id, data.token);
            location.reload();
        } catch (e) {
            alert('Fout bij opslaan: ' + e.message);
            btn.disabled = false;
        }
    };

    // ---------- Bewerken ----------
    window.editComment = function (btn) {
        const item = btn.closest('.comment-item');
        if (item.querySelector('.edit-container')) return;
        const p = item.querySelector('.comment-text');
        const huidig = item.dataset.tekst !== undefined ? item.dataset.tekst : p.textContent;

        const container = document.createElement('div');
        container.className = 'edit-container mt-2';
        const textarea = document.createElement('textarea');
        textarea.className = 'form-control form-control-sm edit-textarea mb-2';
        textarea.rows = 2;
        textarea.value = huidig;

        const opslaan = document.createElement('button');
        opslaan.type = 'button';
        opslaan.className = 'btn btn-sm btn-slam px-3 py-1';
        opslaan.textContent = 'Opslaan';

        const annuleren = document.createElement('button');
        annuleren.type = 'button';
        annuleren.className = 'btn btn-sm btn-outline-secondary px-3 py-1 ms-1';
        annuleren.textContent = 'Annuleren';

        container.append(textarea, opslaan, annuleren);
        p.classList.add('d-none');
        p.after(container);
        textarea.focus();

        annuleren.addEventListener('click', () => { container.remove(); p.classList.remove('d-none'); });
        opslaan.addEventListener('click', async () => {
            const nieuw = textarea.value.trim();
            if (!nieuw) { alert('De reactie mag niet leeg zijn.'); return; }
            opslaan.disabled = true;
            try {
                const data = await post('/api/bewerk-reactie/', {
                    id: item.dataset.id,
                    token: getTokens()[item.dataset.id] || '',
                    tekst: nieuw,
                });
                item.dataset.tekst = data.tekst;
                renderCommentText(p, data.tekst);
                const label = item.querySelector('.comment-edited');
                if (label) label.classList.remove('d-none');
                container.remove();
                p.classList.remove('d-none');
            } catch (e) {
                alert('Fout bij bewerken: ' + e.message);
                opslaan.disabled = false;
            }
        });
    };

    // ---------- Verwijderen ----------
    window.deleteComment = async function (btn) {
        if (!confirm('Weet je zeker dat je deze reactie wilt verwijderen?')) return;
        const item = btn.closest('.comment-item');
        try {
            await post('/api/verwijder-reactie/', {
                id: item.dataset.id,
                token: getTokens()[item.dataset.id] || '',
            });
            removeToken(item.dataset.id);
            item.remove();
        } catch (e) {
            alert('Fout bij verwijderen: ' + e.message);
        }
    };

    window.convertTimestampsInComments = convertTimestampsInComments;

    document.addEventListener('DOMContentLoaded', () => {
        updateActions();
        convertTimestampsInComments();
    });
})();

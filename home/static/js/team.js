/* Teampagina: speelsters, staf en teamfoto beheren op de site zelf. */
(function () {
    function csrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    function json(id) {
        const el = document.getElementById(id);
        try { return el ? JSON.parse(el.textContent) || {} : {}; } catch (e) { return {}; }
    }

    async function verstuur(url, body, isForm) {
        const response = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: isForm ? { 'X-CSRFToken': csrfToken() }
                            : { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
            body: isForm ? body : JSON.stringify(body),
        });
        let res = {};
        try { res = await response.json(); } catch (e) { /* geen JSON */ }
        if (!response.ok || res.status !== 'success') {
            throw new Error(res.message || 'Er ging iets mis (' + response.status + ').');
        }
        return res;
    }

    function toonModal(id) {
        window.bootstrap.Modal.getOrCreateInstance(document.getElementById(id)).show();
    }

    function fout(form, tekst) {
        const el = form.querySelector('.team-fout');
        el.textContent = tekst || '';
        el.classList.toggle('d-none', !tekst);
    }

    function fotoVoorbeeld(form, url) {
        const blok = form.querySelector('.foto-huidig');
        if (!blok) return;
        blok.classList.toggle('d-none', !url);
        const img = blok.querySelector('img');
        if (img) img.src = url || '';
    }

    // Formulier versturen (multipart vanwege foto's)
    window.teamOpslaan = async function (form) {
        fout(form, '');
        if (!form.reportValidity()) return;
        const knop = form.querySelector('[type="submit"]');
        knop.disabled = true;
        try {
            await verstuur(form.dataset.endpoint, new FormData(form), true);
            window.location.reload();
        } catch (e) {
            fout(form, e.message);
            knop.disabled = false;
        }
    };

    // ---- Speelsters ----
    window.openSpeler = function (id) {
        const form = document.querySelector('#spelerModal form');
        form.reset();
        fout(form, '');
        const s = id ? json('speler-data')[id] : null;
        form.elements.id.value = s ? id : '';
        form.querySelector('.form-titel').textContent = s ? 'SPEELSTER BEWERKEN' : 'NIEUWE SPEELSTER';
        form.querySelector('[type="submit"]').textContent = s ? 'Opslaan' : 'Toevoegen';
        form.elements.actief.checked = s ? s.actief : true;
        if (s) {
            form.elements.naam.value = s.naam;
            form.elements.rugnummer.value = s.rugnummer;
            form.elements.positie.value = s.positie;
        }
        const pinHint = form.querySelector('.pin-hint');
        pinHint.textContent = !s ? 'Verplicht voor een nieuwe speelster.'
            : (s.heeft_pincode ? 'Leeg laten = huidige pincode blijft.' : '⚠️ Deze speelster heeft nog geen pincode.');
        form.elements.pincode.required = !s;
        fotoVoorbeeld(form, s ? s.foto_url : '');
        toonModal('spelerModal');
    };

    window.genereerPin = function (knop) {
        const veld = knop.closest('.input-group').querySelector('input');
        const getal = new Uint32Array(1);
        window.crypto.getRandomValues(getal);
        veld.value = String(getal[0] % 10000).padStart(4, '0');
        veld.type = 'text';
    };

    // ---- Staf ----
    window.openStaf = function (blockId) {
        const form = document.querySelector('#stafModal form');
        form.reset();
        fout(form, '');
        const s = blockId ? json('staf-data')[blockId] : null;
        form.elements.block_id.value = s ? blockId : '';
        form.querySelector('.form-titel').textContent = s ? 'STAFLID BEWERKEN' : 'NIEUW STAFLID';
        form.querySelector('[type="submit"]').textContent = s ? 'Opslaan' : 'Toevoegen';
        if (s) {
            form.elements.naam.value = s.naam;
            form.elements.rol.value = s.rol;
        }
        fotoVoorbeeld(form, s ? s.foto_url : '');
        toonModal('stafModal');
    };

    window.stafVerwijderen = async function (blockId, naam, pageId) {
        if (!confirm(naam + ' uit de staf verwijderen?')) return;
        try {
            await verstuur('/api/team/staf-verwijderen/', { page_id: pageId, block_id: blockId }, false);
            window.location.reload();
        } catch (e) {
            alert(e.message);
        }
    };

    // ---- Teamfoto en tekst ----
    window.openTeamInfo = function () {
        const form = document.querySelector('#teamInfoModal form');
        fout(form, '');
        toonModal('teamInfoModal');
    };
})();

/* Homepage: inloggen voor coaches/trainers en mededelingen plaatsen, bewerken en verwijderen. */
(function () {
    function csrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    async function postJson(url, body) {
        const response = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
            body: JSON.stringify(body),
        });
        let res = {};
        try { res = await response.json(); } catch (e) { /* geen JSON */ }
        if (!response.ok || res.status !== 'success') {
            throw new Error(res.message || 'Er ging iets mis (' + response.status + ').');
        }
        return res;
    }

    function data() {
        const el = document.getElementById('mededelingen-data');
        try { return el ? JSON.parse(el.textContent) || {} : {}; } catch (e) { return {}; }
    }

    function toonFout(form, tekst) {
        const fout = form.querySelector('.dialoog-fout');
        fout.textContent = tekst;
        fout.hidden = !tekst;
    }

    window.openDialoog = function (id) {
        const d = document.getElementById(id);
        if (!d) return;
        const form = d.querySelector('form');
        if (form) toonFout(form, '');
        d.showModal();
        const veld = d.querySelector('input:not([type=hidden]), textarea');
        if (veld) veld.focus();
    };

    window.sluitDialoog = function (knop) {
        knop.closest('dialog').close();
    };

    // ---- Inloggen / uitloggen ----
    window.homeInloggen = async function (form) {
        const knop = form.querySelector('[type="submit"]');
        toonFout(form, '');
        knop.disabled = true;
        try {
            await postJson('/api/coach-inloggen/', {
                page_id: form.dataset.pageId,
                gebruikersnaam: form.elements.gebruikersnaam.value.trim(),
                wachtwoord: form.elements.wachtwoord.value,
            });
            window.location.reload();
        } catch (e) {
            toonFout(form, e.message);
            form.elements.wachtwoord.value = '';
            knop.disabled = false;
        }
    };

    window.homeUitloggen = async function () {
        try { await postJson('/api/coach-uitloggen/', {}); } catch (e) { /* toch herladen */ }
        window.location.reload();
    };

    // ---- Mededelingen ----
    window.openMededeling = function (id) {
        const d = document.getElementById('mededelingDialoog');
        const form = d.querySelector('form');
        form.reset();
        const m = id ? data()[id] : null;
        form.dataset.id = m ? id : '';
        d.querySelector('.dialoog-titel').textContent = m ? 'Mededeling bewerken' : 'Nieuwe mededeling';
        form.querySelector('[type="submit"]').textContent = m ? 'Opslaan' : 'Plaatsen';
        if (m) {
            form.elements.titel.value = m.titel;
            form.elements.tekst.value = m.tekst;
            form.elements.belangrijk.checked = m.belangrijk;
            form.elements.zichtbaar_vanaf.value = m.zichtbaar_vanaf || '';
            form.elements.zichtbaar_tot.value = m.zichtbaar_tot || '';
        }
        window.openDialoog('mededelingDialoog');
    };

    window.mededelingOpslaan = async function (form) {
        const knop = form.querySelector('[type="submit"]');
        toonFout(form, '');
        knop.disabled = true;
        try {
            await postJson('/api/mededeling-opslaan/', {
                id: form.dataset.id || null,
                titel: form.elements.titel.value.trim(),
                tekst: form.elements.tekst.value.trim(),
                belangrijk: form.elements.belangrijk.checked,
                zichtbaar_vanaf: form.elements.zichtbaar_vanaf.value,
                zichtbaar_tot: form.elements.zichtbaar_tot.value,
            });
            window.location.reload();
        } catch (e) {
            toonFout(form, e.message);
            knop.disabled = false;
        }
    };

    window.mededelingVerwijderen = async function (id, titel) {
        if (!confirm('Mededeling "' + titel + '" verwijderen?')) return;
        try {
            await postJson('/api/mededeling-verwijderen/', { id: id });
            window.location.reload();
        } catch (e) {
            alert(e.message);
        }
    };
})();

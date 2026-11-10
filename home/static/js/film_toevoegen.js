/* Formulier toevoegen/bewerken voor coaches en trainers (zie includes/coach_balk.html). */
(function () {
    function csrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    window.filmToevoegen = async function (form) {
        const fout = form.querySelector('.film-fout');
        const knop = form.querySelector('[type="submit"]');
        fout.classList.add('d-none');
        if (!form.reportValidity()) return;

        const data = { page_id: form.dataset.pageId };
        if (form.dataset.itemId) data[form.dataset.idVeld || 'block_id'] = form.dataset.itemId;
        form.querySelectorAll('[name]').forEach(el => {
            if (el.name === 'spelers' || el.name === 'voor_wie') return;
            data[el.name] = el.type === 'checkbox' ? el.checked : el.value.trim();
        });
        const bepaald = form.querySelector('[name="voor_wie"]:checked');
        if (bepaald) {
            data.spelers = bepaald.value === 'bepaald'
                ? Array.from(form.querySelectorAll('[name="spelers"]:checked')).map(el => el.value)
                : [];
            if (bepaald.value === 'bepaald' && data.spelers.length === 0) {
                fout.textContent = 'Kies minstens één speelster, of kies "Iedereen".';
                fout.classList.remove('d-none');
                return;
            }
        }

        knop.disabled = true;
        knop.textContent = 'Bezig...';
        try {
            const response = await fetch(form.dataset.endpoint || '/api/film-toevoegen/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
                body: JSON.stringify(data),
            });
            let res = {};
            try { res = await response.json(); } catch (e) { /* geen JSON */ }
            if (!response.ok || res.status !== 'success') {
                throw new Error(res.message || 'Er ging iets mis (' + response.status + ').');
            }
            // Herlaad en open direct de nieuwe wedstrijd/play
            const url = new URL(window.location.href);
            url.searchParams.delete('toevoegen');
            url.searchParams.set(form.dataset.param, res.index);
            if (res.week) url.searchParams.set('week', res.week);
            window.location.href = url.toString();
        } catch (e) {
            fout.textContent = e.message;
            fout.classList.remove('d-none');
            fout.scrollIntoView({ block: 'nearest' });
            knop.disabled = false;
            knop.textContent = form.dataset.itemId ? 'Opslaan' : 'Toevoegen';
        }
    };

    function beheerData() {
        const el = document.getElementById('beheer-data');
        try { return el ? JSON.parse(el.textContent) || {} : {}; } catch (e) { return {}; }
    }

    // Open het formulier leeg (nieuw) of ingevuld met een bestaande wedstrijd/play/opdracht (bewerken)
    window.openFormulier = function (itemId) {
        const modalEl = document.getElementById('filmToevoegenModal');
        if (!modalEl) return;
        const form = modalEl.querySelector('form');
        const titel = form.querySelector('.form-titel');
        const knop = form.querySelector('.form-opslaan');
        if (!titel.dataset.nieuw) titel.dataset.nieuw = titel.textContent;

        form.reset();
        form.querySelector('.film-fout').classList.add('d-none');
        const waarden = itemId ? beheerData()[itemId] : null;
        form.dataset.itemId = waarden ? itemId : '';
        titel.textContent = waarden ? titel.dataset.bewerk : titel.dataset.nieuw;
        knop.textContent = waarden ? 'Opslaan' : 'Toevoegen';

        if (waarden) {
            form.querySelectorAll('[name]').forEach(el => {
                if (el.name === 'spelers') {
                    el.checked = (waarden.spelers || []).map(String).includes(el.value);
                } else if (el.name === 'voor_wie') {
                    el.checked = el.value === ((waarden.spelers || []).length ? 'bepaald' : 'iedereen');
                } else if (el.name in waarden) {
                    if (el.type === 'checkbox') el.checked = Boolean(waarden[el.name]);
                    else el.value = waarden[el.name] == null ? '' : waarden[el.name];
                }
            });
        }
        // Lijst met speelsters tonen/verbergen volgens de gekozen optie
        const lijst = document.getElementById('voor-spelers-lijst');
        const bepaald = form.querySelector('[name="voor_wie"][value="bepaald"]');
        if (lijst && bepaald) lijst.classList.toggle('d-none', !bepaald.checked);

        window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    };

    // Wedstrijd of play verwijderen (inclusief de reacties erbij)
    window.filmVerwijderen = async function (blockId, naam) {
        const form = document.querySelector('#filmToevoegenModal form');
        if (!form) return;
        if (!confirm('Weet je zeker dat je "' + naam + '" wilt verwijderen? Ook de reacties worden verwijderd.')) return;
        try {
            await postJson('/api/film-verwijderen/', { page_id: form.dataset.pageId, block_id: blockId });
            const url = new URL(window.location.href);
            url.searchParams.delete(form.dataset.param);
            window.location.href = url.toString();
        } catch (e) {
            alert(e.message);
        }
    };

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

    // Inloggen vanaf de pagina; daarna herladen en direct het toevoeg-formulier openen
    window.coachInloggen = async function (form) {
        const fout = form.querySelector('.login-fout');
        const knop = form.querySelector('[type="submit"]');
        fout.classList.add('d-none');
        if (!form.reportValidity()) return;

        knop.disabled = true;
        knop.textContent = 'Bezig...';
        try {
            await postJson('/api/coach-inloggen/', {
                page_id: form.dataset.pageId,
                gebruikersnaam: form.querySelector('[name="gebruikersnaam"]').value.trim(),
                wachtwoord: form.querySelector('[name="wachtwoord"]').value,
            });
            // Gewoon herladen; het formulier opent pas als de coach/trainer zelf op de knop drukt
            const url = new URL(window.location.href);
            url.searchParams.delete('toevoegen');
            window.location.href = url.toString();
        } catch (e) {
            fout.textContent = e.message;
            fout.classList.remove('d-none');
            form.querySelector('[name="wachtwoord"]').value = '';
            knop.disabled = false;
            knop.textContent = 'Inloggen';
        }
    };

    window.coachUitloggen = async function () {
        try { await postJson('/api/coach-uitloggen/', {}); } catch (e) { /* toch herladen */ }
        const url = new URL(window.location.href);
        url.searchParams.delete('toevoegen');
        window.location.href = url.toString();
    };

    document.addEventListener('DOMContentLoaded', () => {
        // Oude links met ?toevoegen=1 opruimen (het formulier opent niet meer vanzelf)
        const url = new URL(window.location.href);
        if (url.searchParams.has('toevoegen')) {
            url.searchParams.delete('toevoegen');
            window.history.replaceState(null, '', url.toString());
        }
        // Focus het eerste veld zodra een formulier opent
        ['filmToevoegenModal', 'coachLoginModal'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('shown.bs.modal', () => {
                const veld = el.querySelector('input');
                if (veld) veld.focus();
            });
        });
    });
})();

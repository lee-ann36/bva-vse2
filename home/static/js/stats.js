/*
 * Statistiekenpagina.
 *
 * Overzicht: filters, wedstrijd aanmaken/wijzigen/verwijderen.
 * Bijhouden: speelster + actie aantikken. Elke actie krijgt een eigen id en gaat in een wachtrij
 * (ook bewaard op de telefoon), zodat er niets verloren gaat als het internet in de sporthal
 * even wegvalt. Zodra er weer verbinding is, wordt de wachtrij alsnog verstuurd.
 */
(function () {
    function csrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    class ApiFout extends Error {
        constructor(message, status) { super(message); this.status = status; }
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
            throw new ApiFout(res.message || 'Er ging iets mis (' + response.status + ').', response.status);
        }
        return res;
    }

    function opslag(sleutel, waarde) {
        try {
            if (waarde === undefined) return JSON.parse(localStorage.getItem(sleutel) || 'null');
            localStorage.setItem(sleutel, JSON.stringify(waarde));
        } catch (e) { return null; }
        return null;
    }

    function nieuwId() {
        if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
        return 'id-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    }

    function esc(tekst) {
        const d = document.createElement('div');
        d.textContent = tekst == null ? '' : String(tekst);
        return d.innerHTML;
    }

    // -----------------------------------------------------------------------
    // Overzicht
    // -----------------------------------------------------------------------
    function paginaId() {
        const el = document.querySelector('[data-stats-page]');
        return el ? el.dataset.statsPage : null;
    }

    const filters = document.querySelector('[data-filters]');
    if (filters) {
        filters.addEventListener('change', () => {
            const params = new URLSearchParams();
            filters.querySelectorAll('select[name]').forEach(el => {
                if (el.value && !el.disabled) params.set(el.name, el.value);
            });
            const qs = params.toString();
            window.location.href = window.location.pathname + (qs ? '?' + qs : '');
        });
    }

    function wedstrijdData() {
        const el = document.getElementById('wedstrijd-data');
        return el ? JSON.parse(el.textContent) : {};
    }

    window.openWedstrijdFormulier = function (id) {
        const modalEl = document.getElementById('wedstrijdModal');
        if (!modalEl) return;
        const form = modalEl.querySelector('form');
        form.querySelector('.wedstrijd-fout').classList.add('d-none');
        const suggesties = form.querySelector('.suggesties');
        const w = id ? wedstrijdData()[id] : null;
        form.dataset.id = w ? id : '';
        form.querySelector('.form-titel').textContent = w ? 'WEDSTRIJD WIJZIGEN' : 'NIEUWE WEDSTRIJD';
        form.querySelector('.form-opslaan').textContent = w ? 'Opslaan' : 'Opslaan en bijhouden';
        if (suggesties) suggesties.classList.toggle('d-none', !!w);
        if (w) {
            form.tegenstander.value = w.tegenstander;
            form.datum.value = w.datum;
            form.thuis.value = w.thuis ? '1' : '0';
            form.film.value = w.film || '';
        } else {
            form.reset();
            form.datum.value = new Date().toLocaleDateString('sv-SE');  // JJJJ-MM-DD in eigen tijdzone
        }
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
    };

    window.kiesSuggestie = function (btn) {
        const form = btn.closest('form');
        form.tegenstander.value = btn.dataset.tegenstander;
        form.datum.value = btn.dataset.datum;
        form.thuis.value = btn.dataset.thuis;
        form.film.value = btn.dataset.film || '';
        if (!btn.dataset.datum) form.datum.focus();  // datum uit de film niet leesbaar: zelf invullen
        form.querySelectorAll('.suggesties .btn').forEach(b => b.classList.toggle('active', b === btn));
    };

    window.slaWedstrijdOp = async function (form) {
        const fout = form.querySelector('.wedstrijd-fout');
        const knop = form.querySelector('[type="submit"]');
        fout.classList.add('d-none');
        if (!form.reportValidity()) return;
        knop.disabled = true;
        try {
            const res = await postJson('/api/stats/wedstrijd-opslaan/', {
                page_id: paginaId(),
                id: form.dataset.id || null,
                tegenstander: form.tegenstander.value.trim(),
                datum: form.datum.value,
                thuis: form.thuis.value === '1',
                film_block_id: form.film.value,
            });
            window.location.href = window.location.pathname + (form.dataset.id ? window.location.search : '?bijhouden=' + res.id);
        } catch (e) {
            fout.textContent = e.message;
            fout.classList.remove('d-none');
            knop.disabled = false;
        }
    };

    // Vanaf de homepage: ?nieuw=1 opent meteen het formulier, ?inloggen=1 het inlogscherm
    document.addEventListener('DOMContentLoaded', () => {
        const url = new URL(window.location.href);
        const open = (param, actie) => {
            if (!url.searchParams.has(param)) return;
            url.searchParams.delete(param);
            window.history.replaceState(null, '', url.toString());
            actie();
        };
        if (url.searchParams.has('nieuw') && !document.getElementById('wedstrijdModal')) {
            // Nog niet ingelogd: eerst inloggen; ?nieuw=1 blijft staan, dus na het inloggen opent het formulier alsnog
            const el = document.getElementById('coachLoginModal');
            if (el) bootstrap.Modal.getOrCreateInstance(el).show();
            return;
        }
        open('nieuw', () => window.openWedstrijdFormulier(null));
        open('inloggen', () => {
            const el = document.getElementById('coachLoginModal');
            if (el) bootstrap.Modal.getOrCreateInstance(el).show();
        });
    });

    window.verwijderWedstrijd = async function (btn) {
        if (!confirm('Wedstrijd tegen ' + btn.dataset.naam + ' verwijderen?\n\nAlle statistieken van deze wedstrijd gaan dan ook weg.')) return;
        try {
            await postJson('/api/stats/wedstrijd-verwijderen/', { page_id: paginaId(), id: btn.dataset.id });
            window.location.href = window.location.pathname;
        } catch (e) {
            alert(e.message);
        }
    };

    // -----------------------------------------------------------------------
    // Bijhouden
    // -----------------------------------------------------------------------
    const live = document.querySelector('[data-stats-live]');
    if (!live) return;

    const data = JSON.parse(document.getElementById('stats-live-data').textContent);
    const TEGEN = { t1: 1, t2: 2, t3: 3 };
    const PUNTEN = { '2r': 2, '3r': 3, fr: 1 };
    const KORT = {
        '2r': '2 punten ✓', '2m': '2 punten ✗', '3r': '3 punten ✓', '3m': '3 punten ✗',
        fr: 'Vrije worp ✓', fm: 'Vrije worp ✗', or: 'Rebound aanval', dr: 'Rebound verdediging',
        as: 'Assist', st: 'Steal', bl: 'Block', to: 'Balverlies', pf: 'Fout',
        t1: '+1', t2: '+2', t3: '+3',
    };
    const KWART_NAAM = { 1: 'Q1', 2: 'Q2', 3: 'Q3', 4: 'Q4', 5: 'V' };
    const SLEUTEL_RIJ = 'stats-wachtrij-' + data.wedstrijd_id;
    const SLEUTEL_KWART = 'stats-kwart-' + data.wedstrijd_id;
    const spelerNaam = Object.fromEntries(data.spelers.map(s => [s.id, s.naam]));

    let acties = data.acties.map(a => ({ ...a, wacht: false }));
    let wachtrij = opslag(SLEUTEL_RIJ) || [];
    let bezig = false;
    let fout = '';
    let gekozen = null;
    let herprobeer = null;

    // Wat nog niet verstuurd was (bijv. telefoon was offline en pagina is herladen) er weer bij zetten
    const bekend = new Set(acties.map(a => a.cid));
    wachtrij.forEach(op => {
        if (op.op === 'add' && !bekend.has(op.cid)) acties.push({ cid: op.cid, s: op.s, k: op.k, t: op.t, wacht: true });
        if (op.op === 'del') acties = acties.filter(a => a.cid !== op.cid);
    });

    let kwart = Number(opslag(SLEUTEL_KWART)) || Math.max(1, ...acties.map(a => a.k));

    function bewaarRij() { opslag(SLEUTEL_RIJ, wachtrij); }

    async function verwerk() {
        if (bezig) return;
        bezig = true;
        clearTimeout(herprobeer);
        while (wachtrij.length) {
            const op = wachtrij[0];
            try {
                if (op.op === 'add') {
                    const res = await postJson('/api/stats/actie/', {
                        page_id: data.page_id, wedstrijd_id: data.wedstrijd_id,
                        client_id: op.cid, speler_id: op.s, kwart: op.k, soort: op.t,
                    });
                    const a = acties.find(x => x.cid === op.cid);
                    if (a) { a.wacht = false; a.id = res.id; }
                } else {
                    await postJson('/api/stats/actie-verwijderen/', {
                        page_id: data.page_id, wedstrijd_id: data.wedstrijd_id, client_id: op.cid,
                    });
                }
                fout = '';
                wachtrij.shift();
                bewaarRij();
            } catch (e) {
                if (e instanceof ApiFout && e.status === 403) {
                    fout = 'Je bent uitgelogd. Log opnieuw in op de statistiekenpagina; je acties blijven op deze telefoon bewaard.';
                    break;
                }
                if (e instanceof ApiFout && e.status >= 400 && e.status < 500) {
                    // Ongeldige actie: overslaan, anders blijft de rest hangen
                    fout = e.message;
                    if (op.op === 'add') acties = acties.filter(a => a.cid !== op.cid);
                    wachtrij.shift();
                    bewaarRij();
                    continue;
                }
                // Geen internet of serverfout: later opnieuw proberen
                herprobeer = setTimeout(verwerk, 4000);
                break;
            } finally {
                render();
            }
        }
        bezig = false;
        render();
    }

    function voegToe(soort) {
        const voorTegen = soort in TEGEN;
        if (!voorTegen && !gekozen) {
            const grid = live.querySelector('[data-spelers]');
            grid.classList.add('flits');
            live.querySelector('[data-gekozen-naam]').textContent = '← kies eerst een speelster';
            grid.scrollIntoView({ behavior: 'smooth', block: 'center' });
            setTimeout(() => grid.classList.remove('flits'), 600);
            return;
        }
        const a = { cid: nieuwId(), s: voorTegen ? null : gekozen, k: kwart, t: soort, wacht: true };
        acties.push(a);
        wachtrij.push({ op: 'add', cid: a.cid, s: a.s, k: a.k, t: a.t });
        bewaarRij();
        if (navigator.vibrate) navigator.vibrate(15);
        const knop = live.querySelector('[data-soort="' + soort + '"]');
        if (knop) { knop.classList.add('flits'); setTimeout(() => knop.classList.remove('flits'), 250); }
        render();
        verwerk();
    }

    function verwijder(cid) {
        acties = acties.filter(a => a.cid !== cid);
        const i = wachtrij.findIndex(op => op.op === 'add' && op.cid === cid);
        if (i > 0 || (i === 0 && !bezig)) {
            wachtrij.splice(i, 1);  // nog niet verstuurd: gewoon uit de wachtrij halen
        } else {
            wachtrij.push({ op: 'del', cid: cid });
        }
        bewaarRij();
        render();
        verwerk();
    }

    function tel(lijst) {
        const n = {};
        lijst.forEach(a => { n[a.t] = (n[a.t] || 0) + 1; });
        const g = k => n[k] || 0;
        return {
            pts: 2 * g('2r') + 3 * g('3r') + g('fr'),
            tegen: g('t1') + 2 * g('t2') + 3 * g('t3'),
            fg: (g('2r') + g('3r')) + '/' + (g('2r') + g('3r') + g('2m') + g('3m')),
            drie: g('3r') + '/' + (g('3r') + g('3m')),
            vw: g('fr') + '/' + (g('fr') + g('fm')),
            reb: g('or') + g('dr'), as: g('as'), st: g('st'), bl: g('bl'), to: g('to'), pf: g('pf'),
        };
    }

    function render() {
        const totaal = tel(acties);
        live.querySelector('[data-score-wij]').textContent = totaal.pts;
        live.querySelector('[data-score-zij]').textContent = totaal.tegen;

        live.querySelectorAll('[data-kwart]').forEach(b => b.classList.toggle('actief', Number(b.dataset.kwart) === kwart));

        // Spelers
        const perSpeler = {};
        acties.forEach(a => { if (a.s) (perSpeler[a.s] = perSpeler[a.s] || []).push(a); });
        live.querySelector('[data-spelers]').innerHTML = data.spelers.map(s => {
            const t = tel(perSpeler[s.id] || []);
            return '<button type="button" class="btn-speler' + (gekozen === s.id ? ' gekozen' : '') + '" data-speler="' + s.id + '">' +
                (s.nr != null ? '<span class="nr">#' + esc(s.nr) + '</span>' : '<span class="nr">&nbsp;</span>') +
                '<span class="nm">' + esc(s.naam) + '</span>' +
                '<span class="info">' + t.pts + ' pt · <span class="' + (t.pf >= 4 ? 'fouten-veel' : '') + '">' + t.pf + ' F</span></span>' +
                '</button>';
        }).join('');
        live.querySelector('[data-gekozen-naam]').textContent = gekozen ? '· ' + (spelerNaam[gekozen] || '') : '';

        // Laatste acties (nieuwste bovenaan)
        const laatste = acties.slice(-15).reverse();
        live.querySelector('[data-log]').innerHTML = laatste.length ? laatste.map(a =>
            '<li class="list-group-item">' +
            '<span class="kw">' + KWART_NAAM[a.k] + '</span>' +
            '<span class="flex-fill">' + (a.s ? '<strong>' + esc(spelerNaam[a.s] || '?') + '</strong> · ' : '<strong>' + esc(data.tegenstander) + '</strong> · ') + esc(KORT[a.t] || a.t) + '</span>' +
            (a.wacht ? '<i class="bi bi-cloud-arrow-up wacht" title="Wordt nog verstuurd"></i>' : '') +
            '<button type="button" class="btn btn-sm btn-link text-danger p-0" data-weg="' + esc(a.cid) + '" aria-label="Verwijderen"><i class="bi bi-x-circle"></i></button>' +
            '</li>').join('') : '<li class="list-group-item text-muted">Nog niets genoteerd. Kies een speelster en tik op een actie.</li>';
        live.querySelector('[data-ongedaan]').disabled = !acties.length;

        // Tussenstand
        live.querySelector('[data-tussenstand]').innerHTML = data.spelers.filter(s => perSpeler[s.id]).map(s => {
            const t = tel(perSpeler[s.id]);
            return '<tr><td class="naam">' + esc(s.naam) + '</td><td class="fw-bold">' + t.pts + '</td><td>' + t.fg + '</td><td>' + t.drie +
                '</td><td>' + t.vw + '</td><td>' + t.reb + '</td><td>' + t.as + '</td><td>' + t.st + '</td><td>' + t.bl +
                '</td><td>' + t.to + '</td><td' + (t.pf >= 4 ? ' class="text-danger fw-bold"' : '') + '>' + t.pf + '</td></tr>';
        }).join('') || '<tr><td colspan="11" class="text-muted text-start">Nog geen acties.</td></tr>';

        // Status
        const sync = live.querySelector('[data-sync]');
        const open = wachtrij.length;
        if (fout) {
            sync.innerHTML = '<span class="text-warning"><i class="bi bi-exclamation-triangle me-1"></i>' + esc(fout) + '</span>';
        } else if (open) {
            sync.innerHTML = '<span class="text-warning"><i class="bi bi-cloud-arrow-up me-1"></i>' + open + ' actie' + (open === 1 ? '' : 's') +
                ' nog niet opgeslagen' + (navigator.onLine === false ? ' (geen internet, wordt later verstuurd)' : '…') + '</span>';
        } else {
            sync.innerHTML = '<span class="opacity-75"><i class="bi bi-check2-circle me-1"></i>Alles opgeslagen</span>';
        }
    }

    live.addEventListener('click', e => {
        const speler = e.target.closest('[data-speler]');
        if (speler) {
            const id = Number(speler.dataset.speler);
            gekozen = gekozen === id ? null : id;
            render();
            return;
        }
        const actie = e.target.closest('[data-soort]');
        if (actie) { voegToe(actie.dataset.soort); return; }
        const kw = e.target.closest('[data-kwart]');
        if (kw) {
            kwart = Number(kw.dataset.kwart);
            opslag(SLEUTEL_KWART, kwart);
            render();
            return;
        }
        const weg = e.target.closest('[data-weg]');
        if (weg) { verwijder(weg.dataset.weg); return; }
        if (e.target.closest('[data-ongedaan]') && acties.length) {
            const a = acties[acties.length - 1];
            verwijder(a.cid);
        }
    });

    const filmKnop = live.querySelector('[data-film-toggle]');
    if (filmKnop) {
        const video = live.querySelector('[data-film-video]');
        const zet = verborgen => {
            video.classList.toggle('d-none', verborgen);
            filmKnop.textContent = verborgen ? 'Toon video' : 'Verberg video';
            opslag('stats-video-verborgen', verborgen);
        };
        zet(!!opslag('stats-video-verborgen'));
        filmKnop.addEventListener('click', () => zet(!video.classList.contains('d-none')));
    }

    window.addEventListener('online', verwerk);
    let bevestigd = false;
    window.addEventListener('beforeunload', e => {
        if (wachtrij.length && !bevestigd) { e.preventDefault(); e.returnValue = ''; }
    });
    live.querySelector('[data-verlaat]').addEventListener('click', e => {
        if (wachtrij.length && !confirm('Er zijn nog ' + wachtrij.length + ' acties niet opgeslagen (geen internet?).\n\nZe blijven op deze telefoon bewaard en worden verstuurd als je deze wedstrijd weer opent. Toch weggaan?')) {
            e.preventDefault();
            return;
        }
        bevestigd = true;
    });

    render();
    verwerk();
})();

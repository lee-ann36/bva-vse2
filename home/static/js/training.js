/* Trainingspagina: speelster kiezen (pincode), afvinken en opdrachten verwijderen. */
(function () {
    function csrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }

    function paginaData() {
        const el = document.querySelector('[data-training-page]');
        return { pageId: el ? el.dataset.trainingPage : null, week: el ? el.dataset.week : null };
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

    window.kiesSpeler = async function (form) {
        const fout = form.querySelector('.speler-fout');
        const knop = form.querySelector('[type="submit"]');
        fout.classList.add('d-none');
        if (!form.reportValidity()) return;

        knop.disabled = true;
        try {
            await postJson('/api/training/speler-kiezen/', {
                speler_id: form.querySelector('[name="speler_id"]').value,
                pincode: form.querySelector('[name="pincode"]').value.trim(),
            });
            window.location.reload();
        } catch (e) {
            fout.textContent = e.message;
            fout.classList.remove('d-none');
            form.querySelector('[name="pincode"]').value = '';
            knop.disabled = false;
        }
    };

    window.wisselSpeler = async function () {
        try { await postJson('/api/training/speler-wisselen/', {}); } catch (e) { /* toch herladen */ }
        window.location.reload();
    };

    window.afvinken = async function (btn) {
        const { week } = paginaData();
        btn.disabled = true;
        try {
            await postJson('/api/training/afvinken/', {
                opdracht_id: btn.dataset.opdracht,
                week: week,
                gedaan: btn.dataset.gedaan !== '1',
            });
            window.location.reload();
        } catch (e) {
            alert(e.message);
            btn.disabled = false;
        }
    };

    window.verwijderOpdracht = async function (btn) {
        const { pageId, week } = paginaData();
        let alleenVanafDezeWeek = false;

        if (btn.dataset.herhalend === '1' && week > btn.dataset.start) {
            const keuze = prompt(
                'Dit is een herhalende opdracht.\n\n' +
                '1 = stoppen vanaf deze week (eerdere weken blijven bewaard)\n' +
                '2 = helemaal verwijderen (ook alle eerdere afvinkingen)\n\n' +
                'Typ 1 of 2:', '1');
            if (keuze === null) return;
            if (keuze.trim() === '1') alleenVanafDezeWeek = true;
            else if (keuze.trim() !== '2') return;
        } else if (!confirm('Weet je zeker dat je deze opdracht wilt verwijderen? Ook de afvinkingen worden verwijderd.')) {
            return;
        }

        try {
            await postJson('/api/training/opdracht-verwijderen/', {
                page_id: pageId, id: btn.dataset.id, week: week, alleen_vanaf_deze_week: alleenVanafDezeWeek,
            });
            window.location.reload();
        } catch (e) {
            alert(e.message);
        }
    };

    document.addEventListener('DOMContentLoaded', () => {
        const modal = document.getElementById('spelerKiezenModal');
        if (modal) modal.addEventListener('shown.bs.modal', () => modal.querySelector('select').focus());
    });
})();

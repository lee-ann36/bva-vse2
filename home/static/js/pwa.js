/*
 * "Als app op je telefoon":
 * - service worker aanmelden
 * - Android/Chrome/Edge: echte installeer-knop (beforeinstallprompt)
 * - iPhone/iPad: Apple staat geen installeer-knop toe, dus een stappenplan met dezelfde
 *   icoontjes als in Safari, een pijl naar de Delen-knop en een kleine balk onderaan.
 */
(function () {
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js').catch(() => { /* site werkt gewoon zonder */ });
        });
    }

    const ua = window.navigator.userAgent;
    const isIPad = /ipad/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
    const isIOS = /iphone|ipod/i.test(ua) || isIPad;
    const isGeinstalleerd = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    // Ingebouwde browsers (Instagram, Facebook, Snapchat, TikTok, ...) kunnen niet op het beginscherm zetten
    const isInApp = /FBAN|FBAV|Instagram|Snapchat|TikTok|musical_ly|Line\/|GSA\//i.test(ua);
    const isChromeIOS = /CriOS|EdgiOS|FxiOS/i.test(ua);

    const BALK_KEY = 'bva_ios_balk_weg_tot';
    let installPrompt = null;

    // ------------------------------------------------------------- icoontjes
    const ICOON_DELEN = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="M8 7l4-4 4 4"/><path d="M6 11H5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-1"/></svg>';
    const ICOON_PLUS = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="M12 8v8M8 12h8"/></svg>';
    const ICOON_PUNTJES = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>';

    // ------------------------------------------------------------- opmaak
    const CSS = `
    .bva-ios-balk{position:fixed;left:12px;right:12px;max-width:calc(100vw - 24px);box-sizing:border-box;bottom:calc(12px + env(safe-area-inset-bottom));z-index:2000;
      display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:14px;color:#fff;font:600 14px/1.3 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;
      background:linear-gradient(120deg,#58A6C2 0%,#2f6f8c 45%,#112233 100%);box-shadow:0 10px 30px rgba(17,34,51,.35)}
    .bva-ios-balk img{width:34px;height:34px;border-radius:8px;flex-shrink:0}
    .bva-ios-balk span{flex:1;min-width:0}
    .bva-ios-balk button{border:0;cursor:pointer;font:inherit}
    .bva-ios-balk .hoe{background:#fff;color:#112233;border-radius:999px;padding:7px 14px;font-weight:700;flex-shrink:0}
    .bva-ios-balk .weg{background:none;color:#fff;font-size:22px;line-height:1;padding:0 4px;opacity:.8}
    .bva-ios-scherm{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:2100;background:rgba(11,23,42,.6);display:flex;align-items:flex-end;justify-content:center;
      font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
    .bva-ios-scherm.ipad{align-items:flex-start}
    .bva-ios-kaart{box-sizing:border-box;background:#fff;color:#112233;width:min(420px,100vw);border-radius:20px 20px 0 0;padding:22px 20px calc(96px + env(safe-area-inset-bottom));
      box-shadow:0 -10px 40px rgba(0,0,0,.25);position:relative}
    .bva-ios-scherm.ipad .bva-ios-kaart,.bva-ios-scherm.boven .bva-ios-kaart{border-radius:0 0 20px 20px;padding:84px 20px 22px}
    .bva-ios-kaart h2{font-size:18px;margin:0 0 4px;display:flex;align-items:center;gap:10px}
    .bva-ios-kaart h2 img{width:36px;height:36px;border-radius:9px}
    .bva-ios-kaart p.sub{margin:0 0 16px;color:#6b7280;font-size:14px}
    .bva-ios-stap{display:flex;gap:12px;align-items:flex-start;margin-bottom:14px}
    .bva-ios-stap .nr{width:28px;height:28px;border-radius:50%;color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center;flex-shrink:0;
      background:linear-gradient(120deg,#58A6C2,#112233)}
    .bva-ios-stap .icoon{display:inline-flex;vertical-align:middle;color:#0a84ff;background:#f2f2f7;border-radius:8px;padding:3px;margin:0 2px}
    .bva-ios-sluit{position:absolute;top:12px;right:14px;border:0;background:#f2f2f7;color:#374151;width:32px;height:32px;border-radius:50%;font-size:20px;cursor:pointer}
    .bva-ios-scherm.ipad .bva-ios-sluit,.bva-ios-scherm.boven .bva-ios-sluit{top:auto;bottom:12px}
    .bva-ios-knop{display:block;width:100%;border:0;border-radius:999px;padding:12px;font-weight:700;font-size:15px;color:#fff;cursor:pointer;margin-top:6px;
      background:linear-gradient(120deg,#58A6C2 0%,#2f6f8c 45%,#112233 100%)}
    .bva-ios-pijl{position:fixed;left:50%;bottom:calc(14px + env(safe-area-inset-bottom));transform:translateX(-50%);z-index:2200;color:#58A6C2;
      animation:bvaPijl 1s ease-in-out infinite;filter:drop-shadow(0 2px 6px rgba(17,34,51,.35));pointer-events:none;line-height:0}
    .bva-ios-pijl.rechtsboven{left:auto;right:18px;bottom:auto;top:calc(10px + env(safe-area-inset-top));transform:none;animation-name:bvaPijlOp}
    @keyframes bvaPijl{0%,100%{transform:translate(-50%,0)}50%{transform:translate(-50%,10px)}}
    @keyframes bvaPijlOp{0%,100%{transform:translateY(0)}50%{transform:translateY(-10px)}}
    `;

    function voegCssToe() {
        if (document.getElementById('bva-pwa-css')) return;
        const style = document.createElement('style');
        style.id = 'bva-pwa-css';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    function logoUrl() {
        const link = document.querySelector('link[rel="apple-touch-icon"]');
        return link ? link.href : '';
    }

    // ------------------------------------------------------------- stappenplan
    function stappen() {
        if (isInApp) {
            return {
                sub: 'Je zit nu in de browser van een andere app. Open de site eerst in Safari.',
                html: `
                <div class="bva-ios-stap"><span class="nr">1</span><div>Tik rechtsboven of onderin op <span class="icoon">${ICOON_PUNTJES}</span> en kies <b>Open in Safari</b> (of "Open in browser").</div></div>
                <div class="bva-ios-stap"><span class="nr">2</span><div>Lukt dat niet? Kopieer de link hieronder en plak hem in <b>Safari</b>.</div></div>
                <button type="button" class="bva-ios-knop" data-kopieer>🔗 Kopieer link</button>`,
                pijl: null,
            };
        }
        const deelPlek = isChromeIOS ? 'rechtsboven in de adresbalk' : (isIPad ? 'rechtsboven' : 'onderin het scherm');
        return {
            sub: 'Dan opent BVA VSE-2 als app, met het logo tussen je andere apps.',
            html: `
            <div class="bva-ios-stap"><span class="nr">1</span><div>Tik op <span class="icoon">${ICOON_DELEN}</span> <b>Delen</b>, ${deelPlek}.</div></div>
            <div class="bva-ios-stap"><span class="nr">2</span><div>Scroll een stukje naar beneden en tik op <span class="icoon">${ICOON_PLUS}</span> <b>Zet op beginscherm</b>.</div></div>
            <div class="bva-ios-stap"><span class="nr">3</span><div>Tik rechtsboven op <b>Voeg toe</b>. Klaar! 🎉</div></div>`,
            pijl: (isChromeIOS || isIPad) ? 'rechtsboven' : 'onder',
        };
    }

    window.toonIosUitleg = function () {
        voegCssToe();
        sluitIosUitleg();
        const s = stappen();
        const scherm = document.createElement('div');
        scherm.className = 'bva-ios-scherm' + (s.pijl === 'rechtsboven' ? ' boven' : '') + (isIPad ? ' ipad' : '');
        scherm.setAttribute('role', 'dialog');
        scherm.setAttribute('aria-modal', 'true');
        scherm.setAttribute('aria-label', 'Zet BVA VSE-2 op je beginscherm');
        scherm.innerHTML = `
            <div class="bva-ios-kaart">
                <button type="button" class="bva-ios-sluit" aria-label="Sluiten">×</button>
                <h2><img src="${logoUrl()}" alt="">Zet BVA op je beginscherm</h2>
                <p class="sub">${s.sub}</p>
                ${s.html}
            </div>`;
        scherm.addEventListener('click', e => {
            if (e.target === scherm || e.target.closest('.bva-ios-sluit')) sluitIosUitleg();
        });
        const kopieer = scherm.querySelector('[data-kopieer]');
        if (kopieer) kopieer.addEventListener('click', async () => {
            const link = window.location.origin + '/';
            try { await navigator.clipboard.writeText(link); kopieer.textContent = '✓ Link gekopieerd, plak hem in Safari'; }
            catch (e) { window.prompt('Kopieer deze link:', link); }
        });
        document.body.appendChild(scherm);

        if (s.pijl) {
            const pijl = document.createElement('div');
            pijl.className = 'bva-ios-pijl' + (s.pijl === 'rechtsboven' ? ' rechtsboven' : '');
            pijl.innerHTML = '<svg viewBox="0 0 24 24" width="44" height="44" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                + (s.pijl === 'rechtsboven' ? '<path d="M12 20V5M5 11l7-7 7 7"/>' : '<path d="M12 4v15M5 13l7 7 7-7"/>') + '</svg>';
            document.body.appendChild(pijl);
        }
        const balk = document.querySelector('.bva-ios-balk');
        if (balk) balk.remove();
    };

    function sluitIosUitleg() {
        document.querySelectorAll('.bva-ios-scherm, .bva-ios-pijl').forEach(el => el.remove());
    }

    // ------------------------------------------------------------- balk onderaan
    function balkWeggeklikt() {
        try { return Number(localStorage.getItem(BALK_KEY) || 0) > Date.now(); } catch (e) { return false; }
    }

    function toonIosBalk() {
        if (balkWeggeklikt() || document.querySelector('.bva-ios-balk')) return;
        voegCssToe();
        const balk = document.createElement('div');
        balk.className = 'bva-ios-balk';
        balk.innerHTML = `<img src="${logoUrl()}" alt=""><span>📲 Zet BVA op je beginscherm</span>
            <button type="button" class="hoe">Hoe?</button><button type="button" class="weg" aria-label="Niet nu">×</button>`;
        balk.querySelector('.hoe').addEventListener('click', window.toonIosUitleg);
        balk.querySelector('.weg').addEventListener('click', () => {
            try { localStorage.setItem(BALK_KEY, String(Date.now() + 30 * 24 * 3600 * 1000)); } catch (e) { /* negeren */ }
            balk.remove();
        });
        document.body.appendChild(balk);
    }

    // ------------------------------------------------------------- blok op de homepage
    function toon(blok, wat) {
        if (!blok) return;
        blok.hidden = false;
        blok.querySelectorAll('[data-installeer-stap]').forEach(el => { el.hidden = el.dataset.installeerStap !== wat; });
    }

    document.addEventListener('DOMContentLoaded', () => {
        if (isGeinstalleerd) return;
        const blok = document.querySelector('[data-installeer]');

        if (isIOS) {
            toon(blok, 'ios');
            // Link om te delen in de teamapp: https://.../#zet-op-beginscherm opent meteen het stappenplan
            window.addEventListener('hashchange', () => {
                if (window.location.hash === '#zet-op-beginscherm') window.toonIosUitleg();
            });
            if (window.location.hash === '#zet-op-beginscherm') { window.toonIosUitleg(); return; }
            const iosKnop = blok && blok.querySelector('[data-ios-uitleg]');
            if (iosKnop) iosKnop.addEventListener('click', window.toonIosUitleg);
            // Even wachten, zodat de balk niet meteen bij het laden in beeld springt
            setTimeout(toonIosBalk, 2500);
            return;
        }

        // Android/Chrome/Edge: echte installeer-knop
        window.addEventListener('beforeinstallprompt', e => {
            e.preventDefault();
            installPrompt = e;
            toon(blok, 'knop');
        });
        const knop = blok && blok.querySelector('[data-installeer-knop]');
        if (knop) knop.addEventListener('click', async () => {
            if (!installPrompt) return;
            installPrompt.prompt();
            await installPrompt.userChoice;
            installPrompt = null;
            blok.hidden = true;
        });
        window.addEventListener('appinstalled', () => { if (blok) blok.hidden = true; });
    });
})();

/*
 * Pushmeldingen: knop "Meldingen aanzetten" in elk element met [data-meldingen].
 * Bij elk bezoek wordt het abonnement opnieuw doorgegeven, zodat de server weet
 * welke speelster (pincode-login) bij deze telefoon hoort.
 */
(function () {
    const kanPush = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
    const ua = window.navigator.userAgent;
    const isIOS = /iphone|ipod|ipad/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
    const isGeinstalleerd = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;

    function meta(naam) {
        const el = document.querySelector(`meta[name="${naam}"]`);
        return el ? el.content : '';
    }

    function sleutelBytes(b64) {
        const padding = '='.repeat((4 - (b64.length % 4)) % 4);
        const raw = atob((b64 + padding).replace(/-/g, '+').replace(/_/g, '/'));
        return Uint8Array.from(raw, c => c.charCodeAt(0));
    }

    async function post(url, body) {
        const r = await fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': meta('csrf-token') },
            body: JSON.stringify(body),
        });
        let res = {};
        try { res = await r.json(); } catch (e) { /* geen JSON */ }
        if (!r.ok || res.status !== 'success') throw new Error(res.message || 'Er ging iets mis.');
        return res;
    }

    const CSS = `
    .bva-meld{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:14px 16px;border-radius:14px;background:#eef7fa;color:#112233;
      font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;border:1px solid #cfe7f0}
    .bva-meld .tekst{flex:1 1 200px}
    .bva-meld strong{display:block;font-size:15px}
    .bva-meld small{color:#4b5563}
    .bva-meld button{border:0;border-radius:999px;padding:9px 18px;font-weight:700;font-size:14px;cursor:pointer;white-space:nowrap}
    .bva-meld .aan{color:#fff;background:linear-gradient(120deg,#58A6C2 0%,#2f6f8c 45%,#112233 100%)}
    .bva-meld .uit{background:#fff;color:#374151;border:1px solid #d1d5db}
    `;

    function css() {
        if (document.getElementById('bva-meld-css')) return;
        const s = document.createElement('style');
        s.id = 'bva-meld-css';
        s.textContent = CSS;
        document.head.appendChild(s);
    }

    function toon(html) {
        css();
        document.querySelectorAll('[data-meldingen]').forEach(el => {
            el.innerHTML = `<div class="bva-meld">${html}</div>`;
            el.hidden = false;
        });
    }

    async function abonnement() {
        const reg = await navigator.serviceWorker.ready;
        return reg.pushManager.getSubscription();
    }

    function render(status, speler) {
        if (status === 'ios-eerst-installeren') {
            toon(`<span style="font-size:22px">🔔</span><div class="tekst"><strong>Meldingen op je iPhone?</strong>
                <small>Zet de app eerst op je beginscherm. Open hem daarna via het BVA-icoontje en zet hier meldingen aan.</small></div>
                <button type="button" class="aan" data-actie="ios-hoe">Hoe?</button>`);
        } else if (status === 'geblokkeerd') {
            toon(`<span style="font-size:22px">🔕</span><div class="tekst"><strong>Meldingen zijn geblokkeerd</strong>
                <small>Zet ze aan via de instellingen van je telefoon (Meldingen → BVA VSE-2 / je browser).</small></div>`);
        } else if (status === 'aan') {
            const wie = speler ? ` voor ${speler}` : '';
            const tip = speler ? 'Je krijgt ook je persoonlijke opdrachten en herinneringen.'
                : 'Tip: log op de trainingspagina in met je pincode, dan krijg je ook herinneringen voor jouw opdrachten.';
            toon(`<span style="font-size:22px">🔔</span><div class="tekst"><strong>Meldingen staan aan${wie}</strong><small>${tip}</small></div>
                <button type="button" class="uit" data-actie="uit">Uitzetten</button>`);
        } else {
            toon(`<span style="font-size:22px">🔔</span><div class="tekst"><strong>Krijg een melding op je telefoon</strong>
                <small>Bij nieuwe opdrachten, mededelingen en wedstrijdfilms.</small></div>
                <button type="button" class="aan" data-actie="aan">Meldingen aanzetten</button>`);
        }
    }

    async function zetAan(knop) {
        knop.disabled = true;
        knop.textContent = 'Even geduld…';
        try {
            const toestemming = await Notification.requestPermission();
            if (toestemming !== 'granted') { render(toestemming === 'denied' ? 'geblokkeerd' : 'uit'); return; }
            const reg = await navigator.serviceWorker.ready;
            const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: sleutelBytes(meta('push-sleutel')) });
            const res = await post('/api/push/aanmelden/', sub.toJSON());
            render('aan', res.speler);
        } catch (e) {
            alert('Meldingen aanzetten lukte niet: ' + e.message);
            render('uit');
        }
    }

    async function zetUit() {
        try {
            const sub = await abonnement();
            if (sub) {
                await post('/api/push/afmelden/', { endpoint: sub.endpoint }).catch(() => {});
                await sub.unsubscribe();
            }
        } finally {
            render('uit');
        }
    }

    document.addEventListener('click', e => {
        const knop = e.target.closest('[data-meldingen] [data-actie]');
        if (!knop) return;
        if (knop.dataset.actie === 'aan') zetAan(knop);
        else if (knop.dataset.actie === 'uit') zetUit();
        else if (knop.dataset.actie === 'ios-hoe' && window.toonIosUitleg) window.toonIosUitleg();
    });

    document.addEventListener('DOMContentLoaded', async () => {
        if (!document.querySelector('[data-meldingen]') && !kanPush) return;
        if (!meta('push-sleutel')) return;
        if (!kanPush) {
            if (isIOS && !isGeinstalleerd) render('ios-eerst-installeren');
            return;  // browser zonder meldingen: niets tonen
        }
        if (Notification.permission === 'denied') { render('geblokkeerd'); return; }
        try {
            const sub = await abonnement();
            if (sub && Notification.permission === 'granted') {
                // Opnieuw doorgeven (koppelt de ingelogde speelster aan deze telefoon)
                const res = await post('/api/push/aanmelden/', sub.toJSON()).catch(() => ({}));
                render('aan', res.speler);
            } else {
                render('uit');
            }
        } catch (e) {
            render('uit');
        }
    });
})();

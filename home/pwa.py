"""
"Als app op je telefoon" (Progressive Web App).

- /manifest.webmanifest : naam, kleuren en icoontjes van de app
- /sw.js                : service worker (moet in de root staan om de hele site te dekken)
- /offline/             : pagina die je ziet als je geen internet hebt

De service worker houdt het simpel en veilig:
- pagina's: altijd eerst via internet (dus nooit verouderde opdrachten of uitslagen);
  zonder internet de laatst bekeken versie, of anders de offline-pagina;
- CSS/JS/icoontjes: uit de cache, op de achtergrond ververst;
- admin, API en alles behalve GET: nooit uit de cache.
"""
import json

from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

# Verhoog dit als de service worker verandert, dan ruimen telefoons de oude cache op
SW_VERSIE = 'bva-v3'


@cache_control(max_age=3600)
def manifest(request):
    data = {
        'name': 'BVA VSE-2',
        'short_name': 'VSE-2',
        'description': 'Wedstrijden, plays en training van BVA VSE-2',
        'lang': 'nl',
        'start_url': '/?bron=app',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#112233',
        'theme_color': '#112233',
        'icons': [
            {'src': static('img/app/icon-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('img/app/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('img/app/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png',
             'purpose': 'maskable'},
        ],
        'shortcuts': [
            {'name': 'Training', 'url': '/training/', 'icons': [{'src': static('img/app/icon-192.png'), 'sizes': '192x192'}]},
            {'name': 'Wedstrijden', 'url': '/wedstrijden/'},
            {'name': 'Plays', 'url': '/plays/'},
        ],
    }
    return HttpResponse(json.dumps(data, ensure_ascii=False), content_type='application/manifest+json; charset=utf-8')


SERVICE_WORKER = """
const CACHE = '%(versie)s';
const OFFLINE = '/offline/';

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE).then(c => c.addAll([OFFLINE, %(iconen)s])));
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const req = event.request;
    const url = new URL(req.url);
    if (req.method !== 'GET' || url.origin !== self.location.origin) return;
    if (url.pathname.startsWith('/admin') || url.pathname.startsWith('/api/') || url.pathname === '/sw.js') return;

    // Statische bestanden: snel uit de cache, op de achtergrond verversen
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(caches.open(CACHE).then(async cache => {
            const cached = await cache.match(req);
            const vers = fetch(req).then(res => { if (res.ok) cache.put(req, res.clone()); return res; }).catch(() => cached);
            return cached || vers;
        }));
        return;
    }

    // Pagina's: eerst internet; zonder verbinding de laatst bekeken versie of de offline-pagina
    if (req.mode === 'navigate') {
        event.respondWith(
            fetch(req)
                .then(res => {
                    if (res.ok && res.type === 'basic') {
                        const kopie = res.clone();
                        caches.open(CACHE).then(c => c.put(req, kopie));
                    }
                    return res;
                })
                .catch(async () => (await caches.match(req)) || caches.match(OFFLINE))
        );
    }
});

// Pushmelding binnengekomen: tonen met het BVA-logo
self.addEventListener('push', event => {
    let m = {};
    try { m = event.data ? event.data.json() : {}; } catch (e) { m = { tekst: event.data ? event.data.text() : '' }; }
    event.waitUntil(self.registration.showNotification(m.titel || 'BVA VSE-2', {
        body: m.tekst || '',
        icon: %(icoon)s,
        badge: %(icoon)s,
        tag: m.tag || undefined,
        renotify: Boolean(m.tag),
        data: { url: m.url || '/' },
    }));
});

// Op de melding getikt: open (of activeer) de app op de juiste pagina
self.addEventListener('notificationclick', event => {
    event.notification.close();
    const doel = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;
    event.waitUntil((async () => {
        const vensters = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const v of vensters) {
            if (v.url === doel && 'focus' in v) return v.focus();
        }
        if (vensters.length && 'navigate' in vensters[0]) {
            await vensters[0].navigate(doel);
            return vensters[0].focus();
        }
        return self.clients.openWindow(doel);
    })());
});
"""


def service_worker(request):
    iconen = ', '.join(json.dumps(static(f'img/app/{n}')) for n in ('icon-192.png', 'apple-touch-icon.png'))
    js = SERVICE_WORKER % {'versie': SW_VERSIE, 'iconen': iconen, 'icoon': json.dumps(static('img/app/icon-192.png'))}
    response = HttpResponse(js, content_type='application/javascript; charset=utf-8')
    response['Cache-Control'] = 'no-cache'
    response['Service-Worker-Allowed'] = '/'
    return response


def offline(request):
    return render(request, 'home/offline.html')

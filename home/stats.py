"""
Statistieken: optellen van acties tot een box score, en de gegevens voor de statistiekenpagina.

Elke actie is één regel in de database (wie, welk kwart, wat). Alles hier wordt daaruit
uitgerekend, zodat filteren op wedstrijd, speelster en kwart altijd klopt.
"""
from collections import Counter
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import (
    Speler,
    StatActie,
    StatsPage,
    Wedstrijd,
    WedstrijdenArchiefPage,
    _is_thuis,
    ical_wedstrijden,
    kan_film_toevoegen,
    parse_nl_datum,
    tegenstander_uit_titel,
    youtube_embed_url,
)

KWART_LABELS = dict(StatActie.KWARTEN)

# (kop, uitleg, sleutel, soort) — soort: 'n' aantal, 'ma' raak/poging, 'pct' percentage
KOLOMMEN = [
    ('PTS', 'Punten', 'pts', 'n'),
    ('FG', 'Velddoelpunten (2 + 3 punten): raak / pogingen', 'fg', 'ma'),
    ('FG%', 'Percentage velddoelpunten', 'fg', 'pct'),
    ('2P', '2-punters: raak / pogingen', 'twee', 'ma'),
    ('3P', '3-punters: raak / pogingen', 'drie', 'ma'),
    ('3P%', 'Percentage 3-punters', 'drie', 'pct'),
    ('VW', 'Vrije worpen: raak / pogingen', 'vw', 'ma'),
    ('VW%', 'Percentage vrije worpen', 'vw', 'pct'),
    ('OR', 'Aanvallende rebounds', 'or', 'n'),
    ('DR', 'Verdedigende rebounds', 'dr', 'n'),
    ('REB', 'Rebounds totaal', 'reb', 'n'),
    ('AST', 'Assists', 'as', 'n'),
    ('STL', 'Steals', 'st', 'n'),
    ('BLK', 'Blocks', 'bl', 'n'),
    ('TO', 'Balverlies (turnovers)', 'to', 'n'),
    ('PF', 'Fouten', 'pf', 'n'),
]


class Regel:
    """Opgetelde statistieken van een groep acties (een speelster, het team, een kwart ...)."""

    def __init__(self, label='', speler=None):
        self.label = label
        self.speler = speler
        self.n = Counter()
        self.wedstrijd_ids = set()

    def voeg_toe(self, actie):
        self.n[actie.soort] += 1
        self.wedstrijd_ids.add(actie.wedstrijd_id)

    @property
    def pts(self):
        return 2 * self.n['2r'] + 3 * self.n['3r'] + self.n['fr']

    @property
    def tegen(self):
        return self.n['t1'] + 2 * self.n['t2'] + 3 * self.n['t3']

    @property
    def aantal_wedstrijden(self):
        return len(self.wedstrijd_ids)

    def raak_poging(self, sleutel):
        if sleutel == 'twee':
            return self.n['2r'], self.n['2r'] + self.n['2m']
        if sleutel == 'drie':
            return self.n['3r'], self.n['3r'] + self.n['3m']
        if sleutel == 'vw':
            return self.n['fr'], self.n['fr'] + self.n['fm']
        # fg: alle schoten uit het veld
        raak = self.n['2r'] + self.n['3r']
        return raak, raak + self.n['2m'] + self.n['3m']

    def waarde(self, sleutel):
        if sleutel == 'pts':
            return self.pts
        if sleutel == 'reb':
            return self.n['or'] + self.n['dr']
        return self.n[sleutel]

    def cellen(self, gemiddeld=False, deler=None):
        """Waarden voor de tabel, als tekst. Gemiddeld = per wedstrijd."""
        d = (deler or self.aantal_wedstrijden or 1) if gemiddeld else 1

        def getal(x):
            return f'{x / d:.1f}'.replace('.', ',') if gemiddeld else str(x)

        uit = []
        for _kop, _uitleg, sleutel, soort in KOLOMMEN:
            if soort == 'n':
                uit.append(getal(self.waarde(sleutel)))
            elif soort == 'ma':
                raak, poging = self.raak_poging(sleutel)
                uit.append(f'{getal(raak)}/{getal(poging)}')
            else:
                raak, poging = self.raak_poging(sleutel)
                uit.append(f'{round(100 * raak / poging)}%' if poging else '–')
        return uit


def tel(acties, label='', speler=None):
    regel = Regel(label, speler)
    for a in acties:
        regel.voeg_toe(a)
    return regel


def score(acties):
    """(eigen punten, punten tegenstander)."""
    r = tel(acties)
    return r.pts, r.tegen


def _int_of_none(waarde):
    try:
        return int(waarde)
    except (TypeError, ValueError):
        return None


def kan_stats_bijhouden(user, page):
    """Wie publiceer-rechten op de statistiekenpagina heeft, mag statistieken bijhouden."""
    return kan_film_toevoegen(user, page)


def archief_films():
    """Alle geüploade wedstrijdfilms uit het archief, nieuwste eerst: {block_id: {...}}."""
    archief = WedstrijdenArchiefPage.objects.live().first()
    if not archief:
        return {}
    films = {}
    for index, block in enumerate(archief.wedstrijden):
        v = block.value
        datum = parse_nl_datum(v.get('datum_str'))
        films[block.id] = {
            'block_id': block.id,
            'titel': v.get('titel') or '',
            'datum_str': v.get('datum_str') or '',
            'datum': datum.isoformat() if datum else '',
            'uitslag': v.get('uitslag') or '',
            'tegenstander': tegenstander_uit_titel(v.get('titel')),
            'thuis': _is_thuis(v.get('titel') or '', ''),
            'embed_url': youtube_embed_url(v.get('youtube_url')),
            'archief_url': f'{archief.url}?wedstrijd={index}',
            'index': index,
        }
    return dict(sorted(films.items(), key=lambda kv: (kv[1]['datum'], kv[1]['index']), reverse=True))


def homepage_stats(request):
    """Gegevens voor het statistiekenblok op de homepage."""
    page = StatsPage.objects.live().first()
    if not page:
        return {'stats_url': ''}
    laatste = Wedstrijd.objects.filter(acties__isnull=False).distinct().first()
    uit = {
        'stats_url': page.url,
        'kan_stats_bijhouden': kan_stats_bijhouden(request.user, page),
        'stats_laatste': laatste,
        'stats_aantal_wedstrijden': Wedstrijd.objects.filter(acties__isnull=False).distinct().count(),
    }
    if laatste:
        acties = list(laatste.acties.all())
        uit['stats_score'] = score(acties)
        per_speler = {}
        for a in acties:
            if a.speler_id and a.soort in ('2r', '3r', 'fr'):
                per_speler[a.speler_id] = per_speler.get(a.speler_id, 0) + {'2r': 2, '3r': 3, 'fr': 1}[a.soort]
        if per_speler:
            sid = max(per_speler, key=per_speler.get)
            uit['stats_topscorer'] = (Speler.objects.filter(id=sid).first(), per_speler[sid])
    return uit


def ical_suggesties(bestaande):
    """Wedstrijden uit de agenda van 2 weken terug tot 2 weken vooruit die nog niet zijn aangemaakt."""
    games = cache.get('stats-ical-games')
    if games is None:
        games = [{'datum': g['datum'].date(), 'tegenstander': tegenstander_uit_titel(g['titel']),
                  'thuis': g['thuis_uit'] == 'THUIS', 'titel': g['titel']}
                 for g in ical_wedstrijden(timeout=5)]
        cache.set('stats-ical-games', games, 15 * 60)
    vandaag = timezone.localdate()
    al = {(w.datum, w.tegenstander.lower()) for w in bestaande}
    return [
        {**g, 'datum': g['datum'].isoformat(), 'datum_obj': g['datum']}
        for g in games
        if vandaag - timedelta(days=14) <= g['datum'] <= vandaag + timedelta(days=14)
        and (g['datum'], g['tegenstander'].lower()) not in al
    ]


def _bijhouden_context(page, wedstrijd, spelers_alle):
    acties = list(wedstrijd.acties.all())
    film = archief_films().get(wedstrijd.film_block_id) if wedstrijd.film_block_id else None
    in_wedstrijd = {a.speler_id for a in acties if a.speler_id}
    spelers = [s for s in spelers_alle if s.actief or s.id in in_wedstrijd]
    return {
        'bijhouden': wedstrijd,
        'bijhouden_film': film,
        'bijhouden_data': {
            'page_id': page.id,
            'wedstrijd_id': wedstrijd.id,
            'tegenstander': wedstrijd.tegenstander,
            'spelers': [{'id': s.id, 'naam': s.naam, 'nr': s.rugnummer} for s in spelers],
            'acties': [{'id': a.id, 'cid': a.client_id, 's': a.speler_id, 'k': a.kwart, 't': a.soort} for a in acties],
            'soorten': dict(StatActie.SOORTEN),
        },
    }


def stats_context(page, request):
    beheerder = kan_stats_bijhouden(request.user, page)
    wedstrijden = list(Wedstrijd.objects.all())
    spelers_alle = list(Speler.objects.all())
    context = {'kan_stats_bijhouden': beheerder, 'wedstrijden': wedstrijden}

    # Bijhoud-scherm voor één wedstrijd
    if beheerder and request.GET.get('bijhouden'):
        wedstrijd = next((w for w in wedstrijden if w.id == _int_of_none(request.GET.get('bijhouden'))), None)
        if wedstrijd:
            context.update(_bijhouden_context(page, wedstrijd, spelers_alle))
            return context

    # Filters
    gekozen_wedstrijd = next((w for w in wedstrijden if w.id == _int_of_none(request.GET.get('wedstrijd'))), None)
    kwart = _int_of_none(request.GET.get('kwart'))
    kwart = kwart if kwart in KWART_LABELS else None
    gekozen_speler = next((s for s in spelers_alle if s.id == _int_of_none(request.GET.get('speler'))), None)
    gemiddeld = request.GET.get('weergave') == 'gem' and not gekozen_wedstrijd

    alle_acties = list(StatActie.objects.all() if not gekozen_wedstrijd
                       else StatActie.objects.filter(wedstrijd=gekozen_wedstrijd))
    if kwart:
        acties = [a for a in alle_acties if a.kwart == kwart]
    else:
        acties = alle_acties
    eigen = [a for a in acties if a.soort not in StatActie.TEGENSTANDER]

    # Wedstrijden die (binnen de filters) acties hebben, voor gemiddelden en de tabel per wedstrijd
    met_acties = {a.wedstrijd_id for a in acties}
    getoonde_wedstrijden = [w for w in wedstrijden if w.id in met_acties]

    # Box score: een regel per speelster + team totaal
    per_speler = {}
    for a in eigen:
        if a.speler_id:
            per_speler.setdefault(a.speler_id, []).append(a)
    spelers_volgorde = [s for s in spelers_alle if s.id in per_speler]
    if gekozen_speler:
        spelers_volgorde = [s for s in spelers_volgorde if s.id == gekozen_speler.id]
    box = []
    for s in spelers_volgorde:
        r = tel(per_speler[s.id], s.naam, s)
        box.append({'regel': r, 'cellen': r.cellen(gemiddeld), 'wedstrijden': r.aantal_wedstrijden})
    team = tel(eigen, 'Team totaal')
    team_rij = {'regel': team, 'cellen': team.cellen(gemiddeld, len(getoonde_wedstrijden)),
                'wedstrijden': len(getoonde_wedstrijden)}

    # Onderwerp van de tabellen per wedstrijd/kwart: de gekozen speelster, anders het team
    def van_onderwerp(lijst):
        if gekozen_speler:
            return [a for a in lijst if a.speler_id == gekozen_speler.id and a.soort not in StatActie.TEGENSTANDER]
        return [a for a in lijst if a.soort not in StatActie.TEGENSTANDER]

    per_wedstrijd = []
    if not gekozen_wedstrijd:
        for w in getoonde_wedstrijden:
            w_acties = [a for a in acties if a.wedstrijd_id == w.id]
            r = tel(van_onderwerp(w_acties), str(w))
            wij, zij = score(w_acties)
            per_wedstrijd.append({'wedstrijd': w, 'wij': wij, 'zij': zij, 'cellen': r.cellen()})

    per_kwart = []
    if not kwart:
        for k, label in StatActie.KWARTEN:
            k_acties = [a for a in alle_acties if a.kwart == k]
            if not k_acties and k == 5:
                continue  # verlenging alleen tonen als die gespeeld is
            r = tel(van_onderwerp(k_acties), label)
            wij, zij = score(k_acties)
            per_kwart.append({'kwart': k, 'label': label, 'wij': wij, 'zij': zij,
                              'cellen': r.cellen(gemiddeld, len(getoonde_wedstrijden))})

    # Scorebord bovenaan bij één wedstrijd
    scorebord = None
    if gekozen_wedstrijd:
        wij, zij = score(alle_acties)
        scorebord = {'wij': wij, 'zij': zij, 'kwarten': [
            {'label': label, 'wij': score([a for a in alle_acties if a.kwart == k])[0],
             'zij': score([a for a in alle_acties if a.kwart == k])[1]}
            for k, label in StatActie.KWARTEN
            if k < 5 or any(a.kwart == 5 for a in alle_acties)
        ]}

    # Scores per wedstrijd voor de lijst
    scores = {}
    for a in StatActie.objects.all().only('wedstrijd_id', 'soort'):
        wij, zij = scores.get(a.wedstrijd_id, (0, 0))
        punten = {'2r': 2, '3r': 3, 'fr': 1}.get(a.soort, 0)
        tegen = {'t1': 1, 't2': 2, 't3': 3}.get(a.soort, 0)
        scores[a.wedstrijd_id] = (wij + punten, zij + tegen)
    wedstrijden_lijst = [{'wedstrijd': w, 'wij': scores.get(w.id, (0, 0))[0], 'zij': scores.get(w.id, (0, 0))[1],
                          'heeft_acties': w.id in scores} for w in wedstrijden]

    context.update({
        'kolommen': KOLOMMEN,
        'box': box,
        'team_rij': team_rij,
        'per_wedstrijd': per_wedstrijd,
        'per_kwart': per_kwart,
        'scorebord': scorebord,
        'wedstrijden_lijst': wedstrijden_lijst,
        'spelers_filter': [s for s in spelers_alle if s.actief or s.stat_acties.exists()],
        'kwarten': StatActie.KWARTEN,
        'f_wedstrijd': gekozen_wedstrijd,
        'f_kwart': kwart,
        'f_kwart_label': KWART_LABELS.get(kwart),
        'f_speler': gekozen_speler,
        'gemiddeld': gemiddeld,
        'heeft_stats': bool(acties),
    })
    films = archief_films()
    for item in wedstrijden_lijst:
        item['film'] = films.get(item['wedstrijd'].film_block_id)
    context['f_film'] = films.get(gekozen_wedstrijd.film_block_id) if gekozen_wedstrijd else None
    if beheerder:
        gekoppeld = {w.film_block_id for w in wedstrijden if w.film_block_id}
        context['films'] = list(films.values())
        context['film_suggesties'] = [f for f in films.values() if f['block_id'] not in gekoppeld]
        context['ical_suggesties'] = ical_suggesties(wedstrijden)
        context['wedstrijd_data'] = {
            str(w.id): {'datum': w.datum.isoformat(), 'tegenstander': w.tegenstander, 'thuis': w.thuis,
                        'film': w.film_block_id}
            for w in wedstrijden
        }
    return context

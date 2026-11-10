"""
API voor reacties op het wedstrijdarchief en de plays-pagina.

Er is geen login voor teamleden. Daarom krijgt wie een reactie plaatst een geheime
bewerk-sleutel terug, die de browser bewaart. Alleen met die sleutel kan de reactie
later bewerkt of verwijderd worden. In de database staat alleen een hash van de sleutel.
Ingelogde Wagtail-beheerders (moderators) mogen alle reacties beheren.
"""
import hashlib
import hmac
import json
import secrets

from django.http import JsonResponse
from datetime import timedelta

from django.utils import timezone
from django.views.decorators.http import require_POST
from wagtail.models import Page

from . import push
from .models import (
    PlaysPage,
    WedstrijdenArchiefPage,
    WedstrijdReactie,
    is_moderator,
    kan_film_toevoegen,
    youtube_embed_url,
)

MAX_NAAM = 100
MAX_TEKST = 2000
ROLLEN = {'coach', 'teammate'}


def _hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _fout(message, status=400):
    return JsonResponse({'status': 'error', 'message': message}, status=status)


def _lees_json(request):
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _mag_beheren(request, reactie, token):
    """Mag deze bezoeker deze reactie bewerken/verwijderen?"""
    if is_moderator(request.user):
        return True
    if not reactie.bewerk_token_hash or not isinstance(token, str) or not token:
        return False
    return hmac.compare_digest(_hash(token), reactie.bewerk_token_hash)


def _block_ids_op_pagina(page):
    if isinstance(page, WedstrijdenArchiefPage):
        return {b.id for b in page.wedstrijden}
    if isinstance(page, PlaysPage):
        return {b.id for b in page.plays}
    return None


@require_POST
def sla_reactie_op(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')

    auteur = str(data.get('auteur') or '').strip()
    tekst = str(data.get('tekst') or '').strip()
    rol = data.get('rol')

    if not auteur or not tekst:
        return _fout('Naam en reactie zijn verplicht.')
    if len(auteur) > MAX_NAAM or len(tekst) > MAX_TEKST:
        return _fout(f'Naam (max {MAX_NAAM}) of reactie (max {MAX_TEKST} tekens) is te lang.')
    if rol not in ROLLEN:
        return _fout('Ongeldige rol.')
    if rol == 'coach' and not is_moderator(request.user):
        return _fout('Alleen ingelogde coaches en trainers kunnen als coach reageren.', status=403)

    try:
        page = Page.objects.live().get(id=int(data.get('page_id'))).specific
    except (Page.DoesNotExist, TypeError, ValueError):
        return _fout('Pagina niet gevonden.', status=404)

    block_id = str(data.get('block_id') or '')
    geldige_ids = _block_ids_op_pagina(page)
    if geldige_ids is None or block_id not in geldige_ids:
        return _fout('Onbekende wedstrijd of play.')

    token = secrets.token_urlsafe(32)
    reactie = WedstrijdReactie.objects.create(
        page=page,
        block_id=block_id,
        auteur_naam=auteur,
        rol=rol,
        tekst=tekst,
        bewerk_token_hash=_hash(token),
    )
    return JsonResponse({
        'status': 'success',
        'id': reactie.id,
        'token': token,  # alleen nu één keer terug naar de schrijver
        'auteur': reactie.auteur_naam,
        'rol': reactie.rol,
        'tekst': reactie.tekst,
    })


@require_POST
def bewerk_reactie(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')

    tekst = str(data.get('tekst') or '').strip()
    if not tekst:
        return _fout('De reactie mag niet leeg zijn.')
    if len(tekst) > MAX_TEKST:
        return _fout(f'De reactie mag maximaal {MAX_TEKST} tekens zijn.')

    try:
        reactie = WedstrijdReactie.objects.get(id=int(data.get('id')))
    except (WedstrijdReactie.DoesNotExist, TypeError, ValueError):
        return _fout('Reactie niet gevonden.', status=404)

    if not _mag_beheren(request, reactie, data.get('token')):
        return _fout('Je mag alleen je eigen reacties bewerken.', status=403)

    reactie.tekst = tekst
    reactie.datum_bewerkt = timezone.now()
    reactie.save(update_fields=['tekst', 'datum_bewerkt'])
    return JsonResponse({'status': 'success', 'id': reactie.id, 'tekst': reactie.tekst})


@require_POST
def verwijder_reactie(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')

    try:
        reactie = WedstrijdReactie.objects.get(id=int(data.get('id')))
    except (WedstrijdReactie.DoesNotExist, TypeError, ValueError):
        return _fout('Reactie niet gevonden.', status=404)

    if not _mag_beheren(request, reactie, data.get('token')):
        return _fout('Je mag alleen je eigen reacties verwijderen.', status=403)

    reactie.delete()
    return JsonResponse({'status': 'success'})


# ---------------------------------------------------------------------------
# Film toevoegen (voor coaches) op het wedstrijdarchief en de plays-pagina
# ---------------------------------------------------------------------------

def _tekstveld(data, naam, max_len, verplicht=False):
    waarde = str(data.get(naam) or '').strip()
    if verplicht and not waarde:
        raise ValueError(f'"{naam.replace("_", " ")}" is verplicht.')
    if len(waarde) > max_len:
        raise ValueError(f'"{naam.replace("_", " ")}" mag maximaal {max_len} tekens zijn.')
    return waarde


def _youtube_veld(data, naam, verplicht=False):
    url = _tekstveld(data, naam, 500, verplicht=verplicht)
    if url and not youtube_embed_url(url):
        raise ValueError('Dit is geen geldige YouTube-link: ' + url)
    return url


@require_POST
def film_toevoegen(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')

    try:
        page = Page.objects.live().get(id=int(data.get('page_id'))).specific
    except (Page.DoesNotExist, TypeError, ValueError):
        return _fout('Pagina niet gevonden.', status=404)

    if not isinstance(page, (WedstrijdenArchiefPage, PlaysPage)):
        return _fout('Op deze pagina kun je geen film toevoegen.')
    if not kan_film_toevoegen(request.user, page):
        return _fout('Alleen coaches mogen films toevoegen. Log eerst in.', status=403)

    try:
        if isinstance(page, WedstrijdenArchiefPage):
            veld, block_type = page.wedstrijden, 'wedstrijd'
            waarde = {
                'titel': _tekstveld(data, 'titel', 255, verplicht=True),
                'datum_str': _tekstveld(data, 'datum_str', 255, verplicht=True),
                'uitslag': _tekstveld(data, 'uitslag', 255, verplicht=True),
                'youtube_url': _youtube_veld(data, 'youtube_url', verplicht=True),
            }
        else:
            veld, block_type = page.plays, 'play'
            waarde = {
                'titel': _tekstveld(data, 'titel', 255, verplicht=True),
                'categorie': _tekstveld(data, 'categorie', 255, verplicht=True),
                'korte_beschrijving': _tekstveld(data, 'korte_beschrijving', 255, verplicht=True),
                'video_reallife': _youtube_veld(data, 'video_reallife'),
                'video_defense': _youtube_veld(data, 'video_defense'),
                'video_animatie': _youtube_veld(data, 'video_animatie'),
                'opstelling': _tekstveld(data, 'opstelling', 255),
                'focus': _tekstveld(data, 'focus', 255),
                'stap_1': _tekstveld(data, 'stap_1', 255),
                'stap_2': _tekstveld(data, 'stap_2', 255),
                'stap_3': _tekstveld(data, 'stap_3', 255),
                'stap_4': _tekstveld(data, 'stap_4', 255),
            }
            if not (waarde['video_reallife'] or waarde['video_defense'] or waarde['video_animatie']):
                raise ValueError('Vul minstens één video in (zonder defense, met defense of animatie).')
    except ValueError as e:
        return _fout(str(e))

    block = veld.stream_block.child_blocks[block_type]
    block_id = str(data.get('block_id') or '')
    if block_id:
        # Bestaande wedstrijd/play bijwerken; het id blijft gelijk, dus reacties blijven eraan hangen
        nieuwe_index = next((i for i, b in enumerate(veld) if b.id == block_id), None)
        if nieuwe_index is None:
            return _fout('Deze wedstrijd of play bestaat niet meer.', status=404)
        veld[nieuwe_index] = (block_type, block.to_python(waarde), block_id)
    else:
        veld.append((block_type, block.to_python(waarde)))
        nieuwe_index = len(veld) - 1
        param = 'wedstrijd' if block_type == 'wedstrijd' else 'play'
        push.stuur(
            '🎥 Nieuwe wedstrijdfilm' if block_type == 'wedstrijd' else '🏀 Nieuwe play',
            waarde['titel'] + (f" ({waarde['uitslag']})" if block_type == 'wedstrijd' else f" · {waarde['categorie']}"),
            url=f'{page.url}?{param}={nieuwe_index}',
        )

    revisie = page.save_revision(user=request.user, log_action=True)
    revisie.publish(user=request.user)

    return JsonResponse({'status': 'success', 'index': nieuwe_index})


@require_POST
def film_verwijderen(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')
    try:
        page = Page.objects.live().get(id=int(data.get('page_id'))).specific
    except (Page.DoesNotExist, TypeError, ValueError):
        return _fout('Pagina niet gevonden.', status=404)
    if not isinstance(page, (WedstrijdenArchiefPage, PlaysPage)):
        return _fout('Op deze pagina kun je niets verwijderen.')
    if not kan_film_toevoegen(request.user, page):
        return _fout('Alleen coaches mogen films verwijderen.', status=403)

    veld = page.wedstrijden if isinstance(page, WedstrijdenArchiefPage) else page.plays
    block_id = str(data.get('block_id') or '')
    index = next((i for i, b in enumerate(veld) if b.id == block_id), None)
    if index is None:
        return _fout('Deze wedstrijd of play bestaat niet meer.', status=404)

    del veld[index]
    page.save_revision(user=request.user, log_action=True).publish(user=request.user)
    WedstrijdReactie.objects.filter(page=page, block_id=block_id).delete()
    return JsonResponse({'status': 'success'})


# ---------------------------------------------------------------------------
# Inloggen / uitloggen voor coaches vanaf de pagina zelf
# ---------------------------------------------------------------------------
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache

from .beveiliging import BLOKKADE_MELDING, client_ip as _client_ip, is_geblokkeerd


def _mag_beheren_op(user, page):
    """Mag deze coach/trainer op deze pagina iets aanpassen (en dus hier inloggen)?"""
    from .models import HomePage, TeamPage
    if kan_film_toevoegen(user, page):
        return True
    if isinstance(page, HomePage):
        return user.has_perm('home.add_mededeling')
    if isinstance(page, TeamPage):
        return user.has_perm('home.change_speler')
    return False


@require_POST
def coach_inloggen(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')

    gebruikersnaam = str(data.get('gebruikersnaam') or '').strip()
    if is_geblokkeerd(request, gebruikersnaam):
        return _fout(BLOKKADE_MELDING, status=429)

    try:
        page = Page.objects.live().get(id=int(data.get('page_id'))).specific
    except (Page.DoesNotExist, TypeError, ValueError):
        return _fout('Pagina niet gevonden.', status=404)

    user = authenticate(
        request,
        username=gebruikersnaam,
        password=str(data.get('wachtwoord') or ''),
    )
    if user is None:  # de foute poging wordt geteld in beveiliging.py
        return _fout('Onjuiste naam of wachtwoord.', status=401)

    if not _mag_beheren_op(user, page):
        return _fout('Dit account mag op deze pagina niets aanpassen.', status=403)

    login(request, user)  # wist ook de teller (beveiliging.py)
    return JsonResponse({'status': 'success', 'naam': user.get_full_name() or user.username})


@require_POST
def coach_uitloggen(request):
    logout(request)
    return JsonResponse({'status': 'success'})


# ---------------------------------------------------------------------------
# Training: speelster kiezen (pincode), afvinken, opdrachten beheren
# ---------------------------------------------------------------------------
from datetime import date as _date

from .models import Afvinking, Opdracht, Speler, TrainingPage, week_start

MAX_PIN_POGINGEN = 5             # foute pincodes per speelster ...
MAX_PIN_POGINGEN_PER_ADRES = 20  # ... en per IP-adres (hele team op dezelfde wifi) ...
PIN_BLOKKEER_SECONDEN = 15 * 60  # ... binnen 15 minuten
SPELER_SESSIE_DAGEN = 60


def _training_page(data):
    try:
        page = Page.objects.live().get(id=int(data.get('page_id'))).specific
    except (Page.DoesNotExist, TypeError, ValueError):
        return None
    return page if isinstance(page, TrainingPage) else None


def _lees_datum(waarde):
    try:
        return _date.fromisoformat(str(waarde))
    except (TypeError, ValueError):
        return None


def _lees_week(waarde):
    try:
        return week_start(_date.fromisoformat(str(waarde)))
    except (TypeError, ValueError):
        return None


@require_POST
def speler_kiezen(request):
    """Speelster maakt zich bekend met naam + pincode. Wordt onthouden in de sessie."""
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')

    try:
        speler = Speler.objects.get(id=int(data.get('speler_id')), actief=True)
    except (Speler.DoesNotExist, TypeError, ValueError):
        return _fout('Kies je naam uit de lijst.')

    # Per speelster streng (tegen raden); per adres ruimer, want een team op één wifi deelt een adres
    limieten = {f'pin-pogingen:speler:{speler.id}': MAX_PIN_POGINGEN,
                f'pin-pogingen:ip:{_client_ip(request)}': MAX_PIN_POGINGEN_PER_ADRES}
    sleutels = list(limieten)
    if any(cache.get(k, 0) >= limiet for k, limiet in limieten.items()):
        return _fout('Te veel foute pincodes. Probeer het over 15 minuten opnieuw.', status=429)

    if not speler.heeft_pincode:
        return _fout('Je hebt nog geen pincode. Vraag de trainer of coach om er een in te stellen.', status=403)

    if not speler.check_pincode(str(data.get('pincode') or '').strip()):
        for k in sleutels:
            cache.set(k, cache.get(k, 0) + 1, PIN_BLOKKEER_SECONDEN)
        return _fout('Onjuiste pincode.', status=401)

    for k in sleutels:
        cache.delete(k)
    request.session[TrainingPage.SESSIE_SPELER] = speler.id
    if not request.user.is_authenticated:
        request.session.set_expiry(SPELER_SESSIE_DAGEN * 24 * 3600)
    return JsonResponse({'status': 'success', 'naam': speler.naam})


@require_POST
def speler_wisselen(request):
    request.session.pop(TrainingPage.SESSIE_SPELER, None)
    return JsonResponse({'status': 'success'})


@require_POST
def opdracht_afvinken(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')

    try:
        speler = Speler.objects.get(id=request.session.get(TrainingPage.SESSIE_SPELER), actief=True)
    except (Speler.DoesNotExist, TypeError, ValueError):
        return _fout('Kies eerst je naam en vul je pincode in.', status=403)

    week = _lees_week(data.get('week'))
    if week is None:
        return _fout('Ongeldige week.')
    if week > week_start(timezone.localdate()):
        return _fout('Je kunt opdrachten van een komende week nog niet afvinken.')

    try:
        opdracht = Opdracht.objects.get(id=int(data.get('opdracht_id')))
    except (Opdracht.DoesNotExist, TypeError, ValueError):
        return _fout('Opdracht niet gevonden.', status=404)
    if not opdracht.geldt_in_week(week):
        return _fout('Deze opdracht hoort niet bij die week.')
    if not opdracht.geldt_voor(speler):
        return _fout('Deze opdracht is niet voor jou.', status=403)

    sleutel = opdracht.afvink_week(week)  # eenmalig: één afvinking voor de hele periode
    if data.get('gedaan'):
        Afvinking.objects.get_or_create(speler=speler, opdracht=opdracht, week=sleutel)
    else:
        Afvinking.objects.filter(speler=speler, opdracht=opdracht, week=sleutel).delete()
    return JsonResponse({'status': 'success', 'gedaan': bool(data.get('gedaan'))})


@require_POST
def opdracht_toevoegen(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')

    page = _training_page(data)
    if page is None:
        return _fout('Pagina niet gevonden.', status=404)
    if not kan_film_toevoegen(request.user, page):
        return _fout('Alleen trainers mogen opdrachten toevoegen. Log eerst in.', status=403)

    try:
        titel = _tekstveld(data, 'titel', 150, verplicht=True)
        uitleg = _tekstveld(data, 'uitleg', 3000)
        video_url = _youtube_veld(data, 'video_url')
        hoeveelheid = _tekstveld(data, 'hoeveelheid', 100)
        categorie = str(data.get('categorie') or '')
        if categorie not in dict(Opdracht.CATEGORIEEN):
            raise ValueError('Kies een categorie.')
        begin = _lees_datum(data.get('begin'))
        eind = _lees_datum(data.get('eind'))
        if begin is None:
            raise ValueError('Kies een geldige begindatum.')
        if eind is None:
            raise ValueError('Kies een geldige einddatum.')
        if eind < begin:
            raise ValueError('De einddatum kan niet vóór de begindatum liggen.')
        if (eind - begin).days > 366:
            raise ValueError('Een opdracht kan maximaal een jaar duren.')
        herhalend = bool(data.get('herhalend'))

        # Lege lijst = voor iedereen
        gekozen = data.get('spelers') or []
        if not isinstance(gekozen, list):
            raise ValueError('Ongeldige speelsters.')
        try:
            gekozen_ids = {int(x) for x in gekozen}
        except (TypeError, ValueError):
            raise ValueError('Ongeldige speelsters.')
        voor_spelers = list(Speler.objects.filter(id__in=gekozen_ids, actief=True))
        if len(voor_spelers) != len(gekozen_ids):
            raise ValueError('Een van de gekozen speelsters bestaat niet (meer).')
    except ValueError as e:
        return _fout(str(e))

    velden = dict(titel=titel, uitleg=uitleg, video_url=video_url, hoeveelheid=hoeveelheid, categorie=categorie,
                  begin=begin, eind=eind, herhalend=herhalend)
    if data.get('id'):
        try:
            opdracht = Opdracht.objects.get(id=int(data.get('id')))
        except (Opdracht.DoesNotExist, TypeError, ValueError):
            return _fout('Deze opdracht bestaat niet meer.', status=404)
        for k, v in velden.items():
            setattr(opdracht, k, v)
        opdracht.save()
    else:
        opdracht = Opdracht.objects.create(**velden, aangemaakt_door=request.user)
    opdracht.voor_spelers.set(voor_spelers)
    if not data.get('id'):
        week = week_start(opdracht.begin)
        push.stuur(
            '🏋️ Nieuwe opdracht' + (' voor jou' if voor_spelers else ''),
            f'{opdracht.titel}' + (f' · {opdracht.hoeveelheid}' if opdracht.hoeveelheid else '')
            + (f' · vóór {opdracht.eind:%d-%m}' if not opdracht.herhalend else ''),
            url=f'{page.url}?week={week.isoformat()}',
            spelers=voor_spelers or None,
        )
    # Terug naar deze week als de opdracht nu loopt, anders naar de week waarin hij begint
    vandaag = timezone.localdate()
    toon = vandaag if begin <= vandaag <= eind else begin
    return JsonResponse({'status': 'success', 'index': opdracht.id, 'week': week_start(toon).isoformat()})


@require_POST
def opdracht_verwijderen(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')

    page = _training_page(data)
    if page is None:
        return _fout('Pagina niet gevonden.', status=404)
    if not kan_film_toevoegen(request.user, page):
        return _fout('Alleen trainers mogen opdrachten verwijderen.', status=403)

    try:
        opdracht = Opdracht.objects.get(id=int(data.get('id')))
    except (Opdracht.DoesNotExist, TypeError, ValueError):
        return _fout('Opdracht niet gevonden.', status=404)

    week = _lees_week(data.get('week'))
    if opdracht.herhalend and data.get('alleen_vanaf_deze_week') and week and week > opdracht.begin_week:
        # Herhalende opdracht stoppen vanaf deze week; eerdere weken (en afvinkingen) blijven bewaard
        opdracht.eind = min(opdracht.eind, week - timedelta(days=1))
        opdracht.save(update_fields=['eind'])
        return JsonResponse({'status': 'success', 'gestopt': True})

    opdracht.delete()
    return JsonResponse({'status': 'success', 'gestopt': False})


# ---------------------------------------------------------------------------
# Beheer op de site zelf: mededelingen, spelers, staf en teamfoto
# (zodat coaches en trainers nooit naar de Wagtail-admin hoeven)
# ---------------------------------------------------------------------------
from django.utils.html import escape
from wagtail.images import get_image_model

from .models import Mededeling, TeamPage

MAX_FOTO_MB = 10
FOTO_FORMATEN = {'JPEG', 'PNG', 'WEBP', 'GIF'}


def _maak_foto(bestand, titel):
    """Sla een geüploade foto op als Wagtail-afbeelding (na controle dat het echt een foto is)."""
    if bestand.size > MAX_FOTO_MB * 1024 * 1024:
        raise ValueError(f'De foto mag maximaal {MAX_FOTO_MB} MB zijn.')
    from PIL import Image as PILImage
    try:
        with PILImage.open(bestand) as im:
            formaat = im.format
            im.verify()
    except Exception:
        raise ValueError('Dit bestand is geen geldige foto.')
    if formaat not in FOTO_FORMATEN:
        raise ValueError('Gebruik een JPG-, PNG- of WebP-foto.')
    bestand.seek(0)
    foto = get_image_model()(title=(titel or 'Foto')[:255], file=bestand)
    foto.save()
    return foto


def _tekst_naar_html(tekst):
    """Platte tekst (met lege regels als alinea's) naar eenvoudige rich text."""
    alineas = [a.strip() for a in tekst.replace('\r\n', '\n').split('\n\n') if a.strip()]
    return ''.join('<p>' + escape(a).replace('\n', '<br/>') + '</p>' for a in alineas)


def _datum_of_none(waarde):
    waarde = str(waarde or '').strip()
    if not waarde:
        return None
    try:
        return _date.fromisoformat(waarde)
    except ValueError:
        raise ValueError('Ongeldige datum.')


# ---- Mededelingen ---------------------------------------------------------

@require_POST
def mededeling_opslaan(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')
    bestaand_id = data.get('id')
    if not request.user.has_perm('home.change_mededeling' if bestaand_id else 'home.add_mededeling'):
        return _fout('Alleen coaches en trainers mogen mededelingen plaatsen.', status=403)

    try:
        titel = _tekstveld(data, 'titel', 120, verplicht=True)
        tekst = _tekstveld(data, 'tekst', 1000)
        vanaf = _datum_of_none(data.get('zichtbaar_vanaf')) or timezone.localdate()
        tot = _datum_of_none(data.get('zichtbaar_tot'))
        if tot and tot < vanaf:
            raise ValueError('"Zichtbaar tot" kan niet vóór "zichtbaar vanaf" liggen.')
    except ValueError as e:
        return _fout(str(e))

    if bestaand_id:
        try:
            m = Mededeling.objects.get(id=int(bestaand_id))
        except (Mededeling.DoesNotExist, TypeError, ValueError):
            return _fout('Deze mededeling bestaat niet meer.', status=404)
    else:
        m = Mededeling(aangemaakt_door=request.user)
    m.titel, m.tekst, m.belangrijk = titel, tekst, bool(data.get('belangrijk'))
    m.zichtbaar_vanaf, m.zichtbaar_tot = vanaf, tot
    m.save()
    if not bestaand_id and vanaf <= timezone.localdate():
        push.stuur(('📌 ' if m.belangrijk else '📢 ') + m.titel, m.tekst or 'Nieuwe mededeling van de coach & trainers', url='/')
    return JsonResponse({'status': 'success', 'id': m.id})


@require_POST
def mededeling_verwijderen(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')
    if not request.user.has_perm('home.delete_mededeling'):
        return _fout('Alleen coaches en trainers mogen mededelingen verwijderen.', status=403)
    deleted, _ = Mededeling.objects.filter(id=data.get('id')).delete()
    if not deleted:
        return _fout('Deze mededeling bestaat niet meer.', status=404)
    return JsonResponse({'status': 'success'})


# ---- Spelers (teampagina) -------------------------------------------------

@require_POST
def speler_opslaan(request):
    """Multipart-formulier (vanwege de foto). Lege pincode = huidige pincode houden."""
    p = request.POST
    bestaand_id = p.get('id')
    if not request.user.has_perm('home.change_speler' if bestaand_id else 'home.add_speler'):
        return _fout('Alleen coaches en trainers mogen speelsters beheren.', status=403)

    if bestaand_id:
        try:
            speler = Speler.objects.get(id=int(bestaand_id))
        except (Speler.DoesNotExist, TypeError, ValueError):
            return _fout('Deze speelster bestaat niet meer.', status=404)
    else:
        speler = Speler()

    try:
        naam = _tekstveld(p, 'naam', 100, verplicht=True)
        rug = (p.get('rugnummer') or '').strip()
        if rug and not (rug.isdigit() and 0 <= int(rug) <= 99):
            raise ValueError('Het rugnummer moet een getal van 0 tot en met 99 zijn.')
        positie = p.get('positie') or ''
        if positie and positie not in dict(Speler.POSITIES):
            raise ValueError('Ongeldige positie.')
        pin = (p.get('pincode') or '').strip()
        if pin and not (len(pin) == 4 and pin.isdigit()):
            raise ValueError('De pincode moet uit precies 4 cijfers bestaan.')
        if not bestaand_id and not pin:
            raise ValueError('Geef een nieuwe speelster een pincode (of klik op 🎲).')
        nieuwe_foto = _maak_foto(request.FILES['foto'], naam) if request.FILES.get('foto') else None
    except ValueError as e:
        return _fout(str(e))

    speler.naam = naam
    speler.rugnummer = int(rug) if rug else None
    speler.positie = positie
    speler.actief = p.get('actief') in ('1', 'true', 'on')
    if nieuwe_foto:
        speler.foto = nieuwe_foto
    elif p.get('foto_verwijderen') == '1':
        speler.foto = None
    if pin:
        speler.set_pincode(pin)
    speler.save()
    return JsonResponse({'status': 'success', 'id': speler.id})


# ---- Staf, teamfoto en intro (teampagina) ---------------------------------

def _team_page_voor(request, page_id):
    try:
        page = TeamPage.objects.live().get(id=int(page_id))
    except (TeamPage.DoesNotExist, TypeError, ValueError):
        return None, _fout('Pagina niet gevonden.', status=404)
    if not kan_film_toevoegen(request.user, page):
        return None, _fout('Alleen coaches mogen de staf en teamfoto aanpassen.', status=403)
    return page, None


@require_POST
def staf_opslaan(request):
    page, fout = _team_page_voor(request, request.POST.get('page_id'))
    if fout:
        return fout
    try:
        naam = _tekstveld(request.POST, 'naam', 100, verplicht=True)
        rol = _tekstveld(request.POST, 'rol', 100, verplicht=True)
        nieuwe_foto = _maak_foto(request.FILES['foto'], naam) if request.FILES.get('foto') else None
    except ValueError as e:
        return _fout(str(e))

    block = page.staf.stream_block.child_blocks['persoon']
    block_id = request.POST.get('block_id') or ''
    if block_id:
        index = next((i for i, b in enumerate(page.staf) if b.id == block_id), None)
        if index is None:
            return _fout('Dit staflid bestaat niet meer.', status=404)
        foto = page.staf[index].value.get('foto')
        if nieuwe_foto:
            foto = nieuwe_foto
        elif request.POST.get('foto_verwijderen') == '1':
            foto = None
        page.staf[index] = ('persoon', block.to_python({'naam': naam, 'rol': rol, 'foto': foto.id if foto else None}), block_id)
    else:
        page.staf.append(('persoon', block.to_python(
            {'naam': naam, 'rol': rol, 'foto': nieuwe_foto.id if nieuwe_foto else None})))
    page.save_revision(user=request.user, log_action=True).publish(user=request.user)
    return JsonResponse({'status': 'success'})


@require_POST
def staf_verwijderen(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')
    page, fout = _team_page_voor(request, data.get('page_id'))
    if fout:
        return fout
    index = next((i for i, b in enumerate(page.staf) if b.id == data.get('block_id')), None)
    if index is None:
        return _fout('Dit staflid bestaat niet meer.', status=404)
    del page.staf[index]
    page.save_revision(user=request.user, log_action=True).publish(user=request.user)
    return JsonResponse({'status': 'success'})


@require_POST
def teaminfo_opslaan(request):
    page, fout = _team_page_voor(request, request.POST.get('page_id'))
    if fout:
        return fout
    try:
        intro = _tekstveld(request.POST, 'intro', 3000)
        nieuwe_foto = _maak_foto(request.FILES['teamfoto'], 'Teamfoto BVA VSE-2') if request.FILES.get('teamfoto') else None
    except ValueError as e:
        return _fout(str(e))
    page.intro = _tekst_naar_html(intro)
    if nieuwe_foto:
        page.teamfoto = nieuwe_foto
    elif request.POST.get('teamfoto_verwijderen') == '1':
        page.teamfoto = None
    page.save_revision(user=request.user, log_action=True).publish(user=request.user)
    return JsonResponse({'status': 'success'})


# ---------------------------------------------------------------------------
# Pushmeldingen: telefoon aan- en afmelden
# ---------------------------------------------------------------------------
from .models import PushAbonnement


@require_POST
def push_aanmelden(request):
    """Wordt ook bij elk paginabezoek opnieuw aangeroepen, zodat de koppeling met de speelster klopt."""
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')
    endpoint = str(data.get('endpoint') or '')
    keys = data.get('keys') or {}
    p256dh, auth = str(keys.get('p256dh') or ''), str(keys.get('auth') or '')
    if not endpoint.startswith('https://') or len(endpoint) > 1000 or not (20 < len(p256dh) <= 200) or not (8 < len(auth) <= 100):
        return _fout('Ongeldig meldingen-abonnement.')

    ab, _ = PushAbonnement.objects.get_or_create(endpoint=endpoint, defaults={'p256dh': p256dh, 'auth': auth})
    ab.p256dh, ab.auth = p256dh, auth
    ab.apparaat = request.META.get('HTTP_USER_AGENT', '')[:200]
    speler_id = request.session.get(TrainingPage.SESSIE_SPELER)
    if speler_id:
        ab.speler = Speler.objects.filter(id=speler_id).first()
    if request.user.is_authenticated:
        ab.gebruiker = request.user
    ab.save()
    return JsonResponse({'status': 'success', 'speler': ab.speler.naam if ab.speler else None})


@require_POST
def push_afmelden(request):
    data = _lees_json(request)
    if data is None:
        return _fout('Ongeldige gegevens.')
    PushAbonnement.objects.filter(endpoint=str(data.get('endpoint') or '')).delete()
    return JsonResponse({'status': 'success'})


# ---------------------------------------------------------------------------
# Statistieken bijhouden (wedstrijden aanmaken en acties noteren)
# ---------------------------------------------------------------------------
import re as _re

from .models import StatActie, StatsPage, Wedstrijd
from .stats import kan_stats_bijhouden

CLIENT_ID = _re.compile(r'^[A-Za-z0-9-]{8,40}$')


def _stats_beheer(request, data):
    """Geeft (page, None) als deze gebruiker statistieken mag bijhouden, anders (None, foutmelding)."""
    if data is None:
        return None, _fout('Ongeldige gegevens.')
    try:
        page = Page.objects.live().get(id=int(data.get('page_id'))).specific
    except (Page.DoesNotExist, TypeError, ValueError):
        return None, _fout('Pagina niet gevonden.', status=404)
    if not isinstance(page, StatsPage):
        return None, _fout('Pagina niet gevonden.', status=404)
    if not kan_stats_bijhouden(request.user, page):
        return None, _fout('Je bent niet (meer) ingelogd om statistieken bij te houden.', status=403)
    return page, None


def _stats_wedstrijd(data):
    try:
        return Wedstrijd.objects.get(id=int(data.get('wedstrijd_id') or data.get('id')))
    except (Wedstrijd.DoesNotExist, TypeError, ValueError):
        return None


@require_POST
def wedstrijd_opslaan(request):
    data = _lees_json(request)
    page, fout = _stats_beheer(request, data)
    if fout:
        return fout
    try:
        tegenstander = _tekstveld(data, 'tegenstander', 100, verplicht=True)
        datum = _lees_datum(data.get('datum'))
        if datum is None:
            raise ValueError('Kies een geldige datum.')
    except ValueError as e:
        return _fout(str(e))

    film = str(data.get('film_block_id') or '')
    if film:
        from .stats import archief_films
        if film not in archief_films():
            return _fout('Deze wedstrijdfilm staat niet (meer) in het archief.')
    velden = dict(datum=datum, tegenstander=tegenstander, thuis=bool(data.get('thuis')), film_block_id=film)
    if data.get('id'):
        wedstrijd = _stats_wedstrijd(data)
        if wedstrijd is None:
            return _fout('Deze wedstrijd bestaat niet meer.', status=404)
        for k, v in velden.items():
            setattr(wedstrijd, k, v)
        wedstrijd.save()
    else:
        wedstrijd = Wedstrijd.objects.create(**velden)
    return JsonResponse({'status': 'success', 'id': wedstrijd.id})


@require_POST
def wedstrijd_verwijderen(request):
    data = _lees_json(request)
    page, fout = _stats_beheer(request, data)
    if fout:
        return fout
    wedstrijd = _stats_wedstrijd(data)
    if wedstrijd is None:
        return _fout('Wedstrijd niet gevonden.', status=404)
    wedstrijd.delete()
    return JsonResponse({'status': 'success'})


@require_POST
def stat_actie(request):
    """Noteer één actie. Dezelfde client_id nog een keer sturen telt niet dubbel."""
    data = _lees_json(request)
    page, fout = _stats_beheer(request, data)
    if fout:
        return fout
    wedstrijd = _stats_wedstrijd(data)
    if wedstrijd is None:
        return _fout('Deze wedstrijd bestaat niet meer.', status=404)

    client_id = str(data.get('client_id') or '')
    if not CLIENT_ID.match(client_id):
        return _fout('Ongeldige actie.')
    soort = str(data.get('soort') or '')
    if soort not in dict(StatActie.SOORTEN):
        return _fout('Onbekende actie.')
    kwart = data.get('kwart')
    if kwart not in dict(StatActie.KWARTEN):
        return _fout('Kies een kwart.')

    speler = None
    if soort not in StatActie.TEGENSTANDER:
        try:
            speler = Speler.objects.get(id=int(data.get('speler_id')))
        except (Speler.DoesNotExist, TypeError, ValueError):
            return _fout('Kies eerst een speelster.')

    actie, _nieuw = StatActie.objects.get_or_create(
        client_id=client_id,
        defaults=dict(wedstrijd=wedstrijd, speler=speler, kwart=kwart, soort=soort, door=request.user),
    )
    if actie.wedstrijd_id != wedstrijd.id:
        return _fout('Ongeldige actie.')
    return JsonResponse({'status': 'success', 'id': actie.id, 'client_id': actie.client_id})


@require_POST
def stat_actie_verwijderen(request):
    data = _lees_json(request)
    page, fout = _stats_beheer(request, data)
    if fout:
        return fout
    wedstrijd = _stats_wedstrijd(data)
    if wedstrijd is None:
        return _fout('Deze wedstrijd bestaat niet meer.', status=404)
    # Ook als hij al weg is: dan is het doel bereikt
    StatActie.objects.filter(wedstrijd=wedstrijd, client_id=str(data.get('client_id') or '')).delete()
    return JsonResponse({'status': 'success'})

"""
Pushmeldingen naar telefoons (Web Push).

- Het sleutelpaar wordt bij het eerste gebruik aangemaakt en in de database bewaard,
  dus er hoeft niets bij de hostingpartij ingesteld te worden.
- Versturen gebeurt op de achtergrond, zodat de coach niet hoeft te wachten.
- Telefoons die zich hebben afgemeld of de app hebben verwijderd, worden automatisch opgeruimd.
"""
import base64
import json
import logging
import threading

from django.db import close_old_connections, transaction

logger = logging.getLogger(__name__)

CONTACT = 'mailto:bva-vse2@example.com'  # verplicht in het protocol; wordt alleen bij storingen gebruikt


def _sleutel():
    from .models import PushSleutel
    sleutel = PushSleutel.objects.order_by('id').first()
    if sleutel:
        return sleutel
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02
    v = Vapid02()
    v.generate_keys()
    publiek = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return PushSleutel.objects.create(
        publiek=base64.urlsafe_b64encode(publiek).rstrip(b'=').decode(),
        privaat_pem=v.private_pem().decode(),
    )


def publieke_sleutel():
    try:
        return _sleutel().publiek
    except Exception:  # bijv. tijdens migraties: dan gewoon geen meldingen
        logger.exception('Push-sleutel niet beschikbaar')
        return ''


def _verstuur_naar(abonnement_ids, bericht):
    """Draait op de achtergrond (eigen databaseverbinding)."""
    from py_vapid import Vapid02
    from pywebpush import WebPushException, webpush

    from .models import PushAbonnement

    close_old_connections()
    try:
        vapid = Vapid02.from_pem(_sleutel().privaat_pem.encode())
        data = json.dumps(bericht)
        for ab in PushAbonnement.objects.filter(id__in=abonnement_ids):
            try:
                webpush(ab.als_subscription(), data=data, vapid_private_key=vapid,
                        vapid_claims={'sub': CONTACT}, ttl=24 * 3600, timeout=10)
            except WebPushException as e:
                status = getattr(e.response, 'status_code', None)
                if status in (404, 410):  # telefoon heeft zich afgemeld of app verwijderd
                    ab.delete()
                else:
                    logger.warning('Push mislukt (%s): %s', status, e)
            except Exception:
                logger.exception('Push mislukt')
    finally:
        close_old_connections()


# In tests zetten we dit op False, zodat er synchroon (en zonder echte verzending) wordt getest
OP_ACHTERGROND = True


def stuur(titel, tekst, url='/', spelers=None, tag=None):
    """
    Stuur een melding.
    spelers=None -> iedereen met meldingen aan; anders alleen telefoons van deze speelsters.
    Wordt pas na het opslaan in de database verstuurd (on_commit).
    """
    from .models import PushAbonnement

    qs = PushAbonnement.objects.all()
    if spelers is not None:
        qs = qs.filter(speler__in=list(spelers))
    ids = list(qs.values_list('id', flat=True))
    if not ids:
        return 0
    bericht = {'titel': titel, 'tekst': tekst[:200], 'url': url, 'tag': tag or url}

    def start():
        if OP_ACHTERGROND:
            threading.Thread(target=_verstuur_naar, args=(ids, bericht), daemon=True).start()
        else:
            _verstuur_naar(ids, bericht)

    transaction.on_commit(start)
    return len(ids)

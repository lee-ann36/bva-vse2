"""
Bescherming tegen het raden van wachtwoorden, voor beide inlogschermen:
het inlogvenster op de site (coaches, trainers, statistieken) en de Wagtail-admin (/admin/login/).

- Foute pogingen worden geteld per account én per bezoeker (IP-adres).
- Na te veel foute pogingen is inloggen 15 minuten geblokkeerd, ook met het goede wachtwoord.
- Achter een proxy (Render) is REMOTE_ADDR het adres van de proxy; dan gebruiken we het echte
  adres van de bezoeker uit de headers die de proxy meestuurt (instelling ACHTER_PROXY).
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.dispatch import receiver
from django.http import HttpResponse

MAX_POGINGEN = 10              # foute pogingen per account ...
MAX_POGINGEN_PER_ADRES = 30    # ... of per IP-adres (ruimer: meerdere mensen kunnen één adres delen) ...
BLOKKEER_SECONDEN = 15 * 60    # ... binnen 15 minuten
BLOKKADE_MELDING = 'Te veel foute pogingen. Probeer het over 15 minuten opnieuw.'


def _zonder_accenten(tekst):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD', str(tekst)) if not unicodedata.combining(c)).casefold().strip()


class NaamZonderHoofdletters(ModelBackend):
    """
    Inloggen met je naam, of je nu 'anniko', 'Anniko' of ' ANNIKO ' typt, en 'Zoe' voor 'Zoë'.
    Telefoons maken de eerste letter vaak automatisch een hoofdletter; daardoor lukte inloggen niet.
    Het wachtwoord blijft wel hoofdlettergevoelig.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None
        username = str(username).strip()
        kandidaten = list(User._default_manager.filter(**{f'{User.USERNAME_FIELD}__iexact': username})[:2])
        if not kandidaten:
            # Zonder accenten vergelijken ('Zoe' = 'Zoë'); het team heeft maar een handvol accounts
            kort = _zonder_accenten(username)
            kandidaten = [u for u in User._default_manager.all() if _zonder_accenten(u.get_username()) == kort][:2]
        if len(kandidaten) > 1:  # twee accounts die alleen in hoofdletters verschillen: dan precies
            kandidaten = [u for u in kandidaten if u.get_username() == username]
        if len(kandidaten) != 1:
            User().set_password(password)  # even lang rekenen, zodat je niet kunt zien welke namen bestaan
            return None
        user = kandidaten[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


def client_ip(request):
    if getattr(settings, 'ACHTER_PROXY', False):
        for header in ('HTTP_CF_CONNECTING_IP', 'HTTP_TRUE_CLIENT_IP'):
            if request.META.get(header):
                return request.META[header].strip()[:100]
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded:
            # Het laatste adres is toegevoegd door de proxy zelf en kan dus niet vervalst worden
            return forwarded.split(',')[-1].strip()[:100]
    return request.META.get('REMOTE_ADDR', 'onbekend')


def _sleutels(request, gebruikersnaam):
    sleutels = []
    if request is not None:
        sleutels.append(f'login-pogingen:ip:{client_ip(request)}')
    if gebruikersnaam:
        sleutels.append(f'login-pogingen:naam:{str(gebruikersnaam).strip().lower()[:150]}')
    return sleutels


def is_geblokkeerd(request, gebruikersnaam):
    return any(cache.get(k, 0) >= (MAX_POGINGEN_PER_ADRES if ':ip:' in k else MAX_POGINGEN)
               for k in _sleutels(request, gebruikersnaam))


@receiver(user_login_failed)
def tel_foute_poging(sender, credentials, request=None, **kwargs):
    for k in _sleutels(request, credentials.get('username')):
        try:
            cache.incr(k)
        except ValueError:
            cache.set(k, 1, BLOKKEER_SECONDEN)


@receiver(user_logged_in)
def wis_pogingen(sender, request, user, **kwargs):
    cache.delete_many(_sleutels(request, user.get_username()))


class AdminLoginBlokkade:
    """Weigert inlogpogingen op /admin/login/ zolang het account of de bezoeker geblokkeerd is."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (request.method == 'POST' and request.path.startswith('/admin/login')
                and is_geblokkeerd(request, request.POST.get('username'))):
            return HttpResponse(BLOKKADE_MELDING, status=429, content_type='text/plain; charset=utf-8')
        return self.get_response(request)

"""
Instellingen voor de live site. Alles wat geheim of per server anders is, komt uit
omgevingsvariabelen (in te stellen bij de hostingpartij):

    SECRET_KEY        verplicht: lange willekeurige tekst
    ALLOWED_HOSTS     domeinnaam/-namen, komma-gescheiden (bijv. bva-vse2.fly.dev);
                      op Render hoeft dit niet: het Render-adres wordt automatisch toegevoegd
    DATA_DIR          map op een blijvende schijf voor database + uploads (standaard /data)
    DATABASE_URL      optioneel: online PostgreSQL-database (bijv. Neon). Dan staan alle gegevens
                      én geüploade foto's in die database en is geen blijvende schijf nodig.
"""
import os
from pathlib import Path

from .base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = os.environ['SECRET_KEY']

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]
if os.environ.get('RENDER_EXTERNAL_HOSTNAME'):  # door Render zelf ingesteld, bijv. bva-vse2.onrender.com
    ALLOWED_HOSTS.insert(0, os.environ['RENDER_EXTERNAL_HOSTNAME'])
CSRF_TRUSTED_ORIGINS = [f'https://{h}' for h in ALLOWED_HOSTS if not h.startswith('.')]
if ALLOWED_HOSTS:
    WAGTAILADMIN_BASE_URL = f'https://{ALLOWED_HOSTS[0]}'

# Database en geüploade foto's op een blijvende schijf, zodat ze een update overleven
DATA_DIR = Path(os.environ.get('DATA_DIR', '/data'))
DATABASES['default']['NAME'] = DATA_DIR / 'db.sqlite3'  # noqa: F405
MEDIA_ROOT = DATA_DIR / 'media'

if os.environ.get('DATABASE_URL'):
    import dj_database_url
    DATABASES['default'] = dj_database_url.parse(  # noqa: F405
        os.environ['DATABASE_URL'], conn_max_age=60, conn_health_checks=True, ssl_require=True,
    )
    INSTALLED_APPS.append('django.contrib.postgres')  # noqa: F405  (nodig voor de zoekfunctie van Wagtail)
    # Foto's en documenten ook in de database, want de schijf van een gratis server wordt gewist
    STORAGES['default'] = {'BACKEND': 'home.opslag.DatabaseOpslag'}  # noqa: F405

# CSS/JS serveren via WhiteNoise (gzip + lange cache)
MIDDLEWARE.insert(MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,  # noqa: F405
                  'whitenoise.middleware.WhiteNoiseMiddleware')
STORAGES['staticfiles']['BACKEND'] = 'whitenoise.storage.CompressedManifestStaticFilesStorage'  # noqa: F405

# HTTPS achter de proxy van de hostingpartij
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# Echte IP-adres van bezoekers uit de headers van de proxy halen (voor de inlogblokkade)
ACHTER_PROXY = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
# /up is de health check van de hosting en moet ook via http werken
SECURE_REDIRECT_EXEMPT = [r'^up/$']

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
}

try:
    from .local import *  # noqa: F401,F403
except ImportError:
    pass

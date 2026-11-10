"""
Instellingen voor de live site. Alles wat geheim of per server anders is, komt uit
omgevingsvariabelen (in te stellen bij de hostingpartij):

    SECRET_KEY        verplicht: lange willekeurige tekst
    ALLOWED_HOSTS     verplicht: domeinnaam/-namen, komma-gescheiden (bijv. bva-vse2.fly.dev)
    DATA_DIR          map op een blijvende schijf voor database + uploads (standaard /data)
"""
import os
from pathlib import Path

from .base import *  # noqa: F401,F403

DEBUG = False

SECRET_KEY = os.environ['SECRET_KEY']

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', '').split(',') if h.strip()]
CSRF_TRUSTED_ORIGINS = [f'https://{h}' for h in ALLOWED_HOSTS if not h.startswith('.')]
if ALLOWED_HOSTS:
    WAGTAILADMIN_BASE_URL = f'https://{ALLOWED_HOSTS[0]}'

# Database en geüploade foto's op een blijvende schijf, zodat ze een update overleven
DATA_DIR = Path(os.environ.get('DATA_DIR', '/data'))
DATABASES['default']['NAME'] = DATA_DIR / 'db.sqlite3'  # noqa: F405
MEDIA_ROOT = DATA_DIR / 'media'

# CSS/JS serveren via WhiteNoise (gzip + lange cache)
MIDDLEWARE.insert(MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,  # noqa: F405
                  'whitenoise.middleware.WhiteNoiseMiddleware')
STORAGES['staticfiles']['BACKEND'] = 'whitenoise.storage.CompressedManifestStaticFilesStorage'  # noqa: F405

# HTTPS achter de proxy van de hostingpartij
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
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

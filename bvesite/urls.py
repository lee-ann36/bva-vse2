from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve as serve_media
from wagtail.admin import urls as wagtailadmin_urls
from wagtail import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from home import pwa
from home.opslag import toon_bestand

# Importeer je API views voor de reacties
from home.views import (
    bewerk_reactie,
    coach_inloggen,
    coach_uitloggen,
    film_toevoegen,
    film_verwijderen,
    push_aanmelden,
    push_afmelden,
    mededeling_opslaan,
    mededeling_verwijderen,
    speler_opslaan,
    staf_opslaan,
    staf_verwijderen,
    teaminfo_opslaan,
    opdracht_afvinken,
    opdracht_toevoegen,
    opdracht_verwijderen,
    sla_reactie_op,
    speler_kiezen,
    speler_wisselen,
    stat_actie,
    stat_actie_verwijderen,
    verwijder_reactie,
    wedstrijd_opslaan,
    wedstrijd_verwijderen,
)

urlpatterns = [
    # 1. Wagtail Admin URL's
    path('admin/', include(wagtailadmin_urls)),
    path('documents/', include(wagtaildocs_urls)),

    # 2. Jouw eigen API route voor de reacties
    path('api/sla-reactie/', sla_reactie_op, name='sla_reactie_op'),
    path('api/bewerk-reactie/', bewerk_reactie, name='bewerk_reactie'),
    path('api/verwijder-reactie/', verwijder_reactie, name='verwijder_reactie'),
    path('api/film-toevoegen/', film_toevoegen, name='film_toevoegen'),
    path('api/film-verwijderen/', film_verwijderen, name='film_verwijderen'),
    path('api/push/aanmelden/', push_aanmelden, name='push_aanmelden'),
    path('api/push/afmelden/', push_afmelden, name='push_afmelden'),
    path('api/mededeling-opslaan/', mededeling_opslaan, name='mededeling_opslaan'),
    path('api/mededeling-verwijderen/', mededeling_verwijderen, name='mededeling_verwijderen'),
    path('api/team/speler-opslaan/', speler_opslaan, name='speler_opslaan'),
    path('api/team/staf-opslaan/', staf_opslaan, name='staf_opslaan'),
    path('api/team/staf-verwijderen/', staf_verwijderen, name='staf_verwijderen'),
    path('api/team/info-opslaan/', teaminfo_opslaan, name='teaminfo_opslaan'),
    path('api/coach-inloggen/', coach_inloggen, name='coach_inloggen'),
    path('api/coach-uitloggen/', coach_uitloggen, name='coach_uitloggen'),

    # Training
    path('api/training/speler-kiezen/', speler_kiezen, name='speler_kiezen'),
    path('api/training/speler-wisselen/', speler_wisselen, name='speler_wisselen'),
    path('api/training/afvinken/', opdracht_afvinken, name='opdracht_afvinken'),
    path('api/training/opdracht-toevoegen/', opdracht_toevoegen, name='opdracht_toevoegen'),
    path('api/training/opdracht-verwijderen/', opdracht_verwijderen, name='opdracht_verwijderen'),

    # Statistieken
    path('api/stats/wedstrijd-opslaan/', wedstrijd_opslaan, name='wedstrijd_opslaan'),
    path('api/stats/wedstrijd-verwijderen/', wedstrijd_verwijderen, name='wedstrijd_verwijderen'),
    path('api/stats/actie/', stat_actie, name='stat_actie'),
    path('api/stats/actie-verwijderen/', stat_actie_verwijderen, name='stat_actie_verwijderen'),

    # Als app op je telefoon
    path('manifest.webmanifest', pwa.manifest, name='manifest'),
    path('sw.js', pwa.service_worker, name='service_worker'),
    path('offline/', pwa.offline, name='offline'),

    # Health check voor de hostingpartij
    path('up/', lambda request: HttpResponse('ok', content_type='text/plain'), name='up'),

    # Geüploade foto's (klein team, dus Django mag ze zelf serveren; uit de database als ze daar staan)
    re_path(r'^media/(?P<path>.*)$', toon_bestand)
    if settings.STORAGES['default']['BACKEND'] == 'home.opslag.DatabaseOpslag'
    else re_path(r'^media/(?P<path>.*)$', serve_media, {'document_root': settings.MEDIA_ROOT}),

    # 3. Wagtail pagina's (deze moet onderaan staan)
    path('', include(wagtail_urls)),
]

if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns = staticfiles_urlpatterns() + urlpatterns
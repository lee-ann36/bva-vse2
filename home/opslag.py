"""
Geüploade bestanden (foto's, documenten) in de database bewaren in plaats van op de schijf.

Op een gratis server (zoals Render free) wordt de schijf bij elke herstart gewist. Met deze
opslag staan foto's gewoon in dezelfde database als de rest, dus ze blijven bewaard.
Wordt alleen gebruikt als DATABASE_URL is ingesteld (zie settings/production.py).
"""
from urllib.parse import quote

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.http import Http404, HttpResponse
from django.utils.deconstruct import deconstructible
from django.utils.http import http_date


@deconstructible
class DatabaseOpslag(Storage):
    def _bestand(self, name):
        from .models import Bestand
        return Bestand.objects.filter(naam=name).first()

    def _open(self, name, mode='rb'):
        bestand = self._bestand(name)
        if bestand is None:
            raise FileNotFoundError(name)
        return ContentFile(bytes(bestand.inhoud), name=name)

    def _save(self, name, content):
        from .models import Bestand
        if hasattr(content, 'seek'):
            content.seek(0)
        data = content.read()
        if isinstance(data, str):
            data = data.encode('utf-8')
        Bestand.objects.update_or_create(naam=name, defaults={'inhoud': data, 'grootte': len(data)})
        return name

    def exists(self, name):
        from .models import Bestand
        return Bestand.objects.filter(naam=name).exists()

    def delete(self, name):
        from .models import Bestand
        Bestand.objects.filter(naam=name).delete()

    def size(self, name):
        bestand = self._bestand(name)
        if bestand is None:
            raise FileNotFoundError(name)
        return bestand.grootte

    def url(self, name):
        return settings.MEDIA_URL + quote(str(name).replace('\\', '/'))

    def get_modified_time(self, name):
        bestand = self._bestand(name)
        if bestand is None:
            raise FileNotFoundError(name)
        return bestand.gewijzigd

    get_created_time = get_modified_time
    get_accessed_time = get_modified_time

    def path(self, name):
        raise NotImplementedError('Bestanden staan in de database, niet op de schijf.')


def toon_bestand(request, path):
    """Serveert een bestand uit de database onder /media/..."""
    import mimetypes

    from .models import Bestand
    bestand = Bestand.objects.filter(naam=path).first()
    if bestand is None:
        raise Http404('Bestand niet gevonden')
    soort = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    response = HttpResponse(bytes(bestand.inhoud), content_type=soort)
    response['Content-Length'] = str(bestand.grootte)
    response['Last-Modified'] = http_date(bestand.gewijzigd.timestamp())
    response['Cache-Control'] = 'public, max-age=86400'
    if soort not in ('image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/avif', 'application/pdf'):
        response['Content-Disposition'] = 'attachment'
    return response


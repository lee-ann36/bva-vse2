from . import push


def pushmeldingen(request):
    """Publieke sleutel voor pushmeldingen, voor de <meta name="push-sleutel"> in de pagina's."""
    return {'push_publieke_sleutel': push.publieke_sleutel()}

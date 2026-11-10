"""
Herstelt de homepage op een nieuwe (lege) database.

Migratie 0009 heeft de tabel van HomePage ooit verwijderd en 0010 maakte hem leeg opnieuw aan.
Op een nieuwe database blijft de homepage uit 0002 daardoor achter zonder eigen gegevens,
en geeft de site een serverfout. Hier vullen we die ontbrekende regel aan.
Op een database waar alles al klopt, doet deze migratie niets.
"""
from django.db import migrations


def herstel(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Page = apps.get_model('wagtailcore', 'Page')
    HomePage = apps.get_model('home', 'HomePage')

    ct = ContentType.objects.filter(app_label='home', model='homepage').first()
    if ct is None:
        return
    bestaand = set(HomePage.objects.values_list('page_ptr_id', flat=True))
    for page_id in Page.objects.filter(content_type=ct).values_list('id', flat=True):
        if page_id in bestaand:
            continue
        # raw=True: alleen de HomePage-tabel invullen, de bestaande pagina zelf blijft ongemoeid
        HomePage(page_ptr_id=page_id, koptekst='BVA VSE-2', subtekst='', seizoen="'24/'25", ical_url='').save_base(raw=True)


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0024_wedstrijd_film'),
    ]

    operations = [
        migrations.RunPython(herstel, migrations.RunPython.noop),
    ]

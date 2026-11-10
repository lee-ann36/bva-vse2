from django.db import migrations, models


def index_naar_block_id(apps, schema_editor):
    """Zet bestaande reacties om van 'plek in de lijst' naar het vaste id van de wedstrijd/play."""
    WedstrijdReactie = apps.get_model('home', 'WedstrijdReactie')
    bronnen = [
        (apps.get_model('home', 'WedstrijdenArchiefPage'), 'wedstrijden'),
        (apps.get_model('home', 'PlaysPage'), 'plays'),
    ]
    cache = {}
    for reactie in WedstrijdReactie.objects.all():
        if reactie.page_id not in cache:
            ids = []
            for model, veld in bronnen:
                page = model.objects.filter(page_ptr_id=reactie.page_id).first()
                if page is not None:
                    ids = [blok.get('id') for blok in getattr(page, veld).raw_data]
                    break
            cache[reactie.page_id] = ids
        ids = cache[reactie.page_id]
        if 0 <= reactie.match_index < len(ids) and ids[reactie.match_index]:
            reactie.block_id = ids[reactie.match_index]
            reactie.save(update_fields=['block_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0018_opdracht_begin_eind'),
    ]

    operations = [
        migrations.AddField(
            model_name='wedstrijdreactie',
            name='block_id',
            field=models.CharField(db_index=True, default='', help_text='Id van de wedstrijd of play op de pagina',
                                   max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(index_naar_block_id, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='wedstrijdreactie',
            name='match_index',
        ),
    ]

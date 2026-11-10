from datetime import timedelta

from django.db import migrations, models


def vul_einddatum(apps, schema_editor):
    """Oude opdrachten: 'week' werd begindatum, 'tot en met' (een maandag) wordt een echte einddatum."""
    Opdracht = apps.get_model('home', 'Opdracht')
    for o in Opdracht.objects.all():
        if o.eind:
            o.eind = o.eind + timedelta(days=6)        # laatste maandag -> zondag van die week
        elif o.herhalend:
            o.eind = o.begin + timedelta(weeks=52)     # was doorlopend: een jaar
        else:
            o.eind = o.begin + timedelta(days=6)       # was één week
        o.save(update_fields=['eind'])


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0017_opdracht_voor_spelers'),
    ]

    operations = [
        migrations.RenameField('opdracht', 'week', 'begin'),
        migrations.RenameField('opdracht', 'tot_en_met', 'eind'),
        migrations.RunPython(vul_einddatum, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='opdracht',
            name='begin',
            field=models.DateField(help_text='Vanaf deze dag staat de opdracht klaar.', verbose_name='begindatum'),
        ),
        migrations.AlterField(
            model_name='opdracht',
            name='eind',
            field=models.DateField(
                help_text='Tot en met deze dag. Bij een eenmalige opdracht is dit de deadline.',
                verbose_name='einddatum',
            ),
        ),
        migrations.AlterField(
            model_name='opdracht',
            name='herhalend',
            field=models.BooleanField(
                default=False,
                help_text='Aan: elke week in deze periode opnieuw afvinken. Uit: één keer afvinken vóór de einddatum.',
                verbose_name='elke week opnieuw',
            ),
        ),
    ]

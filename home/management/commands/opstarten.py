"""
Maakt een (lege) database meteen bruikbaar. Draait bij elke start van de server en
is veilig om vaker te draaien: wat er al is, blijft zoals het is.

- Alle vaste pagina's onder de homepage (Wedstrijden, Plays, Programma, Training, Ons team).
- De groepen Coaches, Trainers en Statistieken met hun rechten.
- Accounts uit omgevingsvariabelen (handig op een gratis server waar de database steeds leeg begint):
    ADMIN_GEBRUIKER / ADMIN_WACHTWOORD      beheerder (alles)
    STATS_GEBRUIKER / STATS_WACHTWOORD      iemand die statistieken bijhoudt (bijv. Zoë)
- ICAL_URL: agenda van het team (alleen als de homepage er nog geen heeft).

Gebruik:
    python manage.py opstarten
"""
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import BaseCommand
from wagtail.models import GroupPagePermission

from home.models import (
    HomePage,
    PlaysPage,
    ProgrammaPage,
    StatsPage,
    TeamPage,
    TrainingPage,
    WedstrijdenArchiefPage,
)

PAGINAS = [
    (WedstrijdenArchiefPage, 'Wedstrijden', 'wedstrijden'),
    (PlaysPage, 'Plays', 'plays'),
    (ProgrammaPage, 'Programma', 'programma'),
    (TrainingPage, 'Training', 'training'),
    (TeamPage, 'Ons team', 'team'),
    (StatsPage, 'Statistieken', 'statistieken'),
]

STANDAARD_ICAL = 'https://api.foys.io/competition/public-api/v1/teams/a88d961d-95f7-412f-8ad9-d92c54823f96/ics'


class Command(BaseCommand):
    help = 'Maakt pagina\'s, groepen en accounts aan als ze nog niet bestaan.'

    def handle(self, *args, **options):
        home = HomePage.objects.order_by('path').first()
        if home is None:
            self.stdout.write(self.style.WARNING('Geen homepage gevonden; pagina\'s overgeslagen.'))
        else:
            gewijzigd = False
            if not home.koptekst:
                home.koptekst = 'BVA VSE-2'
                gewijzigd = True
            if not home.ical_url:
                home.ical_url = os.environ.get('ICAL_URL', STANDAARD_ICAL)
                gewijzigd = True
            if gewijzigd:
                home.save_revision().publish()

            for model, titel, slug in PAGINAS:
                if model.objects.exists() or home.get_children().filter(slug=slug).exists():
                    continue
                pagina = model(title=titel, slug=slug)
                home.add_child(instance=pagina)
                pagina.save_revision().publish()
                self.stdout.write(f'Pagina aangemaakt: {titel}')

        # Groepen en rechten (de bestaande commando's zijn veilig om opnieuw te draaien)
        call_command('coach_rechten', stdout=open(os.devnull, 'w'))
        call_command('trainer_rechten', stdout=open(os.devnull, 'w'))
        stats_groep, _ = Group.objects.get_or_create(name='Statistieken')
        page_perms = Permission.objects.filter(content_type__app_label='wagtailcore', codename__in=['change_page', 'publish_page'])
        for pagina in StatsPage.objects.all():
            for perm in page_perms:
                GroupPagePermission.objects.get_or_create(group=stats_groep, page=pagina, permission=perm)

        User = get_user_model()
        naam, wachtwoord = os.environ.get('ADMIN_GEBRUIKER'), os.environ.get('ADMIN_WACHTWOORD')
        if naam and wachtwoord and not User.objects.filter(username=naam).exists():
            User.objects.create_superuser(naam, '', wachtwoord)
            self.stdout.write(f'Beheerder aangemaakt: {naam}')

        naam, wachtwoord = os.environ.get('STATS_GEBRUIKER'), os.environ.get('STATS_WACHTWOORD')
        if naam and wachtwoord and not User.objects.filter(username=naam).exists():
            user = User.objects.create_user(naam, '', wachtwoord)
            user.groups.add(stats_groep)
            self.stdout.write(f'Statistieken-account aangemaakt: {naam}')

        self.stdout.write(self.style.SUCCESS('Klaar om te gebruiken.'))

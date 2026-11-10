"""
Maakt (of herstelt) de groep "Trainers".

Trainers mogen inloggen, opdrachten toevoegen/bewerken/verwijderen (ook via de admin)
en de trainingspagina publiceren. Andere pagina's mogen ze niet aanpassen.

Gebruik:
    python manage.py trainer_rechten
    python manage.py trainer_rechten --gebruiker eva --gebruiker anniko
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from wagtail.models import GroupPagePermission

from home.models import TrainingPage

GROEP = 'Trainers'


class Command(BaseCommand):
    help = 'Maakt de groep "Trainers" met rechten op de trainingspagina en trainingsopdrachten.'

    def add_arguments(self, parser):
        parser.add_argument('--gebruiker', action='append', default=[],
                            help='Gebruikersnaam om aan de groep toe te voegen (mag vaker)')

    def handle(self, *args, **options):
        groep, nieuw = Group.objects.get_or_create(name=GROEP)
        groep.permissions.add(Permission.objects.get(content_type__app_label='wagtailadmin', codename='access_admin'))
        for code in ('add_mededeling', 'change_mededeling', 'delete_mededeling', 'add_speler', 'change_speler'):
            groep.permissions.add(Permission.objects.get(content_type__app_label='home', codename=code))
        for code in ('add_opdracht', 'change_opdracht', 'delete_opdracht'):
            groep.permissions.add(Permission.objects.get(content_type__app_label='home', codename=code))

        page_perms = [
            Permission.objects.get(content_type__app_label='wagtailcore', codename=code)
            for code in ('change_page', 'publish_page')
        ]
        paginas = list(TrainingPage.objects.all())
        if not paginas:
            self.stdout.write(self.style.WARNING('Geen trainingspagina gevonden.'))
        for page in paginas:
            for perm in page_perms:
                GroupPagePermission.objects.get_or_create(group=groep, page=page, permission=perm)
            self.stdout.write(f'  rechten op: {page.title} ({page.url})')

        self.stdout.write(self.style.SUCCESS(f'Groep "{GROEP}" {"aangemaakt" if nieuw else "bijgewerkt"}.'))

        for naam in options['gebruiker']:
            try:
                user = get_user_model().objects.get(username=naam)
            except get_user_model().DoesNotExist:
                raise CommandError(f'Gebruiker "{naam}" bestaat niet.')
            user.groups.add(groep)
            self.stdout.write(self.style.SUCCESS(f'{user.username} zit nu in de groep {GROEP}.'))

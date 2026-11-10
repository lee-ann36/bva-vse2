"""
Maakt (of herstelt) de groep "Coaches".

Coaches mogen inloggen in de admin en het wedstrijdarchief en de plays-pagina
bewerken en publiceren. Andere pagina's mogen ze niet aanpassen.

Gebruik:
    python manage.py coach_rechten
    python manage.py coach_rechten --gebruiker jan      # voeg bestaande gebruiker toe aan de groep
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from wagtail.models import GroupPagePermission

from home.models import PlaysPage, TeamPage, WedstrijdenArchiefPage

GROEP = 'Coaches'


class Command(BaseCommand):
    help = 'Maakt de groep "Coaches" met rechten op het wedstrijdarchief en de plays-pagina.'

    def add_arguments(self, parser):
        parser.add_argument('--gebruiker', help='Gebruikersnaam om aan de groep Coaches toe te voegen')

    def handle(self, *args, **options):
        groep, nieuw = Group.objects.get_or_create(name=GROEP)
        groep.permissions.add(Permission.objects.get(content_type__app_label='wagtailadmin', codename='access_admin'))
        for code in ('add_mededeling', 'change_mededeling', 'delete_mededeling', 'add_speler', 'change_speler'):
            groep.permissions.add(Permission.objects.get(content_type__app_label='home', codename=code))

        page_perms = [
            Permission.objects.get(content_type__app_label='wagtailcore', codename=code)
            for code in ('change_page', 'publish_page')
        ]
        paginas = (list(WedstrijdenArchiefPage.objects.all()) + list(PlaysPage.objects.all())
                   + list(TeamPage.objects.all()))
        if not paginas:
            self.stdout.write(self.style.WARNING('Geen wedstrijdarchief- of plays-pagina gevonden.'))
        for page in paginas:
            for perm in page_perms:
                GroupPagePermission.objects.get_or_create(group=groep, page=page, permission=perm)
            self.stdout.write(f'  rechten op: {page.title} ({page.url})')

        self.stdout.write(self.style.SUCCESS(f'Groep "{GROEP}" {"aangemaakt" if nieuw else "bijgewerkt"}.'))

        if options['gebruiker']:
            try:
                user = get_user_model().objects.get(username=options['gebruiker'])
            except get_user_model().DoesNotExist:
                raise CommandError(f'Gebruiker "{options["gebruiker"]}" bestaat niet.')
            user.groups.add(groep)
            self.stdout.write(self.style.SUCCESS(f'{user.username} zit nu in de groep {GROEP}.'))

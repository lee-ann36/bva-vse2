"""
Maakt (of herstelt) de groep "Trainers".

Trainers mogen alleen trainingsopdrachten beheren (toevoegen, bewerken, verwijderen) op de
trainingspagina. Geen films, plays, mededelingen, speelsters of reacties van anderen, en geen
toegang tot de Wagtail-admin. De rechten worden elke keer precies zo gezet: wat er ooit extra bij
is gekomen, wordt weer weggehaald.

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
        groep.permissions.set(Permission.objects.filter(
            content_type__app_label='home', codename__in=['add_opdracht', 'change_opdracht', 'delete_opdracht']))

        page_perms = [
            Permission.objects.get(content_type__app_label='wagtailcore', codename=code)
            for code in ('change_page', 'publish_page')
        ]
        paginas = list(TrainingPage.objects.all())
        # Alleen rechten op de trainingspagina; rechten op andere pagina's weghalen
        GroupPagePermission.objects.filter(group=groep).exclude(page__in=paginas).delete()
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

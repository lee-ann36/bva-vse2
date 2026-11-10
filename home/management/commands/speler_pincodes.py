"""
Geeft actieve spelers zonder pincode een willekeurige pincode van 4 cijfers en toont ze één keer.
De pincodes worden versleuteld opgeslagen; daarna zijn ze niet meer terug te lezen.

Gebruik:
    python manage.py speler_pincodes            # alleen spelers zonder pincode
    python manage.py speler_pincodes --alle     # iedereen een nieuwe pincode
    python manage.py speler_pincodes --speler Eva
"""
import secrets

from django.core.management.base import BaseCommand, CommandError

from home.models import Speler


class Command(BaseCommand):
    help = 'Maakt pincodes voor spelers en toont ze één keer.'

    def add_arguments(self, parser):
        parser.add_argument('--alle', action='store_true', help='Ook spelers die al een pincode hebben')
        parser.add_argument('--speler', help='Alleen deze speler (naam)')

    def handle(self, *args, **options):
        spelers = Speler.objects.filter(actief=True)
        if options['speler']:
            spelers = spelers.filter(naam__iexact=options['speler'])
            if not spelers:
                raise CommandError(f'Speler "{options["speler"]}" niet gevonden.')
        elif not options['alle']:
            spelers = spelers.filter(pincode_hash='')

        if not spelers:
            self.stdout.write('Alle spelers hebben al een pincode.')
            return

        self.stdout.write('Naam            Pincode')
        self.stdout.write('-----------------------')
        for speler in spelers:
            pin = f'{secrets.randbelow(10000):04d}'
            speler.set_pincode(pin)
            speler.save(update_fields=['pincode_hash'])
            self.stdout.write(f'{speler.naam:<15} {pin}')
        self.stdout.write(self.style.WARNING('Bewaar deze lijst goed: de pincodes zijn hierna niet meer terug te lezen.'))

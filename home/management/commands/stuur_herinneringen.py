"""
Stuurt speelsters een herinnering voor opdrachten die ze nog niet hebben afgevinkt.
Laat de hostingpartij dit elke dag één keer draaien (bijv. om 18:00):

    python manage.py stuur_herinneringen

- Eenmalige opdracht: de dag vóór de deadline.
- Herhalende opdracht: op zaterdag, voor de opdrachten van die week.
Alleen speelsters die met hun pincode zijn ingelogd op een telefoon met meldingen aan,
krijgen een herinnering (anders weten we niet wie wie is).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from home import push
from home.models import Afvinking, Opdracht, Speler, TrainingPage, week_start

ZATERDAG = 5


class Command(BaseCommand):
    help = 'Stuurt herinneringen voor openstaande trainingsopdrachten.'

    def add_arguments(self, parser):
        parser.add_argument('--datum', help='Doen alsof het deze datum is (JJJJ-MM-DD), om te testen')
        parser.add_argument('--droog', action='store_true', help='Alleen laten zien wat er verstuurd zou worden')

    def handle(self, *args, **options):
        # Direct versturen: een achtergrond-thread zou stoppen zodra dit commando klaar is
        push.OP_ACHTERGROND = False
        vandaag = timezone.localdate()
        if options['datum']:
            from datetime import date
            vandaag = date.fromisoformat(options['datum'])
        morgen = vandaag + timedelta(days=1)
        maandag = week_start(vandaag)

        te_checken = list(Opdracht.objects.filter(herhalend=False, eind=morgen).prefetch_related('voor_spelers'))
        if vandaag.weekday() == ZATERDAG:
            te_checken += [o for o in Opdracht.voor_week(maandag) if o.herhalend]

        spelers = list(Speler.objects.filter(actief=True, push_abonnementen__isnull=False).distinct())
        if not te_checken or not spelers:
            self.stdout.write('Geen herinneringen nodig.')
            return

        gedaan = set(Afvinking.objects.filter(opdracht__in=te_checken, speler__in=spelers)
                     .values_list('speler_id', 'opdracht_id', 'week'))
        training = TrainingPage.objects.live().first()
        url = f'{training.url}?week={maandag.isoformat()}' if training else '/'

        verstuurd = 0
        for speler in spelers:
            open_ = [o for o in te_checken
                     if o.geldt_voor(speler) and (speler.id, o.id, o.afvink_week(maandag)) not in gedaan]
            if not open_:
                continue
            titel = '⏰ Nog 1 opdracht open' if len(open_) == 1 else f'⏰ Nog {len(open_)} opdrachten open'
            tekst = ', '.join(o.titel for o in open_[:3]) + (' …' if len(open_) > 3 else '')
            if any(not o.herhalend for o in open_):
                tekst += ' · deadline morgen'
            # Zonder emoji in de console-uitvoer (Windows-consoles kunnen die niet altijd tonen)
            self.stdout.write(f'{speler.naam}: {len(open_)} open - ' + ', '.join(o.titel for o in open_))
            if not options['droog']:
                push.stuur(titel, tekst, url=url, spelers=[speler], tag=f'herinnering-{vandaag}')
                verstuurd += 1
        self.stdout.write(self.style.SUCCESS(f'{verstuurd} herinnering(en) verstuurd.'))

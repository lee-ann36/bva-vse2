from datetime import datetime, time, timedelta
from django import forms
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.db.models import Q
from django.utils import timezone
from icalendar import Calendar
import requests
from wagtail.admin.forms import WagtailAdminModelForm
from wagtail.admin.panels import FieldPanel, FieldRowPanel, HelpPanel
from wagtail.fields import RichTextField, StreamField
from wagtail.blocks import StructBlock, CharBlock, TextBlock, URLBlock, StructValue
from wagtail.models import Page
from wagtail.embeds.blocks import EmbedBlock
from urllib.parse import urlparse, parse_qs
from wagtail import blocks


class SpelerForm(WagtailAdminModelForm):
    """Admin-formulier voor spelers met een extra veld om de pincode (opnieuw) in te stellen."""
    nieuwe_pincode = forms.CharField(
        required=False,
        min_length=4,
        max_length=4,
        label='Nieuwe pincode',
        help_text='4 cijfers, nodig om trainingsopdrachten af te vinken. Laat leeg om de huidige pincode te houden.',
    )

    def clean_nieuwe_pincode(self):
        pin = self.cleaned_data.get('nieuwe_pincode', '').strip()
        if pin and not pin.isdigit():
            raise forms.ValidationError('De pincode mag alleen uit cijfers bestaan.')
        return pin

    def save(self, commit=True):
        speler = super().save(commit=False)
        if self.cleaned_data.get('nieuwe_pincode'):
            speler.set_pincode(self.cleaned_data['nieuwe_pincode'])
        if commit:
            speler.save()
        return speler


class Speler(models.Model):
    """Vaste speler van het team. Te beheren in de admin onder 'Spelers'."""
    base_form_class = SpelerForm

    POSITIES = [
        ('PG', 'Point guard (1)'),
        ('SG', 'Shooting guard (2)'),
        ('SF', 'Small forward (3)'),
        ('PF', 'Power forward (4)'),
        ('C', 'Center (5)'),
    ]

    naam = models.CharField(max_length=100)
    rugnummer = models.PositiveSmallIntegerField(null=True, blank=True)
    positie = models.CharField(max_length=2, choices=POSITIES, blank=True)
    foto = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    actief = models.BooleanField(
        default=True,
        help_text='Zet uit voor spelers die (tijdelijk) niet in de selectie zitten. Zij tellen dan niet mee.',
    )
    # Gehashte pincode (zoals een wachtwoord), om trainingsopdrachten af te vinken
    pincode_hash = models.CharField(max_length=128, blank=True, editable=False)

    panels = [
        FieldPanel('naam'),
        FieldRowPanel([FieldPanel('rugnummer'), FieldPanel('positie')]),
        FieldPanel('foto'),
        FieldPanel('actief'),
        FieldPanel('nieuwe_pincode'),
    ]

    def set_pincode(self, pincode):
        self.pincode_hash = make_password(pincode)

    def check_pincode(self, pincode):
        return bool(self.pincode_hash) and check_password(pincode, self.pincode_hash)

    @property
    def heeft_pincode(self):
        return bool(self.pincode_hash)

    class Meta:
        ordering = ['rugnummer', 'naam']
        verbose_name = 'speler'
        verbose_name_plural = 'spelers'

    def __str__(self):
        return f"#{self.rugnummer} {self.naam}" if self.rugnummer is not None else self.naam


class HomePage(Page):
    koptekst = models.CharField(max_length=255, default='')
    subtekst = RichTextField(blank=True, help_text='')
    seizoen = models.CharField(max_length=20, default="'24/'25")
    achtergrond_foto = models.ForeignKey(
        'wagtailimages.Image',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )

    ical_url = models.URLField(
        blank=True, help_text='https://api.foys.io/competition/public-api/v1/teams/a88d961d-95f7-412f-8ad9-d92c54823f96/ics'
    )

    content_panels = Page.content_panels + [
        FieldPanel('koptekst'),
        FieldPanel('subtekst'),
        HelpPanel(
            content='<p><strong>Aantal spelers</strong> wordt automatisch geteld. '
                    'Voeg spelers toe of bewerk ze via <a href="/admin/snippets/home/speler/">Spelers</a> '
                    'in het menu links.</p>',
            heading='Spelers',
        ),
        FieldPanel('seizoen'),
        FieldPanel('achtergrond_foto'),
        FieldPanel('ical_url'),
    ]

    def get_context(self, request):
        context = super().get_context(request)
        context['spelers'] = Speler.objects.filter(actief=True)
        context['aantal_spelers'] = context['spelers'].count()

        training_page = TrainingPage.objects.live().first()
        context['training_url'] = training_page.url if training_page else '#'
        team_page = TeamPage.objects.live().first()
        context['team_url'] = team_page.url if team_page else '#'
        context['mededelingen'] = list(Mededeling.actueel()[:5])
        context['kan_mededeling_plaatsen'] = request.user.has_perm('home.add_mededeling')
        if context['kan_mededeling_plaatsen']:
            # Beheerders zien ook verlopen/toekomstige mededelingen, zodat ze die kunnen aanpassen
            context['mededelingen'] = list(Mededeling.objects.select_related('aangemaakt_door')[:20])
            context['mededelingen_data'] = {
                str(m.id): {
                    'titel': m.titel, 'tekst': m.tekst, 'belangrijk': m.belangrijk,
                    'zichtbaar_vanaf': m.zichtbaar_vanaf.isoformat() if m.zichtbaar_vanaf else '',
                    'zichtbaar_tot': m.zichtbaar_tot.isoformat() if m.zichtbaar_tot else '',
                }
                for m in context['mededelingen']
            }
        context['vandaag'] = timezone.localdate()
        training = week_overzicht(week_start(timezone.localdate()))
        context['training_aantal'] = len(training['opdrachten'])
        context['training_team_pct'] = training['team_pct']

        programma_page = ProgrammaPage.objects.live().first()
        context['programma_url'] = programma_page.url if programma_page else '#'

        archief_page = WedstrijdenArchiefPage.objects.live().first()
        context['archief_url'] = archief_page.url if archief_page else '#'

        # Laatst geüploade wedstrijd uit het archief voor het blok "Laatste Wedstrijd"
        match_index, match_block = laatste_wedstrijd(archief_page)
        context['laatste_wedstrijd'] = match_block.value if match_block else None
        context['laatste_wedstrijd_url'] = (
            f"{archief_page.url}?wedstrijd={match_index}" if match_block else context['archief_url']
        )
        context['laatste_wedstrijd_reacties'] = (
            WedstrijdReactie.objects.filter(page=archief_page, block_id=match_block.id).count()
            if match_block else 0
        )

        plays_page = PlaysPage.objects.live().first()
        context['plays_url'] = plays_page.url if plays_page else '#'
        context['aantal_plays'] = len(plays_page.plays) if plays_page else 0

        from .stats import homepage_stats
        context.update(homepage_stats(request))

        nu = datetime.now().date()
        context['aankomende_games'] = [g for g in ical_wedstrijden(self.ical_url) if g['datum'].date() >= nu][:3]
        return context


class ProgrammaPage(Page):
    intro = RichTextField(blank=True, help_text="Introductietekst boven het programma")

    content_panels = Page.content_panels + [
        FieldPanel('intro'),
    ]

    def get_context(self, request):
        context = super().get_context(request)
        nu = datetime.now().date()
        context['alle_games'] = [g for g in ical_wedstrijden() if g['datum'].date() >= nu]
        return context


def _is_ons(team):
    """Is dit teamnaam-deel ons team? ('BV Amsterdam VSE-2', 'BVA VSE-2'; niet 'Utrecht Bull's VSE-2')."""
    team = team.strip().lower()
    return 'vse-2' in team and ('amsterdam' in team or team.startswith('bva'))


def _is_thuis(titel, locatie):
    """Thuis als we in onze eigen hal spelen of als eerste team in de titel staan."""
    if 'hogendorpstraat' in locatie.lower():
        return True
    return _is_ons(str(titel or '').split(' - ')[0])


def tegenstander_uit_titel(titel):
    """'BV Amsterdam VSE-2 - BC Leiden' -> 'BC Leiden' (de kant die niet ons team is)."""
    delen = [d.strip().rstrip('*').strip() for d in str(titel or '').split(' - ') if d.strip()]
    anderen = [d for d in delen if not _is_ons(d)]
    return (anderen[0] if anderen else str(titel or '').strip())[:100]


def ical_wedstrijden(url=None, timeout=10):
    """Alle wedstrijden uit de iCal-agenda (standaard die van de homepage), gesorteerd op datum. Lege lijst bij een fout."""
    games = []
    if url is None:
        home_page = HomePage.objects.live().first()
        url = home_page.ical_url if home_page else ''
    if not url:
        return games
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return games
        cal = Calendar.from_ical(response.content)
        for component in cal.walk('vevent'):
            titel = str(component.get('summary', ''))
            start_dt = component.get('dtstart')
            locatie = str(component.get('location', 'Sporthal'))
            if not start_dt:
                continue
            dt_val = start_dt.dt
            game_datum = dt_val if isinstance(dt_val, datetime) else datetime.combine(dt_val, time(0, 0))
            games.append({
                'titel': titel,
                'datum': game_datum,
                'locatie': locatie,
                'thuis_uit': 'THUIS' if _is_thuis(titel, locatie) else 'UIT',
            })
    except Exception as e:
        print('Fout bij ophalen iCal:', e)
        return []
    return sorted(games, key=lambda x: x['datum'])


def youtube_embed_url(url):
    """Zet een YouTube link (watch, youtu.be, embed, shorts) om naar een embed URL."""
    url = str(url or '').strip()
    if not url:
        return ''
    parsed_url = urlparse(url)
    video_id = None

    if parsed_url.netloc in ('youtu.be', 'www.youtu.be'):
        video_id = parsed_url.path.lstrip('/')
    elif parsed_url.netloc in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        if parsed_url.path == '/watch':
            query_params = parse_qs(parsed_url.query)
            video_id = query_params.get('v', [None])[0]
        elif parsed_url.path.startswith('/embed/'):
            video_id = parsed_url.path.split('/')[2]
        elif parsed_url.path.startswith('/shorts/'):
            video_id = parsed_url.path.split('/')[2]

    if not video_id:
        return ''
    video_id = video_id.split('?')[0].split('&')[0]
    return f"https://www.youtube-nocookie.com/embed/{video_id}"


NL_MAANDEN = {
    'januari': 1, 'februari': 2, 'maart': 3, 'april': 4, 'mei': 5, 'juni': 6,
    'juli': 7, 'augustus': 8, 'september': 9, 'oktober': 10, 'november': 11, 'december': 12,
    'jan': 1, 'feb': 2, 'mrt': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'sept': 9, 'okt': 10, 'nov': 11, 'dec': 12,
}


def parse_nl_datum(tekst):
    """Probeer een datum als '4 oktober 2026' of '24-10-2026' te lezen. Geeft None als dat niet lukt."""
    tekst = str(tekst or '').strip().lower()
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(tekst, fmt).date()
        except ValueError:
            pass
    delen = tekst.replace(',', ' ').split()
    if len(delen) >= 3 and delen[0].isdigit() and delen[2].isdigit() and delen[1].rstrip('.') in NL_MAANDEN:
        try:
            return datetime(int(delen[2]), NL_MAANDEN[delen[1].rstrip('.')], int(delen[0])).date()
        except ValueError:
            return None
    return None


def laatste_wedstrijd(archief_page):
    """
    Geeft (index, block) van de laatst gespeelde wedstrijd uit het archief, of (None, None).
    Wedstrijden met een leesbare datum gaan voor; bij gelijke of onleesbare datums wint
    de wedstrijd die het laatst in de lijst is toegevoegd.
    """
    if not archief_page or not archief_page.wedstrijden:
        return None, None
    blocks = list(enumerate(archief_page.wedstrijden))
    beste = max(
        blocks,
        key=lambda item: (parse_nl_datum(item[1].value.get('datum_str')) or datetime.min.date(), item[0]),
    )
    return beste


def items_met_reacties(page, stream):
    """
    Lijst van (block, reacties) voor een StreamField. Reacties hangen aan het vaste id van
    het block, dus verwijderen of van volgorde veranderen verschuift ze niet.
    """
    per_block = {}
    for r in WedstrijdReactie.objects.filter(page=page).order_by('datum_aangemaakt'):
        per_block.setdefault(r.block_id, []).append(r)
    return [(block, per_block.get(block.id, [])) for block in stream]


class PlayValue(StructValue):
    def video_opties(self):
        """Beschikbare video's voor deze play, in de volgorde van de toggle-knoppen."""
        opties = [
            ('zonder', 'Zonder defense', 'bi-person', self.get('video_reallife')),
            ('met', 'Met defense', 'bi-shield-shaded', self.get('video_defense')),
            ('animatie', 'Animatie', 'bi-easel', self.get('video_animatie')),
        ]
        return [
            {'key': key, 'label': label, 'icon': icon, 'embed_url': youtube_embed_url(url)}
            for key, label, icon, url in opties
            if youtube_embed_url(url)
        ]

    def stappen(self):
        return [s for s in (self.get('stap_1'), self.get('stap_2'), self.get('stap_3'), self.get('stap_4')) if s]


class PlayBlock(StructBlock):
    titel = CharBlock(required=True, help_text="Bijv. Horns Twist")
    categorie = CharBlock(required=True, help_text="Bijv. Aanval, Inbounds of Defense")
    korte_beschrijving = CharBlock(required=True, help_text="Korte intro van the play")
    
    video_animatie = URLBlock(required=False, help_text="YouTube link van de getekende animatie / bord-tekening")
    video_reallife = URLBlock(required=False, help_text="YouTube link van de real-life uitvoering")
    video_defense = URLBlock(required=False, help_text="YouTube link van de real-life uitvoering met defense")
    
    opstelling = CharBlock(required=False, default="1-2-2", help_text="Bijv. 1-2-2")
    focus = CharBlock(required=False, help_text="Bijv. Pick & roll")
    
    stap_1 = CharBlock(required=False, help_text="Uitleg stap 1")
    stap_2 = CharBlock(required=False, help_text="Uitleg stap 2")
    stap_3 = CharBlock(required=False, help_text="Uitleg stap 3")
    stap_4 = CharBlock(required=False, help_text="Uitleg stap 4")

    class Meta:
        value_class = PlayValue
        icon = "folder"
        label = "Play"


class PlaysPage(Page):
    intro = RichTextField(blank=True, help_text="Introductietekst boven het playbook")
    
    plays = StreamField([
        ('play', PlayBlock()),
    ], use_json_field=True, blank=True)

    content_panels = Page.content_panels + [
        FieldPanel('intro'),
        FieldPanel('plays'),
    ]

    def get_context(self, request):
        context = super().get_context(request)
        context['plays_met_reacties'] = items_met_reacties(self, self.plays)
        context['is_moderator'] = is_moderator(request.user)
        context['kan_film_toevoegen'] = kan_film_toevoegen(request.user, self)
        # Gegevens om het bewerkformulier in te vullen (alleen voor coaches)
        context['beheer_data'] = {b.id: dict(b.value) for b in self.plays} if context['kan_film_toevoegen'] else {}
        return context


class CommentBlock(StructBlock):
    naam = CharBlock(required=True, help_text="Naam van coach of speler")
    rol = CharBlock(required=True, help_text="Bijv. Hoofdcoach of Speler")
    reactie = TextBlock(required=True, help_text="Reactie met eventuele tijd (bijv. 01:22)")

    class Meta:
        icon = "comment"
        label = "Reactie"


from wagtail.blocks import StructBlock, CharBlock, StreamBlock, StructValue

class WedstrijdResultaatValue(StructValue):
    def get_embed_url(self):
        return youtube_embed_url(self.get('youtube_url'))

class WedstrijdResultaatBlock(StructBlock):
    titel = CharBlock(required=True, help_text="Bijv. BVA VSE-2 - BC Leiden")
    datum_str = CharBlock(required=True, help_text="Bijv. 4 oktober 2026")
    uitslag = CharBlock(required=True, help_text="Bijv. 53 - 36")
    youtube_url = CharBlock(required=True, help_text="Plak hier de YouTube link")

    class Meta:
        value_class = WedstrijdResultaatValue
        icon = "date"
        label = "Gespeelde Wedstrijd"

class WedstrijdenArchiefPage(Page):
    intro = RichTextField(blank=True, help_text="Introductietekst boven het archief")
    
    wedstrijden = StreamField([
        ('wedstrijd', WedstrijdResultaatBlock()),
    ], use_json_field=True, blank=True)

    content_panels = Page.content_panels + [
        FieldPanel('intro'),
        FieldPanel('wedstrijden'),
    ]

    def get_context(self, request):
        context = super().get_context(request)
        context['wedstrijden_met_reacties'] = items_met_reacties(self, self.wedstrijden)
        context['is_moderator'] = is_moderator(request.user)
        context['kan_film_toevoegen'] = kan_film_toevoegen(request.user, self)
        context['beheer_data'] = (
            {b.id: dict(b.value) for b in self.wedstrijden} if context['kan_film_toevoegen'] else {}
        )
        return context

# Voeg een apart block toe voor reacties binnen een wedstrijd
class ReactieBlock(blocks.StructBlock):
    auteur_naam = blocks.CharBlock(required=True, label="Naam (bijv. Coach Jan of Daan)")
    rol = blocks.ChoiceBlock(choices=[
        ('coach', 'Coach'),
        ('teammate', 'Teammate')
    ], default='teammate', label="Rol")
    tekst = blocks.TextBlock(required=True, label="Reactie / Notitie")

    class Meta:
        icon = "comment"
        label = "Reactie"

class WedstrijdBlock(blocks.StructBlock):
    titel = blocks.CharBlock(required=True, label="Wedstrijd Titel (bijv. BVA VSE-2 - BC Leiden)")
    datum_str = blocks.CharBlock(required=True, label="Datum (bijv. 4 oktober 2026)")
    uitslag = blocks.CharBlock(required=True, label="Einduitslag (bijv. 53 - 36)")
    video_url = blocks.URLBlock(required=True, label="YouTube Video URL")
    
    # Hier voegen we de reacties aan toe!
    reacties = blocks.ListBlock(ReactieBlock(), label="Coach & Teammate Reacties", blank=True)

    def get_embed_url(self):
        # Zet normale YouTube links om naar een embed URL
        url = self.video_url
        if "youtu.be/" in url:
            video_id = url.split("youtu.be/")[-1].split("?")[0]
            return f"https://www.youtube-nocookie.com/embed/{video_id}"
        elif "watch?v=" in url:
            video_id = url.split("watch?v=")[-1].split("&")[0]
            return f"https://www.youtube-nocookie.com/embed/{video_id}"
        return url

    class Meta:
        icon = "media"
        label = "Wedstrijd"

class WedstrijdReactie(models.Model):
    # Koppel de reactie aan de Wagtail-pagina en het vaste id van de wedstrijd/play (StreamField-block)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='wedstrijd_reacties')
    block_id = models.CharField(max_length=64, db_index=True, help_text='Id van de wedstrijd of play op de pagina')
    auteur_naam = models.CharField(max_length=100)
    rol = models.CharField(max_length=20, choices=[('coach', 'Coach'), ('teammate', 'Teammate')], default='teammate')
    tekst = models.TextField()
    datum_aangemaakt = models.DateTimeField(auto_now_add=True)
    datum_bewerkt = models.DateTimeField(null=True, blank=True)
    # SHA-256 hash van de geheime bewerk-sleutel die de schrijver in de browser bewaart.
    # Leeg bij oude reacties: die kan alleen een moderator nog beheren.
    bewerk_token_hash = models.CharField(max_length=64, blank=True, editable=False)

    def __str__(self):
        return f"{self.auteur_naam} ({self.rol}) - {self.block_id[:8]}"


def kan_film_toevoegen(user, page):
    """Mag deze gebruiker films toevoegen aan deze pagina? (coach met publiceer-rechten of beheerder)"""
    if not (user and user.is_authenticated):
        return False
    return page.permissions_for_user(user).can_publish()


def is_moderator(user):
    """Ingelogde Wagtail-beheerders mogen alle reacties bewerken en verwijderen."""
    return bool(
        user and user.is_authenticated
        and (user.is_superuser or user.has_perm('wagtailadmin.access_admin'))
    )


# ---------------------------------------------------------------------------
# Training: opdrachten die speelsters per week kunnen afvinken
# ---------------------------------------------------------------------------

def week_start(datum):
    """Maandag van de week waarin `datum` valt."""
    return datum - timedelta(days=datum.weekday())


class Opdracht(models.Model):
    CATEGORIEEN = [
        ('kracht', '💪 Kracht'),
        ('conditie', '🫁 Conditie'),
        ('techniek', '🏀 Techniek / shooting'),
        ('mobiliteit', '🧘 Mobiliteit / blessurepreventie'),
        ('overig', '⭐ Overig'),
    ]

    titel = models.CharField(max_length=150)
    uitleg = models.TextField(blank=True)
    video_url = models.URLField(blank=True, help_text='YouTube-link (optioneel)')
    categorie = models.CharField(max_length=20, choices=CATEGORIEEN, default='techniek')
    hoeveelheid = models.CharField(max_length=100, blank=True, help_text='Bijv. 3×15, 20 min of 50 vrije worpen')
    begin = models.DateField('begindatum', help_text='Vanaf deze dag staat de opdracht klaar.')
    eind = models.DateField('einddatum', help_text='Tot en met deze dag. Bij een eenmalige opdracht is dit de deadline.')
    herhalend = models.BooleanField(
        'elke week opnieuw', default=False,
        help_text='Aan: elke week in deze periode opnieuw afvinken. Uit: één keer afvinken vóór de einddatum.',
    )
    voor_spelers = models.ManyToManyField(
        Speler, blank=True, related_name='persoonlijke_opdrachten', verbose_name='voor speelsters',
        help_text='Laat leeg voor iedereen. Kies speelsters als de opdracht alleen voor hen is.',
    )
    aangemaakt_door = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='+', editable=False)
    aangemaakt = models.DateTimeField(auto_now_add=True)

    panels = [
        FieldPanel('titel'),
        FieldRowPanel([FieldPanel('categorie'), FieldPanel('hoeveelheid')]),
        FieldPanel('uitleg'),
        FieldPanel('video_url'),
        FieldRowPanel([FieldPanel('begin'), FieldPanel('eind')]),
        FieldPanel('herhalend'),
        FieldPanel('voor_spelers', widget=forms.CheckboxSelectMultiple),
    ]

    class Meta:
        ordering = ['aangemaakt']
        verbose_name = 'trainingsopdracht'
        verbose_name_plural = 'trainingsopdrachten'

    def __str__(self):
        return self.titel

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.begin and self.eind and self.eind < self.begin:
            raise ValidationError({'eind': 'De einddatum kan niet vóór de begindatum liggen.'})

    @property
    def begin_week(self):
        return week_start(self.begin)

    @property
    def eind_week(self):
        return week_start(self.eind)

    def afvink_week(self, maandag):
        '''
        Onder welke week een afvinking wordt opgeslagen.
        Herhalend: elke week apart. Eenmalig: één afvinking voor de hele periode.
        '''
        return maandag if self.herhalend else self.begin_week

    @property
    def embed_url(self):
        return youtube_embed_url(self.video_url)

    def _gekozen_ids(self):
        # Gebruikt de prefetch als die er is (voor_week doet dat), anders een query
        return {s.id for s in self.voor_spelers.all()}

    @property
    def voor_iedereen(self):
        return not self._gekozen_ids()

    def doel_ids(self, actieve_ids):
        '''Ids van de (actieve) speelsters voor wie deze opdracht geldt.'''
        gekozen = self._gekozen_ids()
        return (gekozen & set(actieve_ids)) if gekozen else set(actieve_ids)

    def geldt_voor(self, speler):
        gekozen = self._gekozen_ids()
        return not gekozen or speler.id in gekozen

    def voor_wie_tekst(self):
        namen = [s.naam for s in self.voor_spelers.all()]
        return ', '.join(namen) if namen else 'Iedereen'
    voor_wie_tekst.short_description = 'Voor'

    def geldt_in_week(self, maandag):
        '''Valt (een deel van) de periode in de week die op `maandag` begint?'''
        return self.begin <= maandag + timedelta(days=6) and self.eind >= maandag

    def telt_voor_reeks_in_week(self, maandag):
        '''Herhalend: elke week. Eenmalig: alleen in de week van de deadline.'''
        return self.geldt_in_week(maandag) if self.herhalend else self.eind_week == maandag

    @classmethod
    def voor_week(cls, maandag):
        return cls.objects.filter(
            begin__lte=maandag + timedelta(days=6), eind__gte=maandag,
        ).prefetch_related('voor_spelers')


class Afvinking(models.Model):
    speler = models.ForeignKey(Speler, on_delete=models.CASCADE, related_name='afvinkingen')
    opdracht = models.ForeignKey(Opdracht, on_delete=models.CASCADE, related_name='afvinkingen')
    week = models.DateField()
    gedaan_op = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['speler', 'opdracht', 'week'], name='uniek_afvinking_per_week'),
        ]

    def __str__(self):
        return f'{self.speler.naam} - {self.opdracht.titel} ({self.week})'


REEKS_MAX_WEKEN = 52


def reeksen(spelers, huidige_maandag):
    """
    Reeks per speler: aantal weken op rij waarin ze alle opdrachten deed.
    Weken zonder opdrachten tellen niet mee (en breken de reeks niet).
    De huidige week telt mee als hij al af is, maar breekt de reeks niet zolang hij nog loopt.
    """
    eerste = huidige_maandag - timedelta(weeks=REEKS_MAX_WEKEN)
    opdrachten = list(
        Opdracht.objects.filter(begin__lte=huidige_maandag + timedelta(days=6), eind__gte=eerste)
        .prefetch_related('voor_spelers')
    )
    gedaan = set(Afvinking.objects.filter(
        speler__in=spelers, opdracht__in=opdrachten, week__lte=huidige_maandag,
    ).values_list('speler_id', 'week', 'opdracht_id'))

    weken = []
    for i in range(REEKS_MAX_WEKEN + 1):
        maandag = huidige_maandag - timedelta(weeks=i)
        week_opdrachten = [o for o in opdrachten if o.telt_voor_reeks_in_week(maandag)]
        if week_opdrachten:
            weken.append((maandag, week_opdrachten))

    uitkomst = {}
    for speler in spelers:
        reeks = 0
        for maandag, week_opdrachten in weken:
            eigen = [o for o in week_opdrachten if o.geldt_voor(speler)]
            if not eigen:
                continue  # die week niets voor haar: telt niet mee en breekt de reeks niet
            if all((speler.id, o.afvink_week(maandag), o.id) in gedaan for o in eigen):
                reeks += 1
            elif maandag == huidige_maandag:
                continue
            else:
                break
        uitkomst[speler.id] = reeks
    return uitkomst


def week_overzicht(maandag, spelers=None):
    """Opdrachten, wie wat gedaan heeft en de teamvoortgang voor één week."""
    spelers = list(spelers if spelers is not None else Speler.objects.filter(actief=True))
    opdrachten = list(Opdracht.voor_week(maandag))
    actieve_ids = [s.id for s in spelers]
    doelen = {o.id: o.doel_ids(actieve_ids) for o in opdrachten}
    sleutel_week = {o.id: o.afvink_week(maandag) for o in opdrachten}
    gedaan = {
        (speler_id, opdracht_id)
        for speler_id, opdracht_id, week in Afvinking.objects.filter(
            week__in=set(sleutel_week.values()), opdracht__in=opdrachten, speler__in=spelers,
        ).values_list('speler_id', 'opdracht_id', 'week')
        if speler_id in doelen.get(opdracht_id, ()) and sleutel_week.get(opdracht_id) == week
    }
    totaal = sum(len(ids) for ids in doelen.values())
    return {
        'opdrachten': opdrachten,
        'spelers': spelers,
        'gedaan': gedaan,
        'doelen': doelen,
        'team_pct': round(100 * len(gedaan) / totaal) if totaal else 0,
        'aantal_gedaan': len(gedaan),
        'aantal_totaal': totaal,
    }


class TrainingPage(Page):
    intro = RichTextField(blank=True, help_text='Introductietekst boven de trainingsopdrachten')

    content_panels = Page.content_panels + [
        FieldPanel('intro'),
        HelpPanel(
            content='<p>Opdrachten voeg je toe via de knop <strong>Opdracht toevoegen</strong> op de pagina zelf, '
                    'of in het menu links onder <a href="/admin/snippets/home/opdracht/">Trainingsopdrachten</a>.</p>',
            heading='Opdrachten',
        ),
    ]

    SESSIE_SPELER = 'training_speler_id'

    def get_context(self, request):
        context = super().get_context(request)
        huidige = week_start(timezone.localdate())

        maandag = huidige
        gevraagd = request.GET.get('week')
        if gevraagd:
            try:
                maandag = week_start(datetime.strptime(gevraagd, '%Y-%m-%d').date())
            except ValueError:
                pass

        overzicht = week_overzicht(maandag)
        spelers = overzicht['spelers']
        gedaan = overzicht['gedaan']
        doelen = overzicht['doelen']
        aantal_opdrachten = len(overzicht['opdrachten'])

        ingelogd = None
        speler_id = request.session.get(self.SESSIE_SPELER)
        if speler_id:
            ingelogd = next((s for s in spelers if s.id == speler_id), None)

        opdrachten_info = []
        for o in overzicht['opdrachten']:
            doel = doelen[o.id]
            opdrachten_info.append({
                'opdracht': o,
                'voor_iedereen': o.voor_iedereen,
                'doel_spelers': [s for s in spelers if s.id in doel],
                'aantal_doel': len(doel),
                'gedaan_door': [s for s in spelers if (s.id, o.id) in gedaan],
                'voor_mij': bool(ingelogd and ingelogd.id in doel),
                'ik_gedaan': bool(ingelogd and (ingelogd.id, o.id) in gedaan),
            })
        # Opdrachten voor de ingelogde speelster bovenaan
        opdrachten_info.sort(key=lambda x: not x['voor_mij'])
        context['opdrachten_info'] = opdrachten_info

        reeks = reeksen(spelers, huidige)
        spelers_info = []
        for s in spelers:
            eigen = [o for o in overzicht['opdrachten'] if s.id in doelen[o.id]]
            aantal = sum(1 for o in eigen if (s.id, o.id) in gedaan)
            spelers_info.append({
                'speler': s,
                'aantal': aantal,
                'totaal': len(eigen),
                'pct': round(100 * aantal / len(eigen)) if eigen else 0,
                'klaar': bool(eigen) and aantal == len(eigen),
                'reeks': reeks.get(s.id, 0),
            })
        spelers_info.sort(key=lambda x: (-x['pct'], -x['reeks'], x['speler'].naam))

        context.update({
            'maandag': maandag,
            'zondag': maandag + timedelta(days=6),
            'vorige_week': maandag - timedelta(weeks=1),
            'volgende_week': maandag + timedelta(weeks=1),
            'is_huidige_week': maandag == huidige,
            'is_toekomst': maandag > huidige,
            'huidige_week': huidige,
            'vandaag': timezone.localdate(),
            'team_pct': overzicht['team_pct'],
            'aantal_gedaan': overzicht['aantal_gedaan'],
            'aantal_totaal': overzicht['aantal_totaal'],
            'aantal_opdrachten': aantal_opdrachten,
            'spelers_info': spelers_info,
            'alle_spelers': spelers,
            'ingelogde_speler': ingelogd,
            'kan_film_toevoegen': kan_film_toevoegen(request.user, self),
            'beheer_data': {
                str(o.id): {
                    'titel': o.titel, 'uitleg': o.uitleg, 'video_url': o.video_url, 'categorie': o.categorie,
                    'hoeveelheid': o.hoeveelheid, 'begin': o.begin.isoformat(), 'eind': o.eind.isoformat(),
                    'herhalend': o.herhalend, 'spelers': [s.id for s in o.voor_spelers.all()],
                }
                for o in overzicht['opdrachten']
            } if kan_film_toevoegen(request.user, self) else {},
            'categorieen': Opdracht.CATEGORIEEN,
        })
        return context


# ---------------------------------------------------------------------------
# Teampagina
# ---------------------------------------------------------------------------
from wagtail.images.blocks import ImageChooserBlock  # noqa: E402


def richtext_naar_tekst(html):
    """Rich text terug naar platte tekst (voor bewerkformulieren op de site)."""
    import html as _html
    from django.utils.html import strip_tags
    html = (html or '').replace('</p>', '\n\n').replace('<br/>', '\n').replace('<br>', '\n')
    return _html.unescape(strip_tags(html)).strip()


class StafBlock(StructBlock):
    naam = CharBlock(required=True, help_text='Bijv. Anniko')
    rol = CharBlock(required=True, help_text='Bijv. Hoofdcoach, Trainer of Teammanager')
    foto = ImageChooserBlock(required=False)

    class Meta:
        icon = 'user'
        label = 'Staflid'


class TeamPage(Page):
    intro = RichTextField(blank=True, help_text='Korte tekst over het team')
    teamfoto = models.ForeignKey(
        'wagtailimages.Image', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    staf = StreamField([('persoon', StafBlock())], use_json_field=True, blank=True)

    content_panels = Page.content_panels + [
        FieldPanel('intro'),
        FieldPanel('teamfoto'),
        FieldPanel('staf'),
        HelpPanel(
            content='<p>De speelsters komen automatisch uit <a href="/admin/snippets/home/speler/">Spelers</a> '
                    '(naam, rugnummer, positie en foto).</p>',
            heading='Speelsters',
        ),
    ]

    def get_context(self, request):
        context = super().get_context(request)
        spelers = list(Speler.objects.filter(actief=True))
        maandag = week_start(timezone.localdate())
        overzicht = week_overzicht(maandag, spelers)
        reeks = reeksen(spelers, maandag)
        doelen, gedaan = overzicht['doelen'], overzicht['gedaan']

        kaarten = []
        for s in spelers:
            eigen = [o for o in overzicht['opdrachten'] if s.id in doelen[o.id]]
            klaar = sum(1 for o in eigen if (s.id, o.id) in gedaan)
            kaarten.append({
                'speler': s,
                'initialen': ''.join(deel[0] for deel in s.naam.replace('-', ' ').split()[:2]).upper(),
                'reeks': reeks.get(s.id, 0),
                'training_pct': round(100 * klaar / len(eigen)) if eigen else None,
            })
        context['spelers_kaarten'] = kaarten
        context['training_url'] = (TrainingPage.objects.live().first() or self).url

        # Beheer op de pagina zelf (geen Wagtail-admin nodig)
        kan_spelers = request.user.has_perm('home.change_speler')
        kan_pagina = kan_film_toevoegen(request.user, self)
        context['kan_spelers_beheren'] = kan_spelers
        context['kan_pagina_bewerken'] = kan_pagina
        if kan_spelers:
            alle = list(Speler.objects.all())
            context['inactieve_spelers'] = [s for s in alle if not s.actief]
            context['posities'] = Speler.POSITIES
            context['speler_data'] = {
                str(s.id): {
                    'naam': s.naam, 'rugnummer': '' if s.rugnummer is None else s.rugnummer,
                    'positie': s.positie, 'actief': s.actief, 'heeft_pincode': s.heeft_pincode,
                    'foto_url': s.foto.get_rendition('fill-160x160').url if s.foto else '',
                }
                for s in alle
            }
        if kan_pagina:
            context['staf_data'] = {
                b.id: {
                    'naam': b.value.get('naam'), 'rol': b.value.get('rol'),
                    'foto_url': b.value['foto'].get_rendition('fill-160x160').url if b.value.get('foto') else '',
                }
                for b in self.staf
            }
            context['intro_tekst'] = richtext_naar_tekst(self.intro)
            context['teamfoto_url'] = self.teamfoto.get_rendition('fill-320x180').url if self.teamfoto else ''
        return context


# ---------------------------------------------------------------------------
# Mededelingenbord
# ---------------------------------------------------------------------------

class Mededeling(models.Model):
    titel = models.CharField(max_length=120)
    tekst = models.TextField(blank=True, max_length=1000)
    belangrijk = models.BooleanField(default=False, help_text='Valt extra op en staat bovenaan.')
    zichtbaar_vanaf = models.DateField(default=timezone.localdate)
    zichtbaar_tot = models.DateField(null=True, blank=True,
                                     help_text='Daarna verdwijnt hij vanzelf. Leeg = blijft staan tot je hem verwijdert.')
    aangemaakt_door = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='+', editable=False)
    aangemaakt = models.DateTimeField(auto_now_add=True)

    panels = [
        FieldPanel('titel'),
        FieldPanel('tekst'),
        FieldPanel('belangrijk'),
        FieldRowPanel([FieldPanel('zichtbaar_vanaf'), FieldPanel('zichtbaar_tot')]),
    ]

    class Meta:
        ordering = ['-belangrijk', '-aangemaakt']
        verbose_name = 'mededeling'
        verbose_name_plural = 'mededelingen'

    def __str__(self):
        return self.titel

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.zichtbaar_tot and self.zichtbaar_vanaf and self.zichtbaar_tot < self.zichtbaar_vanaf:
            raise ValidationError({'zichtbaar_tot': 'Deze datum kan niet vóór "zichtbaar vanaf" liggen.'})

    @property
    def auteur(self):
        u = self.aangemaakt_door
        return (u.get_full_name() or u.get_username()) if u else ''

    @classmethod
    def actueel(cls):
        vandaag = timezone.localdate()
        return cls.objects.filter(
            Q(zichtbaar_vanaf__lte=vandaag) & (Q(zichtbaar_tot__isnull=True) | Q(zichtbaar_tot__gte=vandaag))
        ).select_related('aangemaakt_door')


# ---------------------------------------------------------------------------
# Pushmeldingen
# ---------------------------------------------------------------------------

class PushSleutel(models.Model):
    """Het (VAPID-)sleutelpaar van de site. Wordt één keer automatisch aangemaakt."""
    publiek = models.CharField(max_length=200)
    privaat_pem = models.TextField()
    aangemaakt = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'push-sleutel'
        verbose_name_plural = 'push-sleutels'

    def __str__(self):
        return f'Push-sleutel van {self.aangemaakt:%d-%m-%Y}'


class PushAbonnement(models.Model):
    """Een telefoon/browser die meldingen wil ontvangen."""
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    # Bekend als een speelster met haar pincode is ingelogd: dan krijgt ze ook persoonlijke meldingen
    speler = models.ForeignKey(Speler, null=True, blank=True, on_delete=models.SET_NULL, related_name='push_abonnementen')
    gebruiker = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    apparaat = models.CharField(max_length=200, blank=True)
    aangemaakt = models.DateTimeField(auto_now_add=True)
    bijgewerkt = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'push-abonnement'
        verbose_name_plural = 'push-abonnementen'

    def __str__(self):
        wie = self.speler.naam if self.speler else (self.gebruiker.get_username() if self.gebruiker else 'onbekend')
        return f'{wie} · {self.apparaat[:40]}'

    def als_subscription(self):
        return {'endpoint': self.endpoint, 'keys': {'p256dh': self.p256dh, 'auth': self.auth}}


# ---------------------------------------------------------------------------
# Statistieken: per wedstrijd elke actie (schot, rebound, assist ...) per kwart
# ---------------------------------------------------------------------------

class Wedstrijd(models.Model):
    """Een wedstrijd waarvan de statistieken worden bijgehouden."""
    datum = models.DateField()
    tegenstander = models.CharField(max_length=100)
    thuis = models.BooleanField(default=True)
    # Gekoppelde wedstrijdfilm uit het archief (id van het StreamField-block), zodat je kunt bijhouden met de video erbij
    film_block_id = models.CharField(max_length=64, blank=True, editable=False)
    aangemaakt = models.DateTimeField(auto_now_add=True)

    panels = [
        FieldRowPanel([FieldPanel('datum'), FieldPanel('thuis')]),
        FieldPanel('tegenstander'),
    ]

    class Meta:
        ordering = ['-datum', '-id']
        verbose_name = 'wedstrijd (statistieken)'
        verbose_name_plural = 'wedstrijden (statistieken)'

    def __str__(self):
        return f"{self.datum:%d-%m-%Y} {'vs' if self.thuis else '@'} {self.tegenstander}"


class StatActie(models.Model):
    """Eén genoteerde actie. Acties van de tegenstander (t1/t2/t3) hebben geen speelster."""
    SOORTEN = [
        ('2r', '2 punten raak'), ('2m', '2 punten mis'),
        ('3r', '3 punten raak'), ('3m', '3 punten mis'),
        ('fr', 'Vrije worp raak'), ('fm', 'Vrije worp mis'),
        ('or', 'Aanvallende rebound'), ('dr', 'Verdedigende rebound'),
        ('as', 'Assist'), ('st', 'Steal'), ('bl', 'Block'),
        ('to', 'Balverlies'), ('pf', 'Fout'),
        ('t1', 'Tegenstander +1'), ('t2', 'Tegenstander +2'), ('t3', 'Tegenstander +3'),
    ]
    TEGENSTANDER = {'t1', 't2', 't3'}
    KWARTEN = [(1, 'Q1'), (2, 'Q2'), (3, 'Q3'), (4, 'Q4'), (5, 'Verlenging')]

    wedstrijd = models.ForeignKey(Wedstrijd, on_delete=models.CASCADE, related_name='acties')
    speler = models.ForeignKey(Speler, null=True, blank=True, on_delete=models.SET_NULL, related_name='stat_acties')
    kwart = models.PositiveSmallIntegerField(choices=KWARTEN)
    soort = models.CharField(max_length=2, choices=SOORTEN)
    # Uniek id uit de browser, zodat een actie die opnieuw verstuurd wordt (slecht internet) niet dubbel telt
    client_id = models.CharField(max_length=40, unique=True)
    door = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    aangemaakt = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['aangemaakt', 'id']
        verbose_name = 'statistiek-actie'
        verbose_name_plural = 'statistiek-acties'

    def __str__(self):
        return f'{self.wedstrijd} Q{self.kwart} {self.speler or "tegenstander"}: {self.get_soort_display()}'


class StatsPage(Page):
    intro = RichTextField(blank=True, help_text='Introductietekst boven de statistieken')

    parent_page_types = ['home.HomePage']
    max_count = 1

    content_panels = Page.content_panels + [
        FieldPanel('intro'),
        HelpPanel(
            content='<p>Statistieken worden op de pagina zelf bijgehouden. Wie dat mag, zet je in de groep '
                    '<strong>Statistieken</strong> (Instellingen → Gebruikers).</p>',
            heading='Bijhouden',
        ),
    ]

    def get_context(self, request):
        from .stats import stats_context
        context = super().get_context(request)
        context.update(stats_context(self, request))
        return context


class Bestand(models.Model):
    """Een geüpload bestand (foto, document), opgeslagen in de database. Zie home/opslag.py."""
    naam = models.CharField(max_length=255, unique=True)
    inhoud = models.BinaryField()
    grootte = models.PositiveIntegerField(default=0)
    gewijzigd = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'bestand'
        verbose_name_plural = 'bestanden'

    def __str__(self):
        return self.naam

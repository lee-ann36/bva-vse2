from home.models import HomePage

from wagtail.models import Page, Site
from wagtail.test.utils import WagtailPageTestCase


class HomeSetUpTests(WagtailPageTestCase):
    """
    Tests for basic page structure setup and HomePage creation.
    """

    def test_root_create(self):
        root_page = Page.objects.get(pk=1)
        self.assertIsNotNone(root_page)

    def test_homepage_create(self):
        root_page = Page.objects.get(pk=1)
        homepage = HomePage(title="Home", koptekst="Test")
        root_page.add_child(instance=homepage)
        self.assertTrue(HomePage.objects.filter(title="Home").exists())


class HomeTests(WagtailPageTestCase):
    """
    Tests for homepage functionality and rendering.
    """

    def setUp(self):
        """
        Create a homepage instance for testing.
        """
        root_page = Page.get_first_root_node()
        Site.objects.create(hostname="testsite", root_page=root_page, is_default_site=True)
        self.homepage = HomePage(title="Home", koptekst="Test")
        root_page.add_child(instance=self.homepage)

    def test_homepage_is_renderable(self):
        self.assertPageIsRenderable(self.homepage)

    def test_homepage_template_used(self):
        response = self.client.get(self.homepage.url)
        self.assertTemplateUsed(response, "home/home_page.html")


import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from home.models import PlaysPage, WedstrijdenArchiefPage, WedstrijdReactie


class ReactieRechtenTests(TestCase):
    """Alleen de schrijver (met bewerk-sleutel) of een moderator mag een reactie bewerken/verwijderen."""

    def setUp(self):
        root = Page.get_first_root_node()
        Site.objects.create(hostname="testserver", root_page=root, is_default_site=True)
        self.archief = WedstrijdenArchiefPage(
            title="Archief", slug="archief-test",
            wedstrijden=[('wedstrijd', {'titel': 'A - B', 'datum_str': '4 oktober 2026',
                                        'uitslag': '1 - 0', 'youtube_url': 'https://youtu.be/abc'})],
        )
        root.add_child(instance=self.archief)
        self.plays = PlaysPage(
            title="Plays", slug="plays-test",
            plays=[('play', {'titel': 'Horns', 'categorie': 'Aanval', 'korte_beschrijving': 'x'})],
        )
        root.add_child(instance=self.plays)
        # enforce_csrf_checks: zo testen we ook dat de echte CSRF-bescherming aan staat
        self.client = Client(enforce_csrf_checks=True)

    def _csrf(self, client):
        # Zelfde waarde in cookie en header, zoals de browser doet via de csrf-token meta-tag
        token = 'a' * 32
        client.cookies['csrftoken'] = token
        return token

    def _post(self, url, data, client=None):
        client = client or self.client
        return client.post(url, json.dumps(data), content_type='application/json',
                           HTTP_X_CSRFTOKEN=self._csrf(client))

    def _block_id(self, page=None, index=0):
        page = page or self.archief
        stream = page.wedstrijden if isinstance(page, WedstrijdenArchiefPage) else page.plays
        return stream[index].id

    def _plaats(self, page=None, index=0, tekst='Goede actie op 01:22'):
        r = self._post('/api/sla-reactie/', {
            'page_id': (page or self.archief).id, 'block_id': self._block_id(page, index),
            'auteur': 'Daan', 'rol': 'teammate', 'tekst': tekst,
        })
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_plaatsen_geeft_sleutel_en_slaat_alleen_hash_op(self):
        data = self._plaats()
        self.assertTrue(data['token'])
        reactie = WedstrijdReactie.objects.get(id=data['id'])
        self.assertNotEqual(reactie.bewerk_token_hash, data['token'])
        self.assertEqual(len(reactie.bewerk_token_hash), 64)

    def test_plaatsen_werkt_ook_op_plays_pagina(self):
        self._plaats(page=self.plays)
        self.assertEqual(WedstrijdReactie.objects.filter(page=self.plays).count(), 1)

    def test_zonder_csrf_geweigerd(self):
        r = self.client.post('/api/sla-reactie/', json.dumps({}), content_type='application/json')
        self.assertEqual(r.status_code, 403)

    def test_ongeldige_invoer_geweigerd(self):
        basis = {'page_id': self.archief.id, 'block_id': self._block_id(), 'auteur': 'X', 'rol': 'teammate', 'tekst': 'hoi'}
        for fout in ({'block_id': 'bestaat-niet'}, {'block_id': self._block_id(self.plays)},
                     {'rol': 'admin'}, {'tekst': ''}, {'tekst': 'x' * 2001}, {'page_id': 999999}):
            r = self._post('/api/sla-reactie/', {**basis, **fout})
            self.assertIn(r.status_code, (400, 404), fout)
        self.assertEqual(WedstrijdReactie.objects.count(), 0)

    def test_eigen_reactie_bewerken_en_verwijderen(self):
        data = self._plaats()
        r = self._post('/api/bewerk-reactie/', {'id': data['id'], 'token': data['token'], 'tekst': 'Aangepast'})
        self.assertEqual(r.status_code, 200)
        reactie = WedstrijdReactie.objects.get(id=data['id'])
        self.assertEqual(reactie.tekst, 'Aangepast')
        self.assertIsNotNone(reactie.datum_bewerkt)

        r = self._post('/api/verwijder-reactie/', {'id': data['id'], 'token': data['token']})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(WedstrijdReactie.objects.filter(id=data['id']).exists())

    def test_iemand_anders_mag_niet_bewerken_of_verwijderen(self):
        data = self._plaats()
        anders = self._plaats(tekst='Andere reactie')  # heeft een eigen, andere sleutel
        for token in ('', 'fout', anders['token'], None):
            r = self._post('/api/bewerk-reactie/', {'id': data['id'], 'token': token, 'tekst': 'gehackt'})
            self.assertEqual(r.status_code, 403, token)
            r = self._post('/api/verwijder-reactie/', {'id': data['id'], 'token': token})
            self.assertEqual(r.status_code, 403, token)
        reactie = WedstrijdReactie.objects.get(id=data['id'])
        self.assertEqual(reactie.tekst, 'Goede actie op 01:22')

    def test_oude_reactie_zonder_sleutel_niet_te_wijzigen(self):
        oud = WedstrijdReactie.objects.create(page=self.archief, block_id=self._block_id(), auteur_naam='Oud', tekst='oud')
        r = self._post('/api/verwijder-reactie/', {'id': oud.id, 'token': ''})
        self.assertEqual(r.status_code, 403)

    def test_moderator_mag_alles(self):
        data = self._plaats()
        get_user_model().objects.create_superuser('coach', 'c@example.com', 'geheim123')
        mod = Client(enforce_csrf_checks=True)
        mod.login(username='coach', password='geheim123')
        r = self._post('/api/bewerk-reactie/', {'id': data['id'], 'tekst': 'Door moderator'}, client=mod)
        self.assertEqual(r.status_code, 200)
        r = self._post('/api/verwijder-reactie/', {'id': data['id']}, client=mod)
        self.assertEqual(r.status_code, 200)

    def test_menu_standaard_verborgen_en_tekst_ge_escaped(self):
        self._plaats(tekst='<img src=x onerror=alert(1)> 01:22')
        html = Client().get(self.archief.url).content.decode()
        self.assertIn('comment-actions d-none', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img src=x', html)


from home.models import Speler


class SpelersTests(WagtailPageTestCase):
    """Het aantal spelers op de homepage wordt geteld uit de actieve spelers."""

    def setUp(self):
        root = Page.get_first_root_node()
        Site.objects.create(hostname="testserver", root_page=root, is_default_site=True)
        self.homepage = HomePage(title="Home", koptekst="Test")
        root.add_child(instance=self.homepage)

    def test_aantal_telt_alleen_actieve_spelers(self):
        Speler.objects.create(naam="Daan", rugnummer=4, positie="PG")
        Speler.objects.create(naam="Sem", rugnummer=12)
        Speler.objects.create(naam="Geblesseerd", rugnummer=7, actief=False)
        response = self.client.get(self.homepage.url)
        self.assertEqual(response.context['aantal_spelers'], 2)
        self.assertContains(response, '<div class="num">2</div>', html=True)

    def test_spelers_in_admin_menu(self):
        get_user_model().objects.create_superuser('coach', 'c@example.com', 'geheim123')
        self.client.login(username='coach', password='geheim123')
        Speler.objects.create(naam="Daan", rugnummer=4)
        response = self.client.get('/admin/snippets/home/speler/')
        self.assertContains(response, 'Daan')
        self.assertEqual(self.client.get('/admin/snippets/home/speler/add/').status_code, 200)


from django.core.management import call_command
from django.contrib.auth.models import Group


class FilmToevoegenTests(TestCase):
    """Coaches (groep Coaches) mogen films/plays toevoegen; anderen niet."""

    def setUp(self):
        root = Page.get_first_root_node()
        Site.objects.create(hostname="testserver", root_page=root, is_default_site=True)
        self.archief = WedstrijdenArchiefPage(
            title="Archief", slug="archief-test",
            wedstrijden=[('wedstrijd', {'titel': 'Oud', 'datum_str': '4 oktober 2026',
                                        'uitslag': '1 - 0', 'youtube_url': 'https://youtu.be/abc'})],
        )
        root.add_child(instance=self.archief)
        self.plays = PlaysPage(title="Plays", slug="plays-test")
        root.add_child(instance=self.plays)
        self.andere_pagina = HomePage(title="Home2", slug="home2", koptekst="x")
        root.add_child(instance=self.andere_pagina)

        call_command('coach_rechten', stdout=open(__import__('os').devnull, 'w'))
        User = get_user_model()
        self.coach = User.objects.create_user('coach', password='geheim123')
        self.coach.groups.add(Group.objects.get(name='Coaches'))
        User.objects.create_user('speler', password='geheim123')

    def _client(self, username=None):
        c = Client(enforce_csrf_checks=True)
        if username:
            c.login(username=username, password='geheim123')
        c.cookies['csrftoken'] = 'b' * 32
        return c

    def _post(self, client, data):
        return client.post('/api/film-toevoegen/', json.dumps(data), content_type='application/json',
                           HTTP_X_CSRFTOKEN='b' * 32)

    WEDSTRIJD = {'titel': 'BVA VSE-2 - Punch', 'datum_str': '1 november 2026',
                 'uitslag': '60 - 50', 'youtube_url': 'https://www.youtube.com/watch?v=nieuw123'}

    def test_coach_voegt_wedstrijd_toe_en_hij_staat_live(self):
        oud_id = self.archief.wedstrijden[0].id
        WedstrijdReactie.objects.create(page=self.archief, block_id=oud_id, auteur_naam='A', tekst='bij Oud')
        r = self._post(self._client('coach'), {'page_id': self.archief.id, **self.WEDSTRIJD})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['index'], 1)

        self.archief.refresh_from_db()
        self.assertEqual([b.value['titel'] for b in self.archief.wedstrijden], ['Oud', 'BVA VSE-2 - Punch'])
        self.assertEqual(self.archief.wedstrijden[1].value.get_embed_url(),
                         'https://www.youtube-nocookie.com/embed/nieuw123')
        # bestaande reactie hoort nog steeds bij de oude wedstrijd
        html = Client().get(self.archief.url).content.decode()
        self.assertIn('BVA VSE-2 - Punch', html)
        self.assertEqual(WedstrijdReactie.objects.get().block_id, oud_id)

    def test_coach_voegt_play_toe(self):
        r = self._post(self._client('coach'), {
            'page_id': self.plays.id, 'titel': 'Horns', 'categorie': 'Aanval',
            'korte_beschrijving': 'Twist', 'video_reallife': 'https://youtu.be/zonder',
            'video_defense': 'https://youtu.be/met', 'stap_1': 'Eerst',
        })
        self.assertEqual(r.status_code, 200, r.content)
        self.plays.refresh_from_db()
        opties = self.plays.plays[0].value.video_opties()
        self.assertEqual([o['key'] for o in opties], ['zonder', 'met'])

    def test_play_zonder_video_of_met_foute_link_geweigerd(self):
        basis = {'page_id': self.plays.id, 'titel': 'X', 'categorie': 'Aanval', 'korte_beschrijving': 'y'}
        self.assertEqual(self._post(self._client('coach'), basis).status_code, 400)
        r = self._post(self._client('coach'), {**basis, 'video_defense': 'https://vimeo.com/123'})
        self.assertEqual(r.status_code, 400)

    def test_niet_ingelogd_of_geen_coach_geweigerd(self):
        for client in (self._client(), self._client('speler')):
            r = self._post(client, {'page_id': self.archief.id, **self.WEDSTRIJD})
            self.assertEqual(r.status_code, 403)
        self.archief.refresh_from_db()
        self.assertEqual(len(self.archief.wedstrijden), 1)

    def test_coach_mag_niet_op_andere_paginas(self):
        r = self._post(self._client('coach'), {'page_id': self.andere_pagina.id, **self.WEDSTRIJD})
        self.assertEqual(r.status_code, 400)

    def test_knop_alleen_zichtbaar_voor_coach(self):
        self.assertNotIn('filmToevoegenModal', Client().get(self.archief.url).content.decode())
        self.assertIn('Coach? Log in', Client().get(self.archief.url).content.decode())
        c = Client(); c.login(username='coach', password='geheim123')
        self.assertIn('filmToevoegenModal', c.get(self.archief.url).content.decode())
        self.assertIn('filmToevoegenModal', c.get(self.plays.url).content.decode())


from django.core.cache import cache


class CoachInloggenTests(FilmToevoegenTests):
    """Inloggen via het formulier op de pagina (hergebruikt de opzet van FilmToevoegenTests)."""

    def _login(self, client, gebruikersnaam, wachtwoord, page=None):
        return client.post('/api/coach-inloggen/', json.dumps({
            'page_id': (page or self.archief).id, 'gebruikersnaam': gebruikersnaam, 'wachtwoord': wachtwoord,
        }), content_type='application/json', HTTP_X_CSRFTOKEN='b' * 32)

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_inloggen_en_daarna_film_toevoegen(self):
        c = self._client()
        self.assertEqual(self._login(c, 'coach', 'geheim123').status_code, 200)
        c.cookies['csrftoken'] = 'b' * 32  # login() roteert het CSRF-token
        r = self._post(c, {'page_id': self.archief.id, **self.WEDSTRIJD})
        self.assertEqual(r.status_code, 200, r.content)

    def test_fout_wachtwoord(self):
        r = self._login(self._client(), 'coach', 'fout')
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()['message'], 'Onjuiste naam of wachtwoord.')

    def test_account_zonder_rechten_wordt_niet_ingelogd(self):
        c = self._client()
        self.assertEqual(self._login(c, 'speler', 'geheim123').status_code, 403)
        self.assertNotIn('_auth_user_id', c.session)

    def test_blokkade_na_te_veel_pogingen(self):
        c = self._client()
        for _ in range(10):
            self._login(c, 'coach', 'fout')
        self.assertEqual(self._login(c, 'coach', 'geheim123').status_code, 429)

    def test_uitloggen(self):
        c = self._client()
        self._login(c, 'coach', 'geheim123')
        c.cookies['csrftoken'] = 'b' * 32
        c.post('/api/coach-uitloggen/', '{}', content_type='application/json', HTTP_X_CSRFTOKEN='b' * 32)
        self.assertNotIn('_auth_user_id', c.session)

    def test_login_formulier_zichtbaar_voor_bezoeker(self):
        html = Client().get(self.plays.url).content.decode()
        self.assertIn('coachLoginModal', html)
        self.assertNotIn('filmToevoegenModal', html)

from django.utils import timezone


from datetime import date, timedelta
from unittest import mock

from home.models import Afvinking, Opdracht, TrainingPage, reeksen, week_start


class WeekLogicaTests(TestCase):
    def test_week_start_is_maandag(self):
        self.assertEqual(week_start(date(2026, 11, 8)), date(2026, 11, 2))   # zondag -> maandag
        self.assertEqual(week_start(date(2026, 11, 2)), date(2026, 11, 2))

    def test_periode_bepaalt_in_welke_weken_hij_staat(self):
        ma = date(2026, 11, 2)
        # woensdag t/m dinsdag erna: valt in twee weken
        a = Opdracht.objects.create(titel='A', begin=date(2026, 11, 4), eind=date(2026, 11, 10))
        b = Opdracht.objects.create(titel='B', begin=ma, eind=ma + timedelta(days=6))
        self.assertEqual(set(Opdracht.voor_week(ma)), {a, b})
        self.assertEqual(set(Opdracht.voor_week(ma + timedelta(weeks=1))), {a})
        self.assertEqual(set(Opdracht.voor_week(ma + timedelta(weeks=2))), set())
        self.assertEqual(set(Opdracht.voor_week(ma - timedelta(weeks=1))), set())

    def test_afvinkweek(self):
        ma = date(2026, 11, 2)
        eenmalig = Opdracht.objects.create(titel='A', begin=date(2026, 11, 4), eind=date(2026, 11, 20))
        herhalend = Opdracht.objects.create(titel='B', begin=ma, eind=date(2026, 11, 20), herhalend=True)
        self.assertEqual(eenmalig.afvink_week(ma + timedelta(weeks=2)), ma)  # één keer voor de hele periode
        self.assertEqual(herhalend.afvink_week(ma + timedelta(weeks=2)), ma + timedelta(weeks=2))

    def test_reeks(self):
        nu = date(2026, 11, 16)
        s = Speler.objects.create(naam='Eva')
        o = Opdracht.objects.create(titel='Elke week', begin=nu - timedelta(weeks=5),
                                    eind=nu + timedelta(weeks=4), herhalend=True)
        # 3 weken op rij gedaan (week -3, -2, -1), week -4 niet, huidige week nog niet
        for w in (1, 2, 3):
            Afvinking.objects.create(speler=s, opdracht=o, week=nu - timedelta(weeks=w))
        self.assertEqual(reeksen([s], nu)[s.id], 3)
        Afvinking.objects.create(speler=s, opdracht=o, week=nu)  # huidige week ook af
        self.assertEqual(reeksen([s], nu)[s.id], 4)


class TrainingOpzet(TestCase):
    """Gedeelde opzet voor trainingstests (bevat zelf geen tests)."""

    def setUp(self):
        cache.clear()
        root = Page.get_first_root_node()
        Site.objects.create(hostname="testserver", root_page=root, is_default_site=True)
        self.page = TrainingPage(title="Training", slug="training")
        root.add_child(instance=self.page)
        call_command('trainer_rechten', stdout=open(__import__('os').devnull, 'w'))

        self.eva = Speler.objects.create(naam='Eva')
        self.eva.set_pincode('1234'); self.eva.save()
        self.tess = Speler.objects.create(naam='Tess')
        self.tess.set_pincode('9999'); self.tess.save()
        self.zonder_pin = Speler.objects.create(naam='Rosa')

        self.maandag = week_start(timezone.localdate())
        self.opdracht = Opdracht.objects.create(titel='50 vrije worpen', begin=self.maandag,
                                                eind=self.maandag + timedelta(weeks=8), herhalend=True)

        User = get_user_model()
        self.trainer = User.objects.create_user('trainer', password='geheim123')
        self.trainer.groups.add(Group.objects.get(name='Trainers'))
        User.objects.create_user('coach', password='geheim123').groups.add(
            Group.objects.get_or_create(name='Coaches')[0])

    def _client(self, username=None):
        c = Client(enforce_csrf_checks=True)
        if username:
            c.login(username=username, password='geheim123')
        c.cookies['csrftoken'] = 'c' * 32
        return c

    def _post(self, client, url, data):
        return client.post(url, json.dumps(data), content_type='application/json', HTTP_X_CSRFTOKEN='c' * 32)

    def _kies(self, client, speler, pin):
        return self._post(client, '/api/training/speler-kiezen/', {'speler_id': speler.id, 'pincode': pin})

    def _vink(self, client, gedaan=True, week=None):
        return self._post(client, '/api/training/afvinken/', {
            'opdracht_id': self.opdracht.id, 'week': (week or self.maandag).isoformat(), 'gedaan': gedaan})

    OPDRACHT = {'titel': 'Planken', 'categorie': 'kracht', 'hoeveelheid': '3×1 min',
                'uitleg': 'Rug recht', 'video_url': 'https://youtu.be/plank', 'herhalend': False}

    def _periode(self, begin=None, eind=None):
        begin = begin or self.maandag
        return {'begin': begin.isoformat(), 'eind': (eind or begin + timedelta(days=6)).isoformat()}


class TrainingTests(TrainingOpzet):
    # --- speelsters ---
    def test_afvinken_met_juiste_pincode(self):
        c = self._client()
        self.assertEqual(self._kies(c, self.eva, '1234').status_code, 200)
        self.assertEqual(self._vink(c).status_code, 200)
        self.assertTrue(Afvinking.objects.filter(speler=self.eva, opdracht=self.opdracht, week=self.maandag).exists())
        self._vink(c)  # twee keer afvinken geeft geen dubbele
        self.assertEqual(Afvinking.objects.count(), 1)
        self.assertEqual(self._vink(c, gedaan=False).status_code, 200)
        self.assertEqual(Afvinking.objects.count(), 0)

    def test_zonder_naam_kiezen_mag_niet(self):
        self.assertEqual(self._vink(self._client()).status_code, 403)

    def test_foute_pincode_en_blokkade(self):
        c = self._client()
        self.assertEqual(self._kies(c, self.eva, '0000').status_code, 401)
        for _ in range(4):
            self._kies(c, self.eva, '0000')
        self.assertEqual(self._kies(c, self.eva, '1234').status_code, 429)  # geblokkeerd, ook met goede pin

    def test_blokkade_geldt_per_speelster_ook_vanaf_ander_adres(self):
        for i in range(5):
            self._post(Client(REMOTE_ADDR=f'10.0.0.{i}', enforce_csrf_checks=False), '/api/training/speler-kiezen/',
                       {'speler_id': self.eva.id, 'pincode': '0000'})
        self.assertEqual(self._kies(self._client(), self.eva, '1234').status_code, 429)

    def test_zonder_pincode_ingesteld(self):
        self.assertEqual(self._kies(self._client(), self.zonder_pin, '').status_code, 403)

    def test_kan_alleen_voor_zichzelf_afvinken(self):
        c = self._client()
        self._kies(c, self.eva, '1234')
        self._vink(c)
        self.assertFalse(Afvinking.objects.filter(speler=self.tess).exists())

    def test_toekomstige_week_niet_afvinken(self):
        c = self._client()
        self._kies(c, self.eva, '1234')
        self.assertEqual(self._vink(c, week=self.maandag + timedelta(weeks=1)).status_code, 400)

    # --- trainers ---
    OPDRACHT = {'titel': 'Planken', 'categorie': 'kracht', 'hoeveelheid': '3×1 min',
                'uitleg': 'Rug recht', 'video_url': 'https://youtu.be/plank', 'herhalend': False}

    def test_trainer_voegt_opdracht_toe(self):
        r = self._post(self._client('trainer'), '/api/training/opdracht-toevoegen/',
                       {'page_id': self.page.id, **self._periode(self.maandag + timedelta(days=3)), **self.OPDRACHT})
        self.assertEqual(r.status_code, 200, r.content)
        o = Opdracht.objects.get(titel='Planken')
        self.assertEqual(o.begin, self.maandag + timedelta(days=3))
        self.assertEqual(o.eind, self.maandag + timedelta(days=9))
        self.assertEqual(o.aangemaakt_door, self.trainer)
        self.assertEqual(o.embed_url, 'https://www.youtube-nocookie.com/embed/plank')

    def test_geen_trainer_geweigerd(self):
        for client in (self._client(), self._client('coach')):
            r = self._post(client, '/api/training/opdracht-toevoegen/',
                           {'page_id': self.page.id, **self._periode(), **self.OPDRACHT})
            self.assertEqual(r.status_code, 403)

    def test_herhalende_opdracht_stoppen_bewaart_verleden(self):
        self.opdracht.begin = self.maandag - timedelta(weeks=2); self.opdracht.save()
        Afvinking.objects.create(speler=self.eva, opdracht=self.opdracht, week=self.maandag - timedelta(weeks=1))
        r = self._post(self._client('trainer'), '/api/training/opdracht-verwijderen/', {
            'page_id': self.page.id, 'id': self.opdracht.id, 'week': self.maandag.isoformat(),
            'alleen_vanaf_deze_week': True})
        self.assertEqual(r.status_code, 200)
        self.opdracht.refresh_from_db()
        self.assertEqual(self.opdracht.eind, self.maandag - timedelta(days=1))
        self.assertNotIn(self.opdracht, Opdracht.voor_week(self.maandag))
        self.assertEqual(Afvinking.objects.count(), 1)

    def test_trainer_login_via_pagina(self):
        c = self._client()
        r = self._post(c, '/api/coach-inloggen/', {'page_id': self.page.id, 'gebruikersnaam': 'trainer', 'wachtwoord': 'geheim123'})
        self.assertEqual(r.status_code, 200)
        r = self._post(self._client(), '/api/coach-inloggen/', {'page_id': self.page.id, 'gebruikersnaam': 'coach', 'wachtwoord': 'geheim123'})
        self.assertEqual(r.status_code, 403)

    # --- pagina ---
    def test_pagina_toont_voortgang(self):
        Afvinking.objects.create(speler=self.eva, opdracht=self.opdracht, week=self.maandag)
        r = Client().get(self.page.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['team_pct'], 33)  # 1 van 3 speelsters x 1 opdracht
        self.assertContains(r, '50 vrije worpen')
        self.assertContains(r, 'spelerKiezenModal')
        self.assertNotContains(r, 'filmToevoegenModal')
        trainer = Client(); trainer.login(username='trainer', password='geheim123')
        self.assertContains(trainer.get(self.page.url), 'NIEUWE TRAININGSOPDRACHT')

    def test_homepage_blok(self):
        home = HomePage(title="Home3", slug="home3", koptekst="x")
        Page.get_first_root_node().add_child(instance=home)
        r = Client().get(home.url)
        self.assertEqual(r.context['training_aantal'], 1)
        self.assertContains(r, 'btn-training')

    def test_pincode_commando(self):
        call_command('speler_pincodes', stdout=open(__import__('os').devnull, 'w'))
        self.zonder_pin.refresh_from_db()
        self.assertTrue(self.zonder_pin.heeft_pincode)
        self.eva.refresh_from_db()
        self.assertTrue(self.eva.check_pincode('1234'))  # bestaande pincode niet overschreven


class PersoonlijkeOpdrachtTests(TrainingOpzet):
    """Opdrachten voor bepaalde speelsters (hergebruikt de opzet van TrainingTests)."""

    def setUp(self):
        super().setUp()
        self.persoonlijk = Opdracht.objects.create(titel='Extra schieten', begin=self.maandag,
                                                   eind=self.maandag + timedelta(days=6))
        self.persoonlijk.voor_spelers.set([self.eva])

    def _vink_persoonlijk(self, client):
        return self._post(client, '/api/training/afvinken/', {
            'opdracht_id': self.persoonlijk.id, 'week': self.maandag.isoformat(), 'gedaan': True})

    def test_alleen_doelspeelster_mag_afvinken(self):
        c = self._client()
        self._kies(c, self.tess, '9999')
        self.assertEqual(self._vink_persoonlijk(c).status_code, 403)
        c = self._client()
        self._kies(c, self.eva, '1234')
        self.assertEqual(self._vink_persoonlijk(c).status_code, 200)

    def test_voortgang_telt_alleen_eigen_opdrachten(self):
        # 3 speelsters x opdracht voor iedereen + 1 persoonlijke = 4 keer te doen
        Afvinking.objects.create(speler=self.eva, opdracht=self.persoonlijk, week=self.maandag)
        r = Client().get(self.page.url)
        self.assertEqual(r.context['aantal_totaal'], 4)
        self.assertEqual(r.context['team_pct'], 25)
        info = {i['speler'].naam: i for i in r.context['spelers_info']}
        self.assertEqual((info['Eva']['aantal'], info['Eva']['totaal']), (1, 2))
        self.assertEqual((info['Tess']['aantal'], info['Tess']['totaal']), (0, 1))
        self.assertContains(r, '👤 Eva')

    def test_niet_voor_jou_zichtbaar(self):
        c = Client()
        self._kies(self._client(), self.tess, '9999')  # andere client; daarom zelf de sessie zetten
        s = c.session; s[TrainingPage.SESSIE_SPELER] = self.tess.id; s.save()
        self.assertContains(c.get(self.page.url), 'Niet voor jou')

    def test_reeks_met_persoonlijke_opdracht(self):
        # Tess heeft de opdracht voor iedereen gedaan; de persoonlijke van Eva telt voor haar niet mee
        Afvinking.objects.create(speler=self.tess, opdracht=self.opdracht, week=self.maandag)
        self.assertEqual(reeksen([self.tess, self.eva], self.maandag)[self.tess.id], 1)
        self.assertEqual(reeksen([self.tess, self.eva], self.maandag)[self.eva.id], 0)

    def test_trainer_maakt_persoonlijke_opdracht(self):
        r = self._post(self._client('trainer'), '/api/training/opdracht-toevoegen/', {
            'page_id': self.page.id, **self._periode(), **self.OPDRACHT,
            'spelers': [self.eva.id, self.tess.id]})
        self.assertEqual(r.status_code, 200, r.content)
        o = Opdracht.objects.get(titel='Planken')
        self.assertEqual(set(o.voor_spelers.all()), {self.eva, self.tess})
        self.assertFalse(o.voor_iedereen)

    def test_lege_lijst_is_iedereen_en_onbekende_speelster_geweigerd(self):
        c = self._client('trainer')
        r = self._post(c, '/api/training/opdracht-toevoegen/', {
            'page_id': self.page.id, **self._periode(), **self.OPDRACHT, 'spelers': []})
        self.assertTrue(Opdracht.objects.get(titel='Planken').voor_iedereen)
        r = self._post(c, '/api/training/opdracht-toevoegen/', {
            'page_id': self.page.id, **self._periode(), **self.OPDRACHT,
            'titel': 'Fout', 'spelers': [999999]})
        self.assertEqual(r.status_code, 400)


class PeriodeTests(TrainingOpzet):
    """Opdrachten met een begindatum en einddatum."""

    def setUp(self):
        super().setUp()
        # Eenmalige opdracht van vorige week t/m volgende week (deadline volgende week zondag)
        self.eenmalig = Opdracht.objects.create(
            titel='Conditietest', begin=self.maandag - timedelta(weeks=1), eind=self.maandag + timedelta(days=13))

    def test_eenmalig_een_keer_afvinken_geldt_voor_hele_periode(self):
        c = self._client()
        self._kies(c, self.eva, '1234')
        r = self._post(c, '/api/training/afvinken/', {
            'opdracht_id': self.eenmalig.id, 'week': self.maandag.isoformat(), 'gedaan': True})
        self.assertEqual(r.status_code, 200)
        # Opgeslagen onder de beginweek, dus ook in andere weken van de periode "gedaan"
        a = Afvinking.objects.get(opdracht=self.eenmalig)
        self.assertEqual(a.week, self.maandag - timedelta(weeks=1))
        for week in (self.maandag - timedelta(weeks=1), self.maandag, self.maandag + timedelta(weeks=1)):
            r = c.get(self.page.url, {'week': week.isoformat()})
            info = next(i for i in r.context['opdrachten_info'] if i['opdracht'].id == self.eenmalig.id)
            self.assertTrue(info['ik_gedaan'], week)

    def test_herhalend_elke_week_apart(self):
        c = self._client()
        self._kies(c, self.eva, '1234')
        self._vink(c)  # self.opdracht is herhalend
        r = c.get(self.page.url, {'week': (self.maandag - timedelta(weeks=1)).isoformat()})
        ids = [i['opdracht'].id for i in r.context['opdrachten_info']]
        self.assertNotIn(self.opdracht.id, ids)  # herhalende begint pas deze week
        self.assertIn(self.eenmalig.id, ids)     # eenmalige liep vorige week al
        r = c.get(self.page.url)
        info = next(i for i in r.context['opdrachten_info'] if i['opdracht'].id == self.opdracht.id)
        self.assertTrue(info['ik_gedaan'])

    def test_eenmalig_breekt_reeks_niet_voor_de_deadline(self):
        # Eva doet de herhalende opdracht deze week; de eenmalige is pas volgende week deadline
        Afvinking.objects.create(speler=self.eva, opdracht=self.opdracht, week=self.maandag)
        self.assertEqual(reeksen([self.eva], self.maandag)[self.eva.id], 1)

    def test_einddatum_voor_begindatum_geweigerd(self):
        r = self._post(self._client('trainer'), '/api/training/opdracht-toevoegen/', {
            'page_id': self.page.id, **self.OPDRACHT,
            'begin': self.maandag.isoformat(), 'eind': (self.maandag - timedelta(days=1)).isoformat()})
        self.assertEqual(r.status_code, 400)
        self.assertIn('einddatum', r.json()['message'])

    def test_deadline_zichtbaar(self):
        r = Client().get(self.page.url)
        self.assertContains(r, 'Eén keer doen, deadline')
        self.assertContains(r, '📅')


from home.models import Mededeling, TeamPage


class ReactieVastAanBlockTests(ReactieRechtenTests):
    """Reacties blijven bij de juiste wedstrijd als de volgorde verandert of er een wordt verwijderd."""

    def test_volgorde_wijzigen_en_verwijderen_verschuift_reacties_niet(self):
        self.archief.wedstrijden.append(('wedstrijd', {
            'titel': 'C - D', 'datum_str': '11 oktober 2026', 'uitslag': '2 - 0', 'youtube_url': 'https://youtu.be/def'}))
        self.archief.save_revision().publish()
        self.archief.refresh_from_db()
        eerste_id, tweede_id = [b.id for b in self.archief.wedstrijden]
        self._plaats(index=1, tekst='Over C - D')

        # coach verwijdert de eerste wedstrijd -> C - D staat nu op plek 0
        del self.archief.wedstrijden[0]
        self.archief.save_revision().publish()
        self.archief.refresh_from_db()
        self.assertEqual(self.archief.wedstrijden[0].id, tweede_id)

        html = Client().get(self.archief.url).content.decode()
        kaart = html.split('id="match-0"')[1].split('id="match-1"')[0] if 'id="match-1"' in html else html.split('id="match-0"')[1]
        self.assertIn('Over C - D', kaart)
        self.assertEqual(WedstrijdReactie.objects.get().block_id, tweede_id)


class TeamEnMededelingTests(TestCase):
    def setUp(self):
        root = Page.get_first_root_node()
        Site.objects.create(hostname="testserver", root_page=root, is_default_site=True)
        self.home = HomePage(title="Home", slug="home-t", koptekst="x")
        root.add_child(instance=self.home)
        self.team = TeamPage(title="Ons team", slug="team",
                             staf=[('persoon', {'naam': 'Anniko', 'rol': 'Coach', 'foto': None})])
        root.add_child(instance=self.team)
        Speler.objects.create(naam='Lee-Ann', rugnummer=7, positie='PG')
        Speler.objects.create(naam='Zoë')
        Speler.objects.create(naam='Weg', actief=False)

    def test_teampagina(self):
        r = Client().get(self.team.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Lee-Ann')
        self.assertContains(r, '#7')
        self.assertContains(r, 'Point guard (1)')
        self.assertContains(r, 'LA')        # initialen zonder foto
        self.assertNotContains(r, '>Weg<')  # niet-actieve speelster niet tonen
        self.assertContains(r, 'Anniko')
        self.assertContains(r, 'Coach')

    def test_mededelingen_op_homepage(self):
        vandaag = timezone.localdate()
        Mededeling.objects.create(titel='Zaterdag eerder', tekst='30 min eerder', belangrijk=True)
        Mededeling.objects.create(titel='Verlopen', zichtbaar_vanaf=vandaag - timedelta(days=9),
                                  zichtbaar_tot=vandaag - timedelta(days=1))
        Mededeling.objects.create(titel='Toekomst', zichtbaar_vanaf=vandaag + timedelta(days=3))
        r = Client().get(self.home.url)
        self.assertContains(r, 'Zaterdag eerder')
        self.assertContains(r, '📌')
        self.assertNotContains(r, 'Verlopen')
        self.assertNotContains(r, 'Toekomst')
        self.assertNotContains(r, '+ Mededeling plaatsen')

    def test_geen_mededelingen_geen_blok_voor_bezoekers(self):
        self.assertNotContains(Client().get(self.home.url), '📢 Mededelingen')

    def test_coach_ziet_plaatsen_link_en_mag_toevoegen(self):
        call_command('coach_rechten', stdout=open(__import__('os').devnull, 'w'))
        coach = get_user_model().objects.create_user('coach', password='geheim123')
        coach.groups.add(Group.objects.get(name='Coaches'))
        c = Client(); c.login(username='coach', password='geheim123')
        self.assertContains(c.get(self.home.url), '+ Mededeling plaatsen')
        self.assertEqual(c.get('/admin/snippets/home/mededeling/add/').status_code, 200)

    def test_app_bestanden(self):
        c = Client()
        m = c.get('/manifest.webmanifest')
        self.assertEqual(m.status_code, 200)
        data = json.loads(m.content)
        self.assertEqual(data['short_name'], 'VSE-2')
        self.assertEqual(data['display'], 'standalone')
        self.assertTrue(any(i['purpose'] == 'maskable' for i in data['icons']))
        sw = c.get('/sw.js')
        self.assertEqual(sw.status_code, 200)
        self.assertIn('javascript', sw['Content-Type'])
        self.assertIn("startsWith('/api/')", sw.content.decode())  # API nooit uit de cache
        self.assertEqual(c.get('/offline/').status_code, 200)
        for url in (self.home.url, self.team.url):
            html = c.get(url).content.decode()
            self.assertIn('rel="manifest"', html)
            self.assertIn('apple-touch-icon', html)
            self.assertIn('name="viewport"', html)


import io as _io
import re as _re

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image as _PILImage


def _test_foto(naam='foto.png'):
    buf = _io.BytesIO()
    _PILImage.new('RGB', (40, 40), (88, 166, 194)).save(buf, format='PNG')
    return SimpleUploadedFile(naam, buf.getvalue(), content_type='image/png')


import shutil as _shutil
import tempfile as _tempfile

from django.test import override_settings

_TEST_MEDIA = _tempfile.mkdtemp(prefix='bva-test-media-')


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class BeheerOpDeSiteTests(TestCase):
    """Alles wat coaches en trainers doen kan op de site zelf, zonder Wagtail-admin."""

    def setUp(self):
        cache.clear()
        root = Page.get_first_root_node()
        Site.objects.create(hostname="testserver", root_page=root, is_default_site=True)
        self.home = HomePage(title="Home", slug="home-b", koptekst="x")
        root.add_child(instance=self.home)
        self.archief = WedstrijdenArchiefPage(title="Wedstrijden", slug="wedstrijden", wedstrijden=[
            ('wedstrijd', {'titel': 'A - B', 'datum_str': '4 oktober 2026', 'uitslag': '1 - 0', 'youtube_url': 'https://youtu.be/aaa'}),
            ('wedstrijd', {'titel': 'C - D', 'datum_str': '11 oktober 2026', 'uitslag': '2 - 0', 'youtube_url': 'https://youtu.be/bbb'}),
        ])
        root.add_child(instance=self.archief)
        self.plays = PlaysPage(title="Plays", slug="plays")
        root.add_child(instance=self.plays)
        self.training = TrainingPage(title="Training", slug="training")
        root.add_child(instance=self.training)
        self.team = TeamPage(title="Ons team", slug="team")
        root.add_child(instance=self.team)
        devnull = open(__import__('os').devnull, 'w')
        call_command('coach_rechten', stdout=devnull)
        call_command('trainer_rechten', stdout=devnull)

        U = get_user_model()
        self.coach = U.objects.create_user('coach', password='geheim123')
        self.coach.groups.add(Group.objects.get(name='Coaches'))
        self.trainer = U.objects.create_user('trainer', password='geheim123')
        self.trainer.groups.add(Group.objects.get(name='Trainers'))
        U.objects.create_user('bezoeker', password='geheim123')

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        _shutil.rmtree(_TEST_MEDIA, ignore_errors=True)  # testfoto's opruimen

    def _c(self, wie=None):
        c = Client(enforce_csrf_checks=True)
        if wie:
            c.login(username=wie, password='geheim123')
        c.cookies['csrftoken'] = 'd' * 32
        return c

    def _json(self, c, url, data):
        return c.post(url, json.dumps(data), content_type='application/json', HTTP_X_CSRFTOKEN='d' * 32)

    def _form(self, c, url, data):
        return c.post(url, data, HTTP_X_CSRFTOKEN='d' * 32)

    # --- geen admin-links meer ---
    def test_geen_links_naar_admin_voor_coach_en_trainer(self):
        for wie in ('coach', 'trainer'):
            c = Client(); c.login(username=wie, password='geheim123')
            for page in (self.home, self.archief, self.plays, self.training, self.team):
                html = c.get(page.url).content.decode()
                self.assertIsNone(_re.search(r'href="/admin', html), f'{wie} ziet admin-link op {page.url}')

    # --- wedstrijden: bewerken en verwijderen ---
    def test_wedstrijd_bewerken_houdt_id_en_reacties(self):
        b_id = self.archief.wedstrijden[1].id
        WedstrijdReactie.objects.create(page=self.archief, block_id=b_id, auteur_naam='X', tekst='goed')
        r = self._json(self._c('coach'), '/api/film-toevoegen/', {
            'page_id': self.archief.id, 'block_id': b_id, 'titel': 'C - D (aangepast)',
            'datum_str': '11 oktober 2026', 'uitslag': '3 - 0', 'youtube_url': 'https://youtu.be/ccc'})
        self.assertEqual(r.status_code, 200, r.content)
        self.archief.refresh_from_db()
        self.assertEqual(len(self.archief.wedstrijden), 2)
        self.assertEqual(self.archief.wedstrijden[1].id, b_id)
        self.assertEqual(self.archief.wedstrijden[1].value['uitslag'], '3 - 0')
        self.assertEqual(WedstrijdReactie.objects.filter(block_id=b_id).count(), 1)

    def test_wedstrijd_verwijderen_ook_reacties(self):
        b_id = self.archief.wedstrijden[0].id
        WedstrijdReactie.objects.create(page=self.archief, block_id=b_id, auteur_naam='X', tekst='weg')
        self.assertEqual(self._json(self._c('trainer'), '/api/film-verwijderen/',
                                    {'page_id': self.archief.id, 'block_id': b_id}).status_code, 403)
        r = self._json(self._c('coach'), '/api/film-verwijderen/', {'page_id': self.archief.id, 'block_id': b_id})
        self.assertEqual(r.status_code, 200)
        self.archief.refresh_from_db()
        self.assertEqual([b.value['titel'] for b in self.archief.wedstrijden], ['C - D'])
        self.assertFalse(WedstrijdReactie.objects.exists())

    def test_coach_ziet_bewerk_knoppen_en_gegevens(self):
        c = Client(); c.login(username='coach', password='geheim123')
        html = c.get(self.archief.url).content.decode()
        self.assertIn("openFormulier('" + self.archief.wedstrijden[0].id, html)
        self.assertIn('id="beheer-data"', html)
        self.assertNotIn('id="beheer-data"', Client().get(self.archief.url).content.decode())

    # --- opdracht bewerken ---
    def test_opdracht_bewerken(self):
        ma = week_start(timezone.localdate())
        o = Opdracht.objects.create(titel='Oud', begin=ma, eind=ma + timedelta(days=6))
        r = self._json(self._c('trainer'), '/api/training/opdracht-toevoegen/', {
            'page_id': self.training.id, 'id': o.id, 'titel': 'Nieuw', 'categorie': 'kracht',
            'begin': ma.isoformat(), 'eind': (ma + timedelta(days=13)).isoformat(), 'herhalend': True, 'spelers': []})
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual((o.titel, o.herhalend, o.eind), ('Nieuw', True, ma + timedelta(days=13)))
        self.assertEqual(Opdracht.objects.count(), 1)

    # --- homepage: inloggen en mededelingen ---
    def test_inloggen_op_homepage(self):
        c = self._c()
        r = self._json(c, '/api/coach-inloggen/', {'page_id': self.home.id, 'gebruikersnaam': 'coach', 'wachtwoord': 'geheim123'})
        self.assertEqual(r.status_code, 200)
        # Een trainer mag op de homepage niets (alleen trainingsopdrachten)
        r = self._json(self._c(), '/api/coach-inloggen/', {'page_id': self.home.id, 'gebruikersnaam': 'trainer', 'wachtwoord': 'geheim123'})
        self.assertEqual(r.status_code, 403)
        r = self._json(self._c(), '/api/coach-inloggen/', {'page_id': self.home.id, 'gebruikersnaam': 'bezoeker', 'wachtwoord': 'geheim123'})
        self.assertEqual(r.status_code, 403)
        self.assertContains(Client().get(self.home.url), 'Coach of trainer? Inloggen')

    def test_mededeling_plaatsen_bewerken_verwijderen(self):
        self.assertEqual(self._json(self._c('trainer'), '/api/mededeling-opslaan/', {'titel': 'X'}).status_code, 403)
        c = self._c('coach')
        r = self._json(c, '/api/mededeling-opslaan/', {'titel': 'Eerder in de zaal', 'tekst': '30 min', 'belangrijk': True})
        self.assertEqual(r.status_code, 200, r.content)
        m = Mededeling.objects.get()
        self.assertEqual((m.aangemaakt_door, m.belangrijk, m.zichtbaar_vanaf), (self.coach, True, timezone.localdate()))
        r = self._json(c, '/api/mededeling-opslaan/', {'id': m.id, 'titel': 'Aangepast', 'tekst': '', 'belangrijk': False})
        m.refresh_from_db()
        self.assertEqual((m.titel, m.belangrijk), ('Aangepast', False))
        self.assertEqual(self._json(c, '/api/mededeling-verwijderen/', {'id': m.id}).status_code, 200)
        self.assertFalse(Mededeling.objects.exists())

    def test_mededeling_niet_voor_bezoekers(self):
        for wie in (None, 'bezoeker'):
            r = self._json(self._c(wie), '/api/mededeling-opslaan/', {'titel': 'Hack'})
            self.assertEqual(r.status_code, 403)
        r = self._json(self._c('coach'), '/api/mededeling-opslaan/', {
            'titel': 'X', 'zichtbaar_vanaf': '2026-11-10', 'zichtbaar_tot': '2026-11-01'})
        self.assertEqual(r.status_code, 400)

    # --- trainers: alleen trainingsopdrachten ---
    def test_trainer_mag_alleen_opdrachten(self):
        from home.models import is_moderator
        self.assertEqual(set(self.trainer.get_all_permissions()),
                         {'home.add_opdracht', 'home.change_opdracht', 'home.delete_opdracht'})
        self.assertFalse(is_moderator(self.trainer))  # geen reacties van anderen beheren, niet als coach reageren
        for page in (self.home, self.archief, self.plays, self.team):
            self.assertFalse(page.permissions_for_user(self.trainer).can_publish(), page.title)
        self.assertTrue(self.training.permissions_for_user(self.trainer).can_publish())
        r = self._json(self._c('trainer'), '/api/film-toevoegen/', {
            'page_id': self.archief.id, 'titel': 'X', 'datum_str': '1 oktober 2026', 'uitslag': '1-0', 'youtube_url': 'https://youtu.be/abc'})
        self.assertEqual(r.status_code, 403)
        # Oude, ruimere rechten worden bij het opnieuw draaien weer weggehaald
        from django.contrib.auth.models import Permission
        groep = Group.objects.get(name='Trainers')
        groep.permissions.add(Permission.objects.get(codename='add_mededeling'))
        call_command('trainer_rechten', stdout=open(__import__('os').devnull, 'w'))
        self.assertNotIn('add_mededeling', groep.permissions.values_list('codename', flat=True))

    # --- teampagina: spelers ---
    def test_speler_toevoegen_met_foto_en_pincode(self):
        r = self._form(self._c('trainer'), '/api/team/speler-opslaan/', {'naam': 'X', 'pincode': '1111'})
        self.assertEqual(r.status_code, 403)  # trainers beheren alleen opdrachten
        r = self._form(self._c('coach'), '/api/team/speler-opslaan/', {
            'naam': 'Nieuwe', 'rugnummer': '12', 'positie': 'C', 'actief': 'on', 'pincode': '4321', 'foto': _test_foto()})
        self.assertEqual(r.status_code, 200, r.content)
        s = Speler.objects.get(naam='Nieuwe')
        self.assertEqual((s.rugnummer, s.positie, s.actief), (12, 'C', True))
        self.assertTrue(s.check_pincode('4321'))
        self.assertIsNotNone(s.foto)

    def test_speler_bewerken_zonder_pincode_houdt_oude(self):
        s = Speler.objects.create(naam='Eva'); s.set_pincode('1111'); s.save()
        r = self._form(self._c('coach'), '/api/team/speler-opslaan/', {'id': s.id, 'naam': 'Eva', 'rugnummer': '', 'pincode': ''})
        self.assertEqual(r.status_code, 200, r.content)
        s.refresh_from_db()
        self.assertTrue(s.check_pincode('1111'))
        self.assertFalse(s.actief)  # schakelaar uit = niet actief

    def test_speler_ongeldige_invoer(self):
        c = self._c('coach')
        for data in ({'naam': 'X', 'pincode': '12'}, {'naam': 'X', 'pincode': '1234', 'rugnummer': '120'},
                     {'naam': '', 'pincode': '1234'}, {'naam': 'X'},  # nieuwe speelster zonder pincode
                     {'naam': 'X', 'pincode': '1234', 'foto': SimpleUploadedFile('x.png', b'geen foto', 'image/png')}):
            self.assertEqual(self._form(c, '/api/team/speler-opslaan/', data).status_code, 400, data)
        self.assertFalse(Speler.objects.exists())
        self.assertEqual(self._form(self._c('bezoeker'), '/api/team/speler-opslaan/', {'naam': 'X', 'pincode': '1234'}).status_code, 403)

    # --- teampagina: staf en teamfoto ---
    def test_staf_en_teaminfo(self):
        c = self._c('coach')
        r = self._form(c, '/api/team/staf-opslaan/', {'page_id': self.team.id, 'naam': 'Anniko', 'rol': 'Coach', 'foto': _test_foto()})
        self.assertEqual(r.status_code, 200, r.content)
        self.team.refresh_from_db()
        b_id = self.team.staf[0].id
        self.assertIsNotNone(self.team.staf[0].value['foto'])
        self._form(c, '/api/team/staf-opslaan/', {'page_id': self.team.id, 'block_id': b_id, 'naam': 'Anniko', 'rol': 'Hoofdcoach', 'foto_verwijderen': '1'})
        self.team.refresh_from_db()
        self.assertEqual((self.team.staf[0].value['rol'], self.team.staf[0].value['foto']), ('Hoofdcoach', None))
        r = self._form(c, '/api/team/info-opslaan/', {'page_id': self.team.id, 'intro': 'Wij zijn VSE-2.\n\n<b>Samen</b>', 'teamfoto': _test_foto()})
        self.assertEqual(r.status_code, 200, r.content)
        self.team.refresh_from_db()
        self.assertEqual(self.team.intro, '<p>Wij zijn VSE-2.</p><p>&lt;b&gt;Samen&lt;/b&gt;</p>')
        self.assertIsNotNone(self.team.teamfoto)
        self.assertEqual(self._json(c, '/api/team/staf-verwijderen/', {'page_id': self.team.id, 'block_id': b_id}).status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(len(self.team.staf), 0)

    def test_trainer_beheert_geen_spelers_of_staf(self):
        r = self._form(self._c('trainer'), '/api/team/staf-opslaan/', {'page_id': self.team.id, 'naam': 'X', 'rol': 'Y'})
        self.assertEqual(r.status_code, 403)
        c = Client(); c.login(username='trainer', password='geheim123')
        html = c.get(self.team.url).content.decode()
        self.assertNotIn('Speelster toevoegen', html)
        self.assertNotIn('Staflid toevoegen', html)


from home import push as _push
from home.models import PushAbonnement, PushSleutel


def _sub(n):
    return {'endpoint': f'https://push.example.com/telefoon-{n}',
            'keys': {'p256dh': 'B' + 'x' * 86, 'auth': 'a' * 22}}


class PushMeldingTests(TrainingOpzet):
    def setUp(self):
        super().setUp()
        _push.OP_ACHTERGROND = False
        self.home = HomePage(title="Home", slug="home-p", koptekst="x")
        Page.get_first_root_node().add_child(instance=self.home)
        call_command('coach_rechten', stdout=open(__import__('os').devnull, 'w'))

    def tearDown(self):
        _push.OP_ACHTERGROND = True

    def _meld_aan(self, client, n, speler=None, pin=None):
        if speler:
            self._kies(client, speler, pin)
        return self._post(client, '/api/push/aanmelden/', _sub(n))

    def test_sleutel_wordt_aangemaakt_en_in_pagina_gezet(self):
        html = Client().get(self.page.url).content.decode()
        sleutel = PushSleutel.objects.get()
        self.assertIn(f'name="push-sleutel" content="{sleutel.publiek}"', html)
        self.assertEqual(len(sleutel.publiek), 87)  # 65 bytes, base64url zonder '='
        Client().get(self.page.url)
        self.assertEqual(PushSleutel.objects.count(), 1)

    def test_aanmelden_koppelt_speelster_en_afmelden(self):
        c = self._client()
        r = self._meld_aan(c, 1, self.eva, '1234')
        self.assertEqual(r.json()['speler'], 'Eva')
        self.assertEqual(PushAbonnement.objects.get().speler, self.eva)
        self.assertEqual(self._post(c, '/api/push/aanmelden/', {'endpoint': 'http://onveilig', 'keys': {}}).status_code, 400)
        self._post(c, '/api/push/afmelden/', {'endpoint': _sub(1)['endpoint']})
        self.assertFalse(PushAbonnement.objects.exists())

    @mock.patch('pywebpush.webpush')
    def test_nieuwe_mededeling_naar_iedereen_bewerken_niet(self, webpush):
        self._meld_aan(self._client(), 1)
        self._meld_aan(self._client(), 2, self.tess, '9999')
        coach = get_user_model().objects.create_user('coachp', password='geheim123')
        coach.groups.add(Group.objects.get(name='Coaches'))
        c = self._client('coachp')
        with self.captureOnCommitCallbacks(execute=True):
            r = self._post(c, '/api/mededeling-opslaan/', {'titel': 'Zaterdag eerder', 'tekst': '30 min', 'belangrijk': True})
        self.assertEqual(webpush.call_count, 2)
        bericht = json.loads(webpush.call_args.kwargs['data'])
        self.assertEqual(bericht['titel'], '📌 Zaterdag eerder')
        webpush.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            self._post(c, '/api/mededeling-opslaan/', {'id': r.json()['id'], 'titel': 'Aangepast'})
            self._post(c, '/api/mededeling-opslaan/', {'titel': 'Later', 'zichtbaar_vanaf': (timezone.localdate() + timedelta(days=5)).isoformat()})
        webpush.assert_not_called()

    @mock.patch('pywebpush.webpush')
    def test_persoonlijke_opdracht_alleen_naar_die_speelster(self, webpush):
        self._meld_aan(self._client(), 1, self.eva, '1234')
        self._meld_aan(self._client(), 2, self.tess, '9999')
        self._meld_aan(self._client(), 3)  # anoniem
        with self.captureOnCommitCallbacks(execute=True):
            self._post(self._client('trainer'), '/api/training/opdracht-toevoegen/', {
                'page_id': self.page.id, **self._periode(), **self.OPDRACHT, 'spelers': [self.eva.id]})
        self.assertEqual(webpush.call_count, 1)
        self.assertEqual(webpush.call_args.args[0]['endpoint'], _sub(1)['endpoint'])
        self.assertIn('voor jou', json.loads(webpush.call_args.kwargs['data'])['titel'])

    @mock.patch('pywebpush.webpush')
    def test_verlopen_abonnement_wordt_opgeruimd(self, webpush):
        from pywebpush import WebPushException
        webpush.side_effect = WebPushException('weg', response=mock.Mock(status_code=410))
        self._meld_aan(self._client(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            _push.stuur('Test', 'tekst')
        self.assertFalse(PushAbonnement.objects.exists())

    @mock.patch('pywebpush.webpush')
    def test_herinnering_dag_voor_deadline(self, webpush):
        morgen = timezone.localdate() + timedelta(days=1)
        o = Opdracht.objects.create(titel='Conditietest', begin=timezone.localdate() - timedelta(days=3), eind=morgen)
        self._meld_aan(self._client(), 1, self.eva, '1234')
        self._meld_aan(self._client(), 2, self.tess, '9999')
        Afvinking.objects.create(speler=self.tess, opdracht=o, week=o.afvink_week(week_start(timezone.localdate())))
        with self.captureOnCommitCallbacks(execute=True):
            call_command('stuur_herinneringen', stdout=open(__import__('os').devnull, 'w'))
        self.assertEqual(webpush.call_count, 1)  # alleen Eva, Tess is klaar
        self.assertEqual(webpush.call_args.args[0]['endpoint'], _sub(1)['endpoint'])
        self.assertIn('deadline morgen', json.loads(webpush.call_args.kwargs['data'])['tekst'])

    def test_service_worker_toont_meldingen(self):
        js = Client().get('/sw.js').content.decode()
        self.assertIn("addEventListener('push'", js)
        self.assertIn("addEventListener('notificationclick'", js)



# ---------------------------------------------------------------------------
# Statistieken
# ---------------------------------------------------------------------------
from datetime import date as _sdate
from datetime import datetime as _sdt

from django.contrib.auth.models import Group as _Group
from django.contrib.auth.models import Permission as _Permission
from django.core.cache import cache as _cache
from wagtail.models import GroupPagePermission as _GroupPagePermission

from home.models import Speler as _Speler
from home.models import StatActie, StatsPage, Wedstrijd, tegenstander_uit_titel
from home.stats import Regel, tel


class StatsOpzet(TestCase):
    def setUp(self):
        root = Page.get_first_root_node()
        Site.objects.all().delete()
        self.home = HomePage(title='Home', slug='stats-home', koptekst='x')
        root.add_child(instance=self.home)
        Site.objects.create(hostname='testserver', root_page=self.home, is_default_site=True)
        self.page = StatsPage(title='Statistieken', slug='statistieken')
        self.home.add_child(instance=self.page)

        self.zoe = get_user_model().objects.create_user('zoe', password='geheim-123')
        groep, _ = _Group.objects.get_or_create(name='Stats-test')
        for code in ('change_page', 'publish_page'):
            _GroupPagePermission.objects.create(
                group=groep, page=self.page,
                permission=_Permission.objects.get(codename=code, content_type__app_label='wagtailcore'))
        self.zoe.groups.add(groep)
        self.anders = get_user_model().objects.create_user('anders', password='geheim-123')

        self.a = _Speler.objects.create(naam='Anna', rugnummer=4)
        self.b = _Speler.objects.create(naam='Bo', rugnummer=7)
        self.w1 = Wedstrijd.objects.create(datum=_sdate(2026, 10, 3), tegenstander='BC Leiden', thuis=True)
        self.w2 = Wedstrijd.objects.create(datum=_sdate(2026, 10, 10), tegenstander='Tonego', thuis=False)
        self.n = 0
        _cache.delete('stats-ical-games')

    def actie(self, w, speler, kwart, soort):
        self.n += 1
        return StatActie.objects.create(wedstrijd=w, speler=speler, kwart=kwart, soort=soort,
                                        client_id=f'test-{self.n:06d}')

    def post(self, url, data, user=None):
        c = Client()
        if user:
            c.force_login(user)
        return c.post(url, json.dumps({'page_id': self.page.id, **data}), content_type='application/json')


class StatsRekenTests(StatsOpzet):
    def test_box_score(self):
        for s in ('2r', '2r', '2m', '3r', '3m', 'fr', 'fm', 'or', 'dr', 'dr', 'as', 'pf'):
            self.actie(self.w1, self.a, 1, s)
        r = tel(StatActie.objects.filter(speler=self.a))
        self.assertEqual(r.pts, 2 + 2 + 3 + 1)
        self.assertEqual(r.raak_poging('fg'), (3, 5))
        self.assertEqual(r.raak_poging('drie'), (1, 2))
        self.assertEqual(r.raak_poging('vw'), (1, 2))
        self.assertEqual(r.waarde('reb'), 3)
        cellen = r.cellen()
        self.assertEqual(cellen[0], '8')      # PTS
        self.assertEqual(cellen[1], '3/5')    # FG
        self.assertEqual(cellen[2], '60%')    # FG%

    def test_gemiddeld_en_leeg_percentage(self):
        self.assertEqual(Regel().cellen()[2], '–')
        self.actie(self.w1, self.a, 1, '2r')
        self.actie(self.w2, self.a, 1, '3r')
        r = tel(StatActie.objects.filter(speler=self.a))
        self.assertEqual(r.cellen(gemiddeld=True)[0], '2,5')

    def test_tegenstander_telt_niet_als_eigen_punten(self):
        self.actie(self.w1, None, 1, 't3')
        self.actie(self.w1, self.a, 1, '2r')
        r = tel(StatActie.objects.all())
        self.assertEqual((r.pts, r.tegen), (2, 3))

    def test_tegenstander_uit_titel(self):
        self.assertEqual(tegenstander_uit_titel('BV Amsterdam VSE-2 - BC Leiden'), 'BC Leiden')
        self.assertEqual(tegenstander_uit_titel('Tonego DSE-3 - BV Amsterdam VSE-2'), 'Tonego DSE-3')
        self.assertEqual(tegenstander_uit_titel('Oefenwedstrijd'), 'Oefenwedstrijd')
        self.assertEqual(tegenstander_uit_titel("Utrecht Bull's VSE-2 - BV Amsterdam VSE-2*"), "Utrecht Bull's VSE-2")
        self.assertEqual(tegenstander_uit_titel('BVA VSE-2 - Lions VSE-2'), 'Lions VSE-2')

    def test_thuis_of_uit(self):
        from home.models import _is_thuis
        self.assertTrue(_is_thuis('BV Amsterdam VSE-2 - BC Leiden', 'Sporthal'))
        self.assertFalse(_is_thuis("Utrecht Bull's VSE-2 - BV Amsterdam VSE-2*", 'Utrecht'))
        self.assertFalse(_is_thuis('BC Leiden - BVA VSE-2', ''))
        self.assertTrue(_is_thuis('BC Leiden - BVA VSE-2', 'Hogendorpstraat 1'))


class StatsPaginaTests(StatsOpzet):
    def test_pagina_voor_iedereen_zichtbaar_zonder_bijhoudknoppen(self):
        self.actie(self.w1, self.a, 1, '2r')
        r = Client().get(self.page.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'STATISTIEKEN')
        self.assertContains(r, 'Anna')
        self.assertNotContains(r, 'Nieuwe wedstrijd')
        self.assertFalse(r.context['kan_stats_bijhouden'])
        # Het bijhoud-scherm is alleen voor wie mag bijhouden
        r = Client().get(self.page.url + f'?bijhouden={self.w1.id}')
        self.assertNotIn('bijhouden', r.context)

    def test_filters_wedstrijd_kwart_speler(self):
        self.actie(self.w1, self.a, 1, '2r')
        self.actie(self.w1, self.a, 2, '3r')
        self.actie(self.w1, self.b, 2, 'fr')
        self.actie(self.w1, None, 2, 't2')
        self.actie(self.w2, self.a, 1, '2r')
        c = Client()

        r = c.get(self.page.url)
        self.assertEqual(r.context['team_rij']['regel'].pts, 2 + 3 + 1 + 2)
        self.assertEqual(len(r.context['per_wedstrijd']), 2)
        self.assertEqual([q['label'] for q in r.context['per_kwart']], ['Q1', 'Q2', 'Q3', 'Q4'])

        r = c.get(self.page.url + f'?wedstrijd={self.w1.id}')
        self.assertEqual((r.context['scorebord']['wij'], r.context['scorebord']['zij']), (6, 2))
        self.assertEqual(r.context['per_wedstrijd'], [])

        r = c.get(self.page.url + f'?wedstrijd={self.w1.id}&kwart=2')
        self.assertEqual(r.context['team_rij']['regel'].pts, 4)
        self.assertEqual(r.context['per_kwart'], [])

        r = c.get(self.page.url + f'?speler={self.a.id}')
        self.assertEqual([rij['regel'].label for rij in r.context['box']], ['Anna'])
        per = {w['wedstrijd'].id: w for w in r.context['per_wedstrijd']}
        self.assertEqual([w['wedstrijd'] for w in r.context['per_wedstrijd']], [self.w2, self.w1])  # nieuwste eerst
        self.assertEqual(per[self.w1.id]['cellen'][0], '5')   # Anna in de wedstrijd tegen Leiden
        self.assertEqual(per[self.w1.id]['wij'], 6)           # teamscore blijft zichtbaar

        r = c.get(self.page.url + f'?speler={self.a.id}&weergave=gem')
        self.assertEqual(r.context['box'][0]['cellen'][0], '3,5')

    def test_verlenging_alleen_als_gespeeld(self):
        self.actie(self.w1, self.a, 1, '2r')
        r = Client().get(self.page.url)
        self.assertNotIn('Verlenging', [q['label'] for q in r.context['per_kwart']])
        self.actie(self.w1, self.a, 5, '2r')
        r = Client().get(self.page.url)
        self.assertEqual(r.context['per_kwart'][-1]['label'], 'Verlenging')

    def test_onzin_filters_geven_geen_fout(self):
        r = Client().get(self.page.url + '?wedstrijd=abc&kwart=9&speler=-1&bijhouden=x')
        self.assertEqual(r.status_code, 200)

    def test_bijhoud_scherm_voor_zoe(self):
        self.actie(self.w1, self.a, 1, '2r')
        c = Client()
        c.force_login(self.zoe)
        with mock.patch('home.stats.ical_wedstrijden', return_value=[]):
            r = c.get(self.page.url)
        self.assertContains(r, 'Nieuwe wedstrijd')
        r = c.get(self.page.url + f'?bijhouden={self.w1.id}')
        self.assertEqual(r.context['bijhouden'], self.w1)
        self.assertEqual(len(r.context['bijhouden_data']['acties']), 1)
        self.assertContains(r, 'stats-live-data')

    def test_ical_suggesties(self):
        vandaag = timezone.localdate()
        games = [
            {'titel': 'BV Amsterdam VSE-2 - BC Leiden', 'datum': _sdt.combine(vandaag, _sdt.min.time()),
             'locatie': '', 'thuis_uit': 'THUIS'},
            {'titel': 'Tonego - BV Amsterdam VSE-2', 'datum': _sdt.combine(vandaag - timedelta(days=60), _sdt.min.time()),
             'locatie': '', 'thuis_uit': 'UIT'},
        ]
        c = Client()
        c.force_login(self.zoe)
        with mock.patch('home.stats.ical_wedstrijden', return_value=games):
            r = c.get(self.page.url)
        self.assertEqual([g['tegenstander'] for g in r.context['ical_suggesties']], ['BC Leiden'])
        # Al aangemaakt: dan niet meer voorstellen
        Wedstrijd.objects.create(datum=vandaag, tegenstander='BC Leiden')
        with mock.patch('home.stats.ical_wedstrijden', return_value=games):
            r = c.get(self.page.url)
        self.assertEqual(r.context['ical_suggesties'], [])


class StatsApiTests(StatsOpzet):
    def test_alleen_bevoegden_mogen_noteren(self):
        data = {'wedstrijd_id': self.w1.id, 'speler_id': self.a.id, 'kwart': 1, 'soort': '2r', 'client_id': 'abcdef12-0001'}
        self.assertEqual(self.post('/api/stats/actie/', data).status_code, 403)
        self.assertEqual(self.post('/api/stats/actie/', data, self.anders).status_code, 403)
        self.assertEqual(self.post('/api/stats/wedstrijd-opslaan/', {'tegenstander': 'X', 'datum': '2026-10-01'},
                                   self.anders).status_code, 403)
        self.assertEqual(self.post('/api/stats/wedstrijd-verwijderen/', {'id': self.w1.id}, self.anders).status_code, 403)
        self.assertFalse(StatActie.objects.exists())
        self.assertTrue(Wedstrijd.objects.filter(id=self.w1.id).exists())

    def test_actie_noteren_telt_niet_dubbel(self):
        data = {'wedstrijd_id': self.w1.id, 'speler_id': self.a.id, 'kwart': 2, 'soort': '3r', 'client_id': 'abcdef12-0001'}
        r1 = self.post('/api/stats/actie/', data, self.zoe)
        r2 = self.post('/api/stats/actie/', data, self.zoe)  # opnieuw verstuurd na slecht internet
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()['id'], r2.json()['id'])
        a = StatActie.objects.get()
        self.assertEqual((a.speler, a.kwart, a.soort, a.door), (self.a, 2, '3r', self.zoe))

    def test_tegenstander_zonder_speelster(self):
        r = self.post('/api/stats/actie/', {'wedstrijd_id': self.w1.id, 'speler_id': self.a.id, 'kwart': 1, 'soort': 't2',
                                            'client_id': 'abcdef12-0002'}, self.zoe)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(StatActie.objects.get().speler)

    def test_ongeldige_acties(self):
        basis = {'wedstrijd_id': self.w1.id, 'speler_id': self.a.id, 'kwart': 1, 'soort': '2r', 'client_id': 'abcdef12-0003'}
        for fout in ({'soort': 'xx'}, {'kwart': 6}, {'kwart': '1'}, {'speler_id': None}, {'client_id': 'kort'},
                     {'client_id': '<script>alert(1)</script>'}):
            r = self.post('/api/stats/actie/', {**basis, **fout}, self.zoe)
            self.assertEqual(r.status_code, 400, fout)
        self.assertEqual(self.post('/api/stats/actie/', {**basis, 'wedstrijd_id': 999}, self.zoe).status_code, 404)
        self.assertFalse(StatActie.objects.exists())

    def test_client_id_van_andere_wedstrijd(self):
        self.actie(self.w2, self.a, 1, '2r')
        r = self.post('/api/stats/actie/', {'wedstrijd_id': self.w1.id, 'speler_id': self.a.id, 'kwart': 1, 'soort': '2r',
                                            'client_id': 'test-000001'}, self.zoe)
        self.assertEqual(r.status_code, 400)

    def test_actie_verwijderen(self):
        a = self.actie(self.w1, self.a, 1, '2r')
        r = self.post('/api/stats/actie-verwijderen/', {'wedstrijd_id': self.w1.id, 'client_id': a.client_id}, self.zoe)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(StatActie.objects.exists())
        # Nog een keer: is al weg, maar dat is prima
        r = self.post('/api/stats/actie-verwijderen/', {'wedstrijd_id': self.w1.id, 'client_id': a.client_id}, self.zoe)
        self.assertEqual(r.status_code, 200)

    def test_wedstrijd_aanmaken_wijzigen_verwijderen(self):
        r = self.post('/api/stats/wedstrijd-opslaan/', {'tegenstander': ' Lions ', 'datum': '2026-11-14', 'thuis': False}, self.zoe)
        self.assertEqual(r.status_code, 200)
        w = Wedstrijd.objects.get(id=r.json()['id'])
        self.assertEqual((w.tegenstander, w.datum, w.thuis), ('Lions', _sdate(2026, 11, 14), False))

        self.post('/api/stats/wedstrijd-opslaan/', {'id': w.id, 'tegenstander': 'Lions 2', 'datum': '2026-11-15', 'thuis': True}, self.zoe)
        w.refresh_from_db()
        self.assertEqual((w.tegenstander, w.thuis), ('Lions 2', True))

        self.assertEqual(self.post('/api/stats/wedstrijd-opslaan/', {'tegenstander': '', 'datum': '2026-11-14'}, self.zoe).status_code, 400)
        self.assertEqual(self.post('/api/stats/wedstrijd-opslaan/', {'tegenstander': 'X', 'datum': 'gisteren'}, self.zoe).status_code, 400)

        self.actie(w, self.a, 1, '2r')
        self.assertEqual(self.post('/api/stats/wedstrijd-verwijderen/', {'id': w.id}, self.zoe).status_code, 200)
        self.assertFalse(Wedstrijd.objects.filter(id=w.id).exists())
        self.assertFalse(StatActie.objects.filter(wedstrijd_id=w.id).exists())

    def test_zoe_kan_inloggen_op_de_pagina(self):
        def login(naam):
            return Client().post('/api/coach-inloggen/', json.dumps(
                {'page_id': self.page.id, 'gebruikersnaam': naam, 'wachtwoord': 'geheim-123'}), content_type='application/json')
        self.assertEqual(login('zoe').status_code, 200)
        self.assertEqual(login('anders').status_code, 403)


class StatsFilmEnHomepageTests(StatsOpzet):
    def setUp(self):
        super().setUp()
        self.archief = WedstrijdenArchiefPage(title='Wedstrijden', slug='wedstrijden-stats')
        self.home.add_child(instance=self.archief)
        self.archief.wedstrijden = [
            ('wedstrijd', {'titel': 'BV Amsterdam VSE-2 - BC Leiden', 'datum_str': '4 oktober 2026', 'uitslag': '53 - 36',
                           'youtube_url': 'https://youtu.be/abc123'}),
            ('wedstrijd', {'titel': 'Tonego - BV Amsterdam VSE-2', 'datum_str': '11 oktober 2026', 'uitslag': '40 - 44',
                           'youtube_url': 'https://youtu.be/def456'}),
        ]
        self.archief.save_revision().publish()
        self.archief.refresh_from_db()
        self.film_leiden = self.archief.wedstrijden[0].id

    def test_archief_films(self):
        from home.stats import archief_films
        films = list(archief_films().values())
        self.assertEqual([f['tegenstander'] for f in films], ['Tonego', 'BC Leiden'])  # nieuwste eerst
        leiden = films[1]
        self.assertEqual((leiden['datum'], leiden['thuis']), ('2026-10-04', True))
        self.assertFalse(films[0]['thuis'])
        self.assertEqual(leiden['embed_url'], 'https://www.youtube-nocookie.com/embed/abc123')
        self.assertTrue(leiden['archief_url'].endswith('?wedstrijd=0'))

    def test_wedstrijd_koppelen_aan_film(self):
        r = self.post('/api/stats/wedstrijd-opslaan/', {'tegenstander': 'BC Leiden', 'datum': '2026-10-04', 'thuis': True,
                                                        'film_block_id': self.film_leiden}, self.zoe)
        self.assertEqual(r.status_code, 200)
        w = Wedstrijd.objects.get(id=r.json()['id'])
        self.assertEqual(w.film_block_id, self.film_leiden)

        r = self.post('/api/stats/wedstrijd-opslaan/', {'tegenstander': 'X', 'datum': '2026-10-04', 'film_block_id': 'bestaat-niet'}, self.zoe)
        self.assertEqual(r.status_code, 400)

        # Bijhouden toont de video; gekoppelde film wordt niet meer voorgesteld
        c = Client()
        c.force_login(self.zoe)
        r = c.get(self.page.url + f'?bijhouden={w.id}')
        self.assertContains(r, 'youtube-nocookie.com/embed/abc123')
        self.assertContains(r, 'met-film')
        with mock.patch('home.stats.ical_wedstrijden', return_value=[]):
            r = c.get(self.page.url)
        self.assertEqual([f['tegenstander'] for f in r.context['film_suggesties']], ['Tonego'])
        self.assertEqual(len(r.context['films']), 2)

        # Overzicht van die wedstrijd linkt naar de film
        r = Client().get(self.page.url + f'?wedstrijd={w.id}')
        self.assertContains(r, 'Film bekijken')

    def test_zonder_film_geen_video(self):
        c = Client()
        c.force_login(self.zoe)
        r = c.get(self.page.url + f'?bijhouden={self.w1.id}')
        self.assertNotContains(r, 'youtube-nocookie')
        self.assertNotContains(r, 'met-film')

    def test_homepage_blok(self):
        r = Client().get(self.home.url)
        self.assertContains(r, 'Stats per wedstrijd')
        self.assertContains(r, 'Nog geen stats')
        self.assertContains(r, 'Bekijk alle stats')
        self.assertNotContains(r, 'Nieuwe wedstrijd bijhouden')

        self.actie(self.w2, self.a, 1, '3r')
        self.actie(self.w2, self.b, 1, '2r')
        self.actie(self.w2, None, 1, 't2')
        c = Client()
        c.force_login(self.zoe)
        r = c.get(self.home.url)
        self.assertEqual(r.context['stats_laatste'], self.w2)
        self.assertEqual(r.context['stats_score'], (5, 2))
        self.assertEqual(r.context['stats_topscorer'], (self.a, 3))
        # Ook voor Zoë alleen de knop naar het overzicht (bijhouden doet ze op de statistiekenpagina)
        self.assertContains(r, 'Bekijk alle stats')
        self.assertNotContains(r, 'Nieuwe wedstrijd bijhouden')


class DatabaseOpslagTests(TestCase):
    """Foto's in de database (voor een server zonder blijvende schijf)."""

    def test_foto_uploaden_rendition_en_tonen(self):
        from django.core.files.images import ImageFile
        from django.core.files.storage import storages
        from django.test import RequestFactory, override_settings
        from wagtail.images import get_image_model

        from home.models import Bestand
        from home.opslag import DatabaseOpslag, toon_bestand

        from django.conf import settings
        opslag = {**settings.STORAGES, 'default': {'BACKEND': 'home.opslag.DatabaseOpslag'}}
        with override_settings(STORAGES=opslag):
            storages._storages = {}
            try:
                self.assertIsInstance(storages['default'], DatabaseOpslag)
                img = get_image_model().objects.create(title='Teamfoto', file=ImageFile(_test_foto('team.png').file, name='team.png'))
                self.assertTrue(Bestand.objects.filter(naam=img.file.name).exists())
                self.assertEqual((img.width, img.height), (40, 40))
                r = img.get_rendition('fill-10x10')
                self.assertTrue(Bestand.objects.filter(naam=r.file.name).exists())
                self.assertTrue(r.url.startswith('/media/'))

                resp = toon_bestand(RequestFactory().get(r.url), r.file.name)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp['Content-Type'], 'image/png')
                self.assertTrue(resp.content.startswith(b'\x89PNG'))

                with self.captureOnCommitCallbacks(execute=True):  # Wagtail wist bestanden pas na de commit
                    img.delete()
                self.assertFalse(Bestand.objects.filter(naam=img.file.name).exists())
            finally:
                storages._storages = {}

    def test_onbekend_bestand_geeft_404(self):
        from django.http import Http404
        from django.test import RequestFactory
        from home.opslag import toon_bestand
        with self.assertRaises(Http404):
            toon_bestand(RequestFactory().get('/media/x.png'), 'x.png')


class BeveiligingTests(StatsFilmEnHomepageTests):
    """Alleen wie iets mag, kan het ook: reacties als coach en de inlogblokkade."""

    def setUp(self):
        super().setUp()
        cache.clear()
        from django.contrib.auth.models import Permission
        self.coach = get_user_model().objects.create_user('coachtest', password='coach-wachtwoord-1')
        self.coach.user_permissions.add(Permission.objects.get(codename='access_admin'))

    def _reactie(self, client, rol):
        return client.post('/api/sla-reactie/', json.dumps({
            'page_id': self.archief.id, 'block_id': self.film_leiden, 'auteur': 'Anniko', 'rol': rol, 'tekst': 'Goed gespeeld',
        }), content_type='application/json')

    def test_alleen_ingelogde_coach_reageert_als_coach(self):
        self.assertEqual(self._reactie(Client(), 'coach').status_code, 403)
        self.assertEqual(self._reactie(Client(), 'teammate').status_code, 200)
        c = Client()
        c.force_login(self.coach)
        self.assertEqual(self._reactie(c, 'coach').status_code, 200)
        self.assertEqual(list(WedstrijdReactie.objects.order_by('id').values_list('rol', flat=True)), ['teammate', 'coach'])
        # De keuze "Coach" staat alleen in het formulier voor wie ingelogd is
        self.assertNotContains(Client().get(self.archief.url), '<option value="coach">')
        self.assertContains(c.get(self.archief.url), '<option value="coach">')

    def test_admin_login_geblokkeerd_na_te_veel_pogingen_ook_vanaf_andere_adressen(self):
        for i in range(10):
            Client(REMOTE_ADDR=f'10.1.0.{i}').post('/admin/login/', {'username': 'zoe', 'password': 'fout'})
        r = Client(REMOTE_ADDR='10.9.9.9').post('/admin/login/', {'username': 'zoe', 'password': 'geheim-123'})
        self.assertEqual(r.status_code, 429)
        # Ook het inlogvenster op de site zelf is dan geblokkeerd voor dit account
        r = Client(REMOTE_ADDR='10.9.9.8').post('/api/coach-inloggen/', json.dumps(
            {'page_id': self.page.id, 'gebruikersnaam': 'zoe', 'wachtwoord': 'geheim-123'}), content_type='application/json')
        self.assertEqual(r.status_code, 429)
        # Een ander account heeft er geen last van
        r = Client(REMOTE_ADDR='10.9.9.7').post('/admin/login/', {'username': 'coachtest', 'password': 'coach-wachtwoord-1'})
        self.assertEqual(r.status_code, 302)

    def test_goede_login_wist_de_teller(self):
        for _ in range(9):
            Client().post('/admin/login/', {'username': 'zoe', 'password': 'fout'})
        self.assertEqual(Client().post('/admin/login/', {'username': 'zoe', 'password': 'geheim-123'}).status_code, 302)
        for _ in range(9):
            Client().post('/admin/login/', {'username': 'zoe', 'password': 'fout'})
        self.assertEqual(Client().post('/admin/login/', {'username': 'zoe', 'password': 'geheim-123'}).status_code, 302)

    def test_echt_ip_achter_proxy(self):
        from django.test import RequestFactory, override_settings
        from home.beveiliging import client_ip
        rf = RequestFactory()
        verzoek = rf.get('/', REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='6.6.6.6, 81.2.3.4')
        self.assertEqual(client_ip(verzoek), '10.0.0.1')  # lokaal: geen proxy
        with override_settings(ACHTER_PROXY=True):
            self.assertEqual(client_ip(verzoek), '81.2.3.4')  # niet het vervalsbare eerste adres
            self.assertEqual(client_ip(rf.get('/', HTTP_CF_CONNECTING_IP='81.9.9.9', REMOTE_ADDR='10.0.0.1')), '81.9.9.9')


class InloggenZonderHoofdletterTests(BeveiligingTests):
    """Telefoons maken de eerste letter een hoofdletter: inloggen moet dan nog steeds lukken."""

    def test_naam_met_hoofdletters_of_spaties(self):
        for naam in ('zoe', 'Zoe', 'ZOE', ' Zoe '):
            r = Client().post('/api/coach-inloggen/', json.dumps(
                {'page_id': self.page.id, 'gebruikersnaam': naam, 'wachtwoord': 'geheim-123'}), content_type='application/json')
            self.assertEqual(r.status_code, 200, naam)
        self.assertEqual(Client().post('/admin/login/', {'username': 'Coachtest', 'password': 'coach-wachtwoord-1'}).status_code, 302)
        # Het wachtwoord blijft hoofdlettergevoelig
        r = Client().post('/api/coach-inloggen/', json.dumps(
            {'page_id': self.page.id, 'gebruikersnaam': 'Zoe', 'wachtwoord': 'Geheim-123'}), content_type='application/json')
        self.assertEqual(r.status_code, 401)

    def test_blokkade_telt_ook_met_andere_hoofdletters(self):
        for i, naam in enumerate(['zoe', 'Zoe', 'ZOE', 'zOe', 'ZoE'] * 2):
            Client(REMOTE_ADDR=f'10.2.0.{i}').post('/admin/login/', {'username': naam, 'password': 'fout'})
        self.assertEqual(Client(REMOTE_ADDR='10.2.9.9').post('/admin/login/', {'username': 'zoe', 'password': 'geheim-123'}).status_code, 429)

    def test_inlogveld_zonder_automatische_hoofdletter(self):
        self.assertContains(Client().get(self.page.url), 'autocapitalize="none"')

    def test_naam_zonder_accenten(self):
        get_user_model().objects.create_user('Anaïs', password='test-ww-4821')
        from django.contrib.auth import authenticate
        for naam in ('Anaïs', 'anaïs', 'ANAÏS', 'Anais', 'anais ', 'ANAIS'):
            self.assertIsNotNone(authenticate(username=naam, password='test-ww-4821'), naam)
        self.assertIsNone(authenticate(username='Anais', password='fout'))


class WachtwoordBeheerTests(TestCase):
    """De coach wijzigt op de teampagina wachtwoorden: eigen, trainers en stats. Nooit beheerder of andere coach."""

    def setUp(self):
        from django.contrib.auth.models import Group
        cache.clear()
        root = Page.get_first_root_node()
        Site.objects.all().delete()
        home = HomePage(title='Home', slug='ww-home', koptekst='x')
        root.add_child(instance=home)
        Site.objects.create(hostname='testserver', root_page=home, is_default_site=True)
        self.team = TeamPage(title='Ons team', slug='team')
        home.add_child(instance=self.team)
        U = get_user_model()
        maak = lambda naam, *groepen: self._lid(U.objects.create_user(naam, password='oud-wachtwoord-1'), groepen)
        self.coach = maak('coach1', 'Coaches', 'Trainers')
        self.coach2 = maak('coach2', 'Coaches')
        self.trainer = maak('trainer1', 'Trainers')
        self.stats = maak('stats1', 'Statistieken')
        self.los = maak('bezoeker1')
        self.admin = U.objects.create_superuser('baas', '', 'oud-wachtwoord-1')

    def _lid(self, user, groepen):
        from django.contrib.auth.models import Group
        for g in groepen:
            user.groups.add(Group.objects.get_or_create(name=g)[0])
        return user

    def _wijzig(self, client, doel, ww='Nieuw-ww-2026'):
        return client.post('/api/team/wachtwoord/', json.dumps({'user_id': doel.id, 'wachtwoord': ww}), content_type='application/json')

    def _client(self, user):
        c = Client(); c.force_login(user); return c

    def test_coach_wijzigt_eigen_trainers_en_stats(self):
        c = self._client(self.coach)
        for doel in (self.coach, self.trainer, self.stats):
            self.assertEqual(self._wijzig(c, doel).status_code, 200, doel.username)
            doel.refresh_from_db()
            self.assertTrue(doel.check_password('Nieuw-ww-2026'))
        # Na het wijzigen van je eigen wachtwoord blijf je ingelogd
        self.assertEqual(self._wijzig(c, self.trainer, 'Nog-een-2026').status_code, 200)

    def test_coach_niet_bij_beheerder_of_andere_coach(self):
        c = self._client(self.coach)
        for doel in (self.admin, self.coach2, self.los):
            self.assertEqual(self._wijzig(c, doel).status_code, 403, doel.username)
            doel.refresh_from_db()
            self.assertTrue(doel.check_password('oud-wachtwoord-1'))

    def test_trainer_en_bezoeker_mogen_niets(self):
        for actor in (self.trainer, self.stats, self.los):
            self.assertEqual(self._wijzig(self._client(actor), self.trainer).status_code, 403, actor.username)
        self.assertEqual(self._wijzig(Client(), self.trainer).status_code, 403)

    def test_te_makkelijk_wachtwoord(self):
        c = self._client(self.coach)
        for ww in ('kort', '12345678', 'password'):
            self.assertEqual(self._wijzig(c, self.trainer, ww).status_code, 400, ww)

    def test_teampagina_toont_alleen_toegestane_accounts(self):
        r = self._client(self.coach).get(self.team.url)
        namen = [a['naam'] for a in r.context['accounts']]
        self.assertEqual(namen[0], 'coach1')  # eigen account eerst
        self.assertEqual(set(namen), {'coach1', 'trainer1', 'stats1'})
        self.assertContains(r, 'Accounts en wachtwoorden')
        r = self._client(self.trainer).get(self.team.url)
        self.assertEqual(r.context['accounts'], [])
        self.assertNotContains(r, 'Accounts en wachtwoorden')

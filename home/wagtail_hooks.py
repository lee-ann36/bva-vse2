from wagtail import hooks
from wagtail.admin.ui.tables import BooleanColumn
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from .models import Mededeling, Opdracht, Speler, Wedstrijd


class SpelerViewSet(SnippetViewSet):
    """Zet 'Spelers' als eigen menu-item in de Wagtail-admin."""
    model = Speler
    icon = 'group'
    menu_label = 'Spelers'
    menu_order = 200
    add_to_admin_menu = True
    list_display = ['naam', 'rugnummer', 'positie', 'actief', BooleanColumn('heeft_pincode', label='Pincode')]
    list_filter = ['actief', 'positie']
    search_fields = ['naam']
    ordering = ['rugnummer', 'naam']


class OpdrachtViewSet(SnippetViewSet):
    """Trainingsopdrachten, voor trainers om te bewerken."""
    model = Opdracht
    icon = 'tasks'
    menu_label = 'Trainingsopdrachten'
    menu_order = 210
    add_to_admin_menu = True
    list_display = ['titel', 'categorie', 'voor_wie_tekst', 'begin', 'eind', BooleanColumn('herhalend')]
    list_filter = ['categorie', 'herhalend']
    search_fields = ['titel', 'uitleg']
    ordering = ['-begin', 'titel']


class MededelingViewSet(SnippetViewSet):
    """Mededelingen op de homepage, voor coaches en trainers."""
    model = Mededeling
    icon = 'info-circle'
    menu_label = 'Mededelingen'
    menu_order = 190
    add_to_admin_menu = True
    list_display = ['titel', BooleanColumn('belangrijk'), 'zichtbaar_vanaf', 'zichtbaar_tot', 'auteur']
    list_filter = ['belangrijk']
    search_fields = ['titel', 'tekst']
    ordering = ['-aangemaakt']


class WedstrijdViewSet(SnippetViewSet):
    """Wedstrijden waarvan statistieken worden bijgehouden (de acties zelf noteer je op de site)."""
    model = Wedstrijd
    icon = 'table'
    menu_label = 'Stats-wedstrijden'
    menu_order = 220
    add_to_admin_menu = True
    list_display = ['datum', 'tegenstander', BooleanColumn('thuis')]
    search_fields = ['tegenstander']
    ordering = ['-datum']


register_snippet(MededelingViewSet)
register_snippet(WedstrijdViewSet)
register_snippet(SpelerViewSet)
register_snippet(OpdrachtViewSet)


@hooks.register('after_create_snippet')
def onthoud_schrijver(request, instance):
    """Sla op wie een mededeling of opdracht via de admin heeft aangemaakt."""
    if isinstance(instance, (Mededeling, Opdracht)) and instance.aangemaakt_door_id is None:
        instance.aangemaakt_door = request.user
        instance.save(update_fields=['aangemaakt_door'])

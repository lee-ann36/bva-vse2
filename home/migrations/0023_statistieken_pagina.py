"""
Maakt de pagina 'Statistieken' (onder de homepage) en de groep 'Statistieken' aan.
Wie in die groep zit (of Coaches), mag op de pagina statistieken bijhouden.
"""
import uuid

from django.db import migrations

ALFABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
STAP = 4


def _volgende_pad(laatste_pad, ouder_pad):
    if not laatste_pad:
        return ouder_pad + '0001'
    n = 0
    for teken in laatste_pad[-STAP:]:
        n = n * len(ALFABET) + ALFABET.index(teken)
    n += 1
    stap = ''
    for _ in range(STAP):
        n, rest = divmod(n, len(ALFABET))
        stap = ALFABET[rest] + stap
    return laatste_pad[:-STAP] + stap


def maak_pagina_en_groep(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    Page = apps.get_model('wagtailcore', 'Page')
    GroupPagePermission = apps.get_model('wagtailcore', 'GroupPagePermission')
    HomePage = apps.get_model('home', 'HomePage')
    StatsPage = apps.get_model('home', 'StatsPage')

    home = HomePage.objects.order_by('path').first()
    if home is None or StatsPage.objects.exists():
        return
    if Page.objects.filter(path__startswith=home.path, depth=home.depth + 1, slug='statistieken').exists():
        return

    laatste = (Page.objects.filter(path__startswith=home.path, depth=home.depth + 1)
               .order_by('-path').values_list('path', flat=True).first())
    ct, _ = ContentType.objects.get_or_create(app_label='home', model='statspage')
    pagina = StatsPage.objects.create(
        title='Statistieken', draft_title='Statistieken', slug='statistieken',
        content_type=ct, path=_volgende_pad(laatste, home.path), depth=home.depth + 1, numchild=0,
        url_path=f'{home.url_path}statistieken/', live=True, has_unpublished_changes=False,
        locale_id=home.locale_id, translation_key=uuid.uuid4(),
    )
    Page.objects.filter(id=home.id).update(numchild=home.numchild + 1)

    page_ct, _ = ContentType.objects.get_or_create(app_label='wagtailcore', model='page')
    rechten = []
    for codename, naam in (('change_page', 'Can change page'), ('publish_page', 'Can publish page')):
        perm, _ = Permission.objects.get_or_create(content_type=page_ct, codename=codename, defaults={'name': naam})
        rechten.append(perm)

    groep, _ = Group.objects.get_or_create(name='Statistieken')
    groepen = [groep] + list(Group.objects.filter(name='Coaches'))
    for g in groepen:
        for perm in rechten:
            GroupPagePermission.objects.get_or_create(group=g, page_id=pagina.id, permission=perm)


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0022_statistieken'),
    ]

    operations = [
        migrations.RunPython(maak_pagina_en_groep, migrations.RunPython.noop),
    ]

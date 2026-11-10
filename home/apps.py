from django.apps import AppConfig


class HomeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "home"

    def ready(self):
        from . import beveiliging  # noqa: F401  (koppelt de tellers voor foute inlogpogingen)

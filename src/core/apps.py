from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "Base"

    def ready(self):
        from core import connexions  # noqa: F401  (limitation des essais de connexion)
        from core import journal

        journal.brancher()  # journal des actions (K4)
        from core.admin_fr import franciser

        franciser()  # titres de l'administration (l'app admin a déjà chargé tous les admin.py)

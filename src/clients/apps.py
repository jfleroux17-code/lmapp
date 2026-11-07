from django.apps import AppConfig


class ClientsConfig(AppConfig):
    name = "clients"
    verbose_name = "Clients"

    def ready(self):
        from clients import signals  # noqa: F401  (géocodage automatique)

"""Dernier avis raccourci pour tenir dans un texto de 201 caractères (décision de JF, 11 novembre 2026).
Changé seulement si JF n'avait pas modifié le texte par défaut."""
from django.db import migrations

ANCIEN = ("Bonjour {client}, dernier avis : le solde de {montant} ({factures}) est impayé depuis le {depuis}. "
          "Merci de le régler sans tarder, ou de nous appeler si le paiement pose problème. {paiement}")
NOUVEAU = ("Bonjour {client}, dernier avis : le solde de {montant} ({factures}) est impayé depuis le {depuis}. "
           "Merci de le régler sans tarder ou de nous appeler. {paiement}")


def raccourcir(apps, schema_editor):
    apps.get_model("communications", "GabaritParDefaut").objects.filter(genre="relance_3", texte=ANCIEN).update(texte=NOUVEAU)


def remettre(apps, schema_editor):
    apps.get_model("communications", "GabaritParDefaut").objects.filter(genre="relance_3", texte=NOUVEAU).update(texte=ANCIEN)


class Migration(migrations.Migration):
    dependencies = [("communications", "0015_photos_jointes")]
    operations = [migrations.RunPython(raccourcir, remettre)]

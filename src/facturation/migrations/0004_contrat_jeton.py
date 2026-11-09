import secrets

from django.db import migrations, models

import facturation.models


def remplir(apps, schema_editor):
    Contrat = apps.get_model("facturation", "Contrat")
    for c in Contrat.objects.filter(jeton=None):
        c.jeton = secrets.token_urlsafe(24)
        c.save(update_fields=["jeton"])


class Migration(migrations.Migration):
    """Lien public du contrat (B6) : jeton propre à chaque contrat, en trois temps (ajout, remplissage, unicité)."""

    dependencies = [("facturation", "0003_facture_consultee")]

    operations = [
        migrations.AddField(model_name="contrat", name="jeton", field=models.CharField(max_length=40, null=True, editable=False)),
        migrations.RunPython(remplir, migrations.RunPython.noop),
        migrations.AlterField(model_name="contrat", name="jeton",
                              field=models.CharField(default=facturation.models._jeton, editable=False, max_length=40, unique=True)),
        migrations.AlterField(model_name="contrat", name="notes",
                              field=models.TextField(blank=True, help_text="Notes internes : jamais sur le contrat remis au client.")),
    ]

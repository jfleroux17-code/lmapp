# Extension PostgreSQL « unaccent » : la recherche ignore les accents
# (« cote » trouve « Côté »). Ajoute une extension, ne touche à aucune donnée.
from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("clients", "0002_adresse_geocodage_note_adresse_position_precision")]
    operations = [UnaccentExtension()]

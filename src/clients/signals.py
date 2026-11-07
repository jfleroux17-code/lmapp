"""Géocodage automatique : une adresse créée, ou dont la rue, la ville ou le code
postal change, est mise en file pour le worker, après la fin de la transaction."""
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from clients.models import Adresse

CHAMPS_ADRESSE = ("ligne1", "ville", "province", "code_postal")


@receiver(pre_save, sender=Adresse)
def _noter_changement(sender, instance, update_fields=None, **kwargs):
    instance._a_geocoder = False
    if update_fields is not None and not set(update_fields) & set(CHAMPS_ADRESSE):
        return  # sauvegarde partielle (ex. résultat du géocodage) : rien à faire
    if instance.position_source in (Adresse.SourcePosition.MANUELLE, Adresse.SourcePosition.GPS):
        return
    if instance.pk is None:
        instance._a_geocoder = instance.position is None
        return
    avant = Adresse.objects.filter(pk=instance.pk).values(*CHAMPS_ADRESSE).first()
    if avant is None or any(avant[c] != getattr(instance, c) for c in CHAMPS_ADRESSE):
        instance._a_geocoder = True


@receiver(post_save, sender=Adresse)
def _mettre_en_file(sender, instance, **kwargs):
    if getattr(instance, "_a_geocoder", False):
        from clients.tasks import geocoder_adresse

        pk = instance.pk
        transaction.on_commit(lambda: geocoder_adresse.defer(adresse_id=pk))

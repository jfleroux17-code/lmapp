#!/bin/sh
# Met les alertes de la surveillance en silence pendant un déploiement ou une mise en service.
#
#   sh /srv/lmapp/outils/silence.sh 30   # silence de 30 minutes (au plus 240)
#   sh /srv/lmapp/outils/silence.sh 0    # fin du silence tout de suite
#
# Les vérifications continuent : une panne qui dure encore à la fin du silence est signalée normalement.
# Voir core/surveillance.py. Lu par le service « surveillance » (dossier etat/, monté en lecture seule).
set -eu
MIN="${1:?Nombre de minutes (0 pour finir le silence)}"
case "$MIN" in *[!0-9]*) echo "Un nombre de minutes, svp."; exit 1;; esac
[ "$MIN" -le 240 ] || { echo "Au plus 240 minutes : une surveillance muette trop longtemps ne surveille plus."; exit 1; }
DOSSIER=/srv/lmapp/etat
mkdir -p "$DOSSIER"
FIN=$(( $(date +%s) + MIN * 60 ))
echo "$FIN" > "$DOSSIER/silence_jusqu_a.tmp" && mv "$DOSSIER/silence_jusqu_a.tmp" "$DOSSIER/silence_jusqu_a"
if [ "$MIN" -eq 0 ]; then echo "Silence fini : les alertes partent de nouveau."; else echo "Alertes en silence jusqu'à $(date -d "@$FIN" +%H:%M)."; fi

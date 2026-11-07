#!/bin/sh
# Sauvegarde de la base de prod (PRD K3), lancée par le service « sauvegarde »
# de compose.yaml (image postgis : pg_dump de même version que la base).
# Écrit dans /srv/lmapp/sauvegardes, que COVE copie hors de ld1 toutes les
# 12 heures : en sauvegardant aussi toutes les 12 heures, COVE emporte
# toujours une copie de moins de 12 heures, quelle que soit son heure.
#
#   - une sauvegarde à chaque heure de SAUVEGARDE_HEURES (« 03:30 15:30 » par
#     défaut : hors de la plage de 2 h à 3 h que les changements d'heure
#     sautent ou répètent);
#   - rattrapage au démarrage si la dernière réussite date de plus de 14 h;
#   - fichier vérifié (lisible par pg_restore) avant d'être gardé;
#   - on garde les SAUVEGARDE_GARDER plus récentes (28 : 14 jours), et les 10 plus
#     récentes « avant déploiement ». Nettoyage par nombre, pas par âge : si
#     les sauvegardes échouaient, on ne perdrait pas les dernières bonnes.
set -eu

HEURES="${SAUVEGARDE_HEURES:-03:30 15:30}"
GARDER="${SAUVEGARDE_GARDER:-28}"
RATTRAPAGE_H=14
RACINE=/sauvegardes
DOSSIER="$RACINE/nocturnes"
umask 077

journal() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$RACINE/journal.log"
}

garder_les_plus_recents() {  # dossier, motif, nombre
    ls -1t "$1"/$2 2>/dev/null | tail -n +"$(( $3 + 1 ))" | while read -r vieux; do
        rm -f -- "$vieux" && journal "nettoyage : $(basename "$vieux") retiré"
    done
}

sauvegarder() {
    mkdir -p "$DOSSIER"
    f="$DOSSIER/lmapp_$(date +%Y%m%d-%H%M%S).dump"
    if pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$f.partiel" \
        && n=$(pg_restore --list "$f.partiel" | grep -c 'TABLE DATA') && [ "$n" -gt 0 ]; then
        mv "$f.partiel" "$f"
        date +%s > "$RACINE/derniere_reussite"
        journal "OK $(basename "$f") ($(wc -c < "$f") octets, $n tables)"
    else
        rm -f "$f.partiel"
        journal "ÉCHEC de la sauvegarde de la base"
        return 1
    fi
    garder_les_plus_recents "$DOSSIER" 'lmapp_*.dump' "$GARDER"
    garder_les_plus_recents "$RACINE" 'lmapp_avant-deploiement_*.dump' 10
}

prochaine() {  # secondes jusqu'à la plus proche des HEURES
    maintenant=$(date +%s)
    meilleure=""
    for h in $HEURES; do
        cible=$(date -d "today $h" +%s)
        [ "$cible" -le "$maintenant" ] && cible=$(date -d "tomorrow $h" +%s)
        if [ -z "$meilleure" ] || [ "$cible" -lt "$meilleure" ]; then meilleure=$cible; fi
    done
    echo $(( meilleure - maintenant ))
}

if [ "${1:-}" = "--prochaine" ]; then  # vérification : prochain passage, sans rien sauvegarder
    s=$(prochaine)
    echo "prochaine sauvegarde dans $s s, le $(date -d "@$(( $(date +%s) + s ))" '+%Y-%m-%d à %H:%M')"
    exit 0
fi

trap 'journal "arrêt du service de sauvegarde"; exit 0' TERM INT

journal "service de sauvegarde démarré (chaque jour à $HEURES, on garde les $GARDER plus récentes)"
derniere=$(cat "$RACINE/derniere_reussite" 2>/dev/null || echo 0)
if [ $(( $(date +%s) - derniere )) -gt $(( RATTRAPAGE_H * 3600 )) ]; then
    journal "aucune sauvegarde depuis plus de $RATTRAPAGE_H h : rattrapage maintenant"
    sauvegarder || true
fi

while true; do
    attente=$(prochaine)
    sleep "$attente" &
    wait $!
    sauvegarder || true
done

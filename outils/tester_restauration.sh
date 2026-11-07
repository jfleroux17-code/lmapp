#!/bin/sh
# Test de restauration (PRD 6.7, une fois par mois) : restaure la sauvegarde
# nocturne la plus récente dans une base PostGIS jetable, sans réseau, puis
# compare le nombre de lignes de chaque table avec la base de prod. La base
# jetable est effacée à la fin. Ne touche jamais à la base de prod (lecture).
#
#   sh /srv/lmapp/outils/tester_restauration.sh [fichier.dump]
set -eu

cd /srv/lmapp
FICHIER="${1:-$(ls -1t sauvegardes/nocturnes/lmapp_*.dump | head -1)}"
NOM="essai-restauration-$$"
echo "Sauvegarde testée : $FICHIER ($(wc -c < "$FICHIER") octets)"

docker run -d --name "$NOM" --network none -e POSTGRES_PASSWORD=jetable \
    postgis/postgis:17-3.7 >/dev/null
trap 'docker rm -f "$NOM" >/dev/null 2>&1' EXIT
i=0
until docker exec "$NOM" pg_isready -U postgres >/dev/null 2>&1; do
    i=$((i + 1)); [ "$i" -gt 60 ] && { echo "La base jetable ne démarre pas."; exit 1; }; sleep 1
done
sleep 3  # l'image PostGIS redémarre une fois après son initialisation
until docker exec "$NOM" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done

# Base vide (template0) : c'est la sauvegarde qui installe PostGIS, comme sur un serveur neuf.
# Toute erreur de restauration fait échouer le test.
docker exec "$NOM" createdb -U postgres -T template0 restauration
docker exec -i "$NOM" pg_restore -U postgres -d restauration --no-owner --no-privileges --exit-on-error < "$FICHIER"
echo "Restauration : aucune erreur."

COMPTE="select string_agg(format('select %L || '' '' || count(*) from %I', tablename, tablename), ' union all ') from pg_tables where schemaname = 'public'"
compter() {  # conteneur, utilisateur, base
    q=$(docker exec "$1" psql -U "$2" -d "$3" -Atc "$COMPTE")
    docker exec "$1" psql -U "$2" -d "$3" -Atc "select * from ($q) t order by 1"
}
docker exec "$NOM" psql -U postgres -d restauration -c "analyze" >/dev/null
compter "$NOM" postgres restauration > /tmp/restauree.$$
# Lire seulement ces deux variables du .env (jamais l'exécuter : la SECRET_KEY contient des caractères spéciaux)
PG_USER=$(sed -n 's/^POSTGRES_USER=//p' .env)
PG_DB=$(sed -n 's/^POSTGRES_DB=//p' .env)
compter lmapp-db-1 "$PG_USER" "$PG_DB" > /tmp/prod.$$

echo "Tables restaurées : $(wc -l < /tmp/restauree.$$) | tables en prod : $(wc -l < /tmp/prod.$$)"
if diff /tmp/prod.$$ /tmp/restauree.$$ > /tmp/ecarts.$$; then
    echo "RÉUSSI : même nombre de lignes dans chaque table que la prod."
    resultat=0
else
    echo "ÉCARTS (prod à gauche, restauration à droite; normal si la prod a changé depuis la sauvegarde) :"
    sed 's/^/  /' /tmp/ecarts.$$
    resultat=2
fi
echo "$(date '+%Y-%m-%d %H:%M:%S') test de restauration de $(basename "$FICHIER") : $([ $resultat -eq 0 ] && echo RÉUSSI || echo ÉCARTS)" >> sauvegardes/journal.log
rm -f /tmp/restauree.$$ /tmp/prod.$$ /tmp/ecarts.$$
exit $resultat

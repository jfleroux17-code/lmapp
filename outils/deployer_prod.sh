#!/bin/sh
# Déploiement en prod (CLAUDE.md, « Du test à la prod »), à lancer après validation en test :
#
#   sh /srv/lmapp/outils/deployer_prod.sh
#
# Dans l'ordre : sauvegarde de la base (vérifiée), construction de l'image,
# étiquette au numéro du commit (pour revenir en arrière), migrations, redémarrage,
# vérifications (santé, ports publiés). S'arrête à la première erreur.
set -eu
cd /srv/lmapp

PG_USER=$(sed -n 's/^POSTGRES_USER=//p' .env)
PG_DB=$(sed -n 's/^POSTGRES_DB=//p' .env)
COMMIT=$(git rev-parse --short HEAD)
F="sauvegardes/lmapp_avant-deploiement_$(date +%Y%m%d-%H%M%S).dump"

echo "== Alertes de la surveillance en silence (20 minutes au plus)"
sh outils/silence.sh 20

echo "== Sauvegarde avant déploiement"
(umask 077; docker compose exec -T db pg_dump -U "$PG_USER" -d "$PG_DB" -Fc > "$F")
n=$(docker compose exec -T db pg_restore --list < "$F" | grep -c 'TABLE DATA')
[ "$n" -gt 0 ] || { echo "Sauvegarde illisible : déploiement arrêté."; exit 1; }
echo "$F ($(wc -c < "$F") octets, $n tables)"

echo "== Image lmapp:latest (commit $COMMIT)"
docker compose build -q app
docker tag lmapp:latest "lmapp:$COMMIT"

echo "== Migrations"
docker compose run --rm app python manage.py migrate

echo "== Redémarrage"
docker compose up -d
sleep 8
docker compose ps --format '{{.Service}} {{.Status}}'

echo "== Vérifications"
curl -sf --resolve louis.ledeneigeur.com:443:127.0.0.1 https://louis.ledeneigeur.com/sante/ && echo
echo "Ports ouverts sur ld1 (attendu : 22, 443 et 5000 de COVE) :"
ss -tln | awk '/LISTEN/ && $4 !~ /^127\./ {print "  " $4}'
sh outils/silence.sh 5  # le temps que le worker reprenne son battement; ensuite, alertes normales
echo "Déployé : commit $COMMIT. Retour arrière possible : docker tag lmapp:<ancien commit> lmapp:latest && docker compose up -d"

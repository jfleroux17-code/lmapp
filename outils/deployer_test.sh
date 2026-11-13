#!/bin/sh
# Mise à jour de l'environnement de test (test.ledeneigeur.com) : construire, migrer, redémarrer, vérifier.
# Toujours ce script après un changement de code : un « build » + « up » sans migration casse le test
# (vu le 13 novembre 2026 : colonne manquante, toutes les pages en erreur 500).
#
#   sh /srv/lmapp/outils/deployer_test.sh
set -eu
cd /srv/lmapp/test
echo "== Construction de l'image lmapp:test"
docker compose build -q app
echo "== Migrations"
docker compose run --rm -q app python manage.py migrate --noinput
echo "== Redémarrage"
docker compose up -d
echo "== Vérifications"
EN_ATTENTE=$(docker compose run --rm -q app python manage.py showmigrations 2>/dev/null | grep -c "\[ \]" || true)
[ "$EN_ATTENTE" = "0" ] || { echo "ERREUR : $EN_ATTENTE migration(s) pas appliquée(s)"; exit 1; }
for i in 1 2 3 4 5 6 7 8 9 10; do
	if curl -sk --resolve test.ledeneigeur.com:443:127.0.0.1 https://test.ledeneigeur.com/sante/ | grep -q '"base": "ok"'; then
		echo "Test à jour : l'app et la base répondent."; exit 0
	fi
	sleep 3
done
echo "ERREUR : /sante/ ne répond pas"; exit 1

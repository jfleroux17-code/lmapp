#!/bin/sh
# Redémarrage de ld1 confirmé par courriel (audit de sécurité, point 7, choix de JF du 13 novembre 2026).
#
# Exécuté en root chaque minute par le minuteur systemd lmapp-redemarrage.timer. Installé par JF (une fois, sudo) :
#   sudo install -m 755 -o root -g root /srv/lmapp/outils/redemarrage_hote.sh /usr/local/sbin/lmapp-redemarrage
#   (copie appartenant à root : un compte ordinaire ne peut pas changer ce que root exécute)
#
# Dossier d'échange /srv/lmapp/etat/redemarrage (monté dans le conteneur « surveillance », sans aucun droit sur ld1) :
#   requis  : écrit ici quand Ubuntu demande un redémarrage (/run/reboot-required), effacé sinon;
#   demande : écrit par la surveillance après la réponse de JF, une date locale stricte AAAA-MM-JJTHH:MM;
#   dernier : écrit ici juste avant le redémarrage (la surveillance confirme à JF que ld1 est revenu).
# Ce script ne lit rien d'autre, et rejette toute demande qui n'a pas exactement ce format.
set -eu
D=/srv/lmapp/etat/redemarrage
mkdir -p "$D"
chown 1000:1000 "$D"

if [ -f /run/reboot-required ]; then
	if [ ! -f "$D/requis" ]; then
		{ date -Iseconds; cat /run/reboot-required.pkgs 2>/dev/null || true; } > "$D/requis.tmp"
		chown 1000:1000 "$D/requis.tmp"
		mv "$D/requis.tmp" "$D/requis"
	fi
else
	rm -f "$D/requis"
fi

[ -f "$D/demande" ] || exit 0
Q=$(head -c 16 "$D/demande" | tr -d '\n')
case "$Q" in
	[0-9][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]) ;;
	*) logger -t lmapp-redemarrage "demande illisible, effacée"; rm -f "$D/demande"; exit 0 ;;
esac
CIBLE=$(date -d "${Q%T*} ${Q#*T}" +%s) || { rm -f "$D/demande"; exit 0; }
MAINTENANT=$(date +%s)
[ "$MAINTENANT" -ge "$CIBLE" ] || exit 0
rm -f "$D/demande"
# Heure manquée de plus de 30 minutes (serveur arrêté, minuteur en retard) : on ne redémarre pas en retard
[ $((MAINTENANT - CIBLE)) -le 1800 ] || { logger -t lmapp-redemarrage "heure $Q dépassée, rien fait"; exit 0; }
[ -f /run/reboot-required ] || { logger -t lmapp-redemarrage "plus besoin de redémarrer"; exit 0; }
# Surveillance en silence 15 minutes (même fichier que outils/silence.sh), puis redémarrage
echo $((MAINTENANT + 900)) > /srv/lmapp/etat/silence_jusqu_a.tmp
chown 1000:1000 /srv/lmapp/etat/silence_jusqu_a.tmp
mv /srv/lmapp/etat/silence_jusqu_a.tmp /srv/lmapp/etat/silence_jusqu_a
echo "$Q" > "$D/dernier"
chown 1000:1000 "$D/dernier"
logger -t lmapp-redemarrage "redémarrage confirmé par courriel pour $Q"
systemctl reboot

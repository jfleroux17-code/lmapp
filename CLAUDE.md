# CLAUDE.md : consignes pour Claude Code sur ld1

Projet : LMAPP, application de gestion pour Louis Méthot Déneigement.
Porteur : Jean-François Leroux (JF), administrateur du serveur.
Plan complet : `PRD.md` dans ce dossier. Le lire au complet avant toute décision d'architecture.

## Le serveur

- Hôte : `ld1`, VM Hyper-V (Gen 2) sur l'hôte SUPER-01, au centre de données de JF.
- OS : Ubuntu Server 26.04.1 LTS, noyau 7.0, installation minimale. 4 vCPU, 8 Go de RAM, 250 Go.
- Réseau : IP fixe `172.16.4.100/24`, passerelle `172.16.4.1`, DNS `8.8.8.8` et `1.1.1.1`. Config dans `/etc/netplan/01-ld1.yaml` (l'original est dans `/root/netplan-backup/`).
- Fuseau horaire : `America/Toronto`.
- Disque : le volume logique `ubuntu-vg/ubuntu-lv` ne fait que 98 Go sur les 250 Go de la VM (à agrandir par JF avec `lvextend -r`).
- Domaine : `ledeneigeur.com` (et `ledeneigeur.ca` redirigé). Serveur : `ld1.ledeneigeur.com`. App : un sous-domaine par déneigeur; celui de Louis est `louis.ledeneigeur.com`. Environnement de test : `test.ledeneigeur.com`. Caddy sert chaque sous-domaine avec son propre certificat.
- DNS chez Cloudflare. Au 7 novembre 2026, un enregistrement générique `*` en mode proxy fait résoudre tous les sous-domaines vers Cloudflare (`172.64.80.1`), pas vers ld1. IP publique sortante de ld1 : `216.46.12.226`.
- Utilisateur : `deploy` (sudo avec mot de passe, membre du groupe `docker`). Pas de sudo sans mot de passe.
- SSH : clé seulement, `root` interdit, `AllowUsers deploy` (`/etc/ssh/sshd_config.d/00-ld1.conf`).
- Pare-feu `ufw` : SSH seulement depuis `172.16.4.0/24`; 80 et 443 limités au réseau interne. `fail2ban` actif sur sshd (backend systemd, `172.16.4.1` exclu). Rappel : ufw ne protège pas les ports publiés par Docker (règle 3).
- Exposition à Internet (décision de JF, 7 novembre 2026, pas encore en place) : redirection au routeur de `216.46.12.226` vers `172.16.4.100`, **limitée à quelques IP sources** choisies par JF. Le 443 seulement est proposé (le 80 est inutile avec la validation DNS). Le filtrage principal se fait au routeur; une liste `IP_PERMISES` dans `edge/.env`, appliquée par Caddy, sert de deuxième couche si l'IP réelle des visiteurs arrive jusqu'à ld1. Enregistrements de l'app en DNS seulement (nuage gris), sinon le filtre par IP ne voit que Cloudflare.
- MAC de la VM dynamique (décision de JF) : netplan doit reconnaître la carte par le pilote `hv_netvsc`, jamais par la MAC.
- Les connexions SSH arrivent avec la source `172.16.4.1` (NAT source du routeur). À vérifier pour le trafic web au premier essai de l'extérieur (journaux de Caddy) : si c'est aussi le cas, ni l'app ni Caddy ne voient l'IP réelle, et le filtre `IP_PERMISES` ne peut pas fonctionner.
- Docker : paquets Ubuntu (`docker.io`, `docker-compose-v2`, `docker-buildx`), journaux plafonnés à 10 Mo x 3 par conteneur.
- Dossier du projet : `/srv/lmapp` (propriétaire `deploy`).

Première chose à faire dans une nouvelle session : vérifier que Docker est installé et fonctionnel (`docker --version`, `docker compose version`, `docker ps`). Si ce n'est pas le cas, le dire à JF avant de continuer.

## Règles de travail

1. **Rien sans sudo dans le dos de JF.** Toute commande `sudo` est annoncée avec ce qu'elle fait, et JF tape le mot de passe. Le travail de l'app (code, Docker, base) se fait sans sudo.
2. **Avant tout geste destructif ou irréversible** (suppression de données, `docker volume rm`, migration qui détruit une colonne, modification réseau, SSH ou pare-feu, envoi réel de textos ou de courriels à des clients) : montrer le plan, dire ce qui est irréversible, attendre un « go » explicite. Rappeler à JF de prendre un instantané Hyper-V avant une grosse étape.
3. **Docker contourne ufw.** Seul le conteneur Caddy (projet `edge`) publie un port (443 TCP pour l'instant). PostgreSQL, l'app et le worker restent sur les réseaux Docker internes, sans `ports:`. Jamais de `5432` exposé. Après chaque changement au Compose, vérifier les ports publiés (`docker compose ps`, `ss -tln`).
4. **Git dès le départ.** Un commit par changement logique, messages en français. Le `.env` et tout secret restent hors du dépôt (`.gitignore`).
5. **Secrets** : clés API (Twilio, SMTP2GO, Stripe, Anthropic), mots de passe IMAP et de base de données vont dans `/srv/lmapp/.env` (permissions 600). Ne jamais les afficher en entier dans la console ni les écrire dans un fichier suivi par Git.
6. **Environnement de test séparé** (autre projet Compose, autre base) avant toute mise en production. Jamais de test sur les vrais clients de Louis. En test, les textos et courriels partent vers les numéros et adresses de JF seulement.
7. **Données de Louis jamais codées en dur** : nom, taxes, numéro de texto, gabarits, tout passe par la table `Entreprise` et la configuration (section P du PRD).
8. **Procéder par étapes courtes** et montrer le résultat avant de passer à la suivante. Expliquer le raisonnement, pas juste la conclusion.

## Langue et style

- Interface, messages aux clients, gabarits, commentaires utilisateurs et documentation : **français québécois**.
- Ne jamais utiliser le tiret cadratin ni le tiret demi-cadratin dans les textes rédigés. Utiliser deux-points, virgules, parenthèses ou points.
- Ton court et direct, pas corporatif. Pas de vocabulaire de vente.
- Ne jamais utiliser le mot « soumission » : « proposition » ou « offre ».
- Dans un document officiel, le nom de JF s'écrit « Jean-François Leroux ».

## Pile retenue (voir PRD section 6)

Django (Python 3.12+), gabarits Django + HTMX + Alpine.js + Tailwind, PostgreSQL 17 + PostGIS, Procrastinate pour les tâches, Caddy en frontal (HTTPS Let's Encrypt), Gunicorn, WeasyPrint pour les PDF, Leaflet + OpenStreetMap. PWA mobile d'abord, pensée pour un iPhone 17 Pro Max utilisé avec des gants.

Versions en place : Python 3.13, Django 5.2 LTS (choisi plutôt que 6.x pour durer jusqu'en avril 2028), PostgreSQL 17.11 et PostGIS 3.7 (`postgis/postgis:17-3.7`), Procrastinate 3.10, Gunicorn 26.2, WeasyPrint 70, Caddy 2.11. Versions fixées dans `requirements.txt` et `compose.yaml`; on monte à la main, après test.

## Structure du dépôt et façon de faire

- `src/` : le code Django (`config/` pour les réglages, `core/` pour l'app de base). `Dockerfile`, `compose.yaml` (prod) et la documentation à la racine. `edge/` : le frontal Caddy (`edge/compose.yaml`, `edge/Caddyfile`).
- Trois projets Compose :
  - `edge` (`/srv/lmapp/edge`) : Caddy seul, frontal HTTPS de tous les environnements, **seul projet qui publie un port**. Recharger le Caddyfile : `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`.
  - `lmapp` (`/srv/lmapp`) : la prod, `db`, `app` et `worker`, sans aucun port publié.
  - `lmapp-test` (à venir) : le test sur `test.ledeneigeur.com`, sa propre base.
- Une seule image (`lmapp:latest`) pour `app` (Gunicorn) et `worker` (`manage.py procrastinate worker`). Utilisateur `lmapp` (UID 1000, comme `deploy`), système de fichiers en lecture seule sauf `/tmp` et les médias.
- Réseaux Docker :
  - `edge` (externe, créé une fois avec `docker network create edge`) : partagé entre Caddy et les apps. Chaque app y porte un nom unique (`lmapp-prod-app`, `lmapp-test-app`); Caddy s'adresse à ces noms, jamais à `app`.
  - `lmapp_interne` (sans accès Internet) : `db`, `app` et `worker` de la prod.
  - `lmapp_sortie` : sortie Internet du worker, propre à la prod; le worker n'est pas sur le réseau partagé.
- Volumes **externes** `lmapp_pgdata`, `lmapp_media`, `lmapp_caddy_data` (ce dernier utilisé par `edge`) : `docker compose down -v` ne peut pas les effacer. Ne jamais les supprimer sans le « go » de JF (règle 2).
- **Migrations jamais automatiques au démarrage.** Les lancer à la main : `docker compose run --rm app python manage.py migrate`. Lire le plan (`showmigrations`, `sqlmigrate`) avant toute migration qui touche des données existantes.
- Réglages lus depuis l'environnement (`.env`, modèle dans `.env.example`). `LMAPP_ENV` vaut `prod` ou `test` et sert aux garde-fous sur les envois réels.
- Vérification de santé : `/sante/` répond `{"app": "ok", "base": "ok"}`.
- Pour tester le HTTPS depuis ld1 sans DNS : `curl -k --resolve louis.ledeneigeur.com:443:127.0.0.1 https://louis.ledeneigeur.com/sante/`.

## Ordre de travail

Fait (7 novembre 2026) : dépôt Git, squelette Django, Dockerfile, Compose et `.env`, pile démarrée et validée sur le réseau interne avec le certificat interne de Caddy. Caddy déplacé dans le projet `edge` (décision de JF).

À suivre, dans l'ordre :
1. Vrai certificat Let's Encrypt par validation DNS Cloudflare (image Caddy avec `caddy-dns/cloudflare`, jeton `CLOUDFLARE_API_TOKEN` déposé par JF dans `edge/.env`, propre au projet `edge`).
2. Environnement de test sur `test.ledeneigeur.com` : projet Compose `lmapp-test`, sa propre base et ses propres volumes, app sur le réseau `edge` sous le nom `lmapp-test-app`.
3. Ouverture filtrée par IP (voir « Exposition à Internet » plus haut), avec la liste `IP_PERMISES` dans Caddy et la lecture de l'IP réelle par Django.
4. Phase 1 du PRD (section 8) : modèle de données (`Entreprise` en premier), import CSV, puis le volet argent.

# CLAUDE.md : consignes pour Claude Code sur ld1

Projet : LMAPP, application de gestion pour Louis Méthot Déneigement.
Porteur : Jean-François Leroux (JF), administrateur du serveur.
Plan complet : `PRD.md` dans ce dossier. Le lire au complet avant toute décision d'architecture.

## Le serveur

- Hôte : `ld1`, VM Hyper-V (Gen 2) sur l'hôte SUPER-01, au centre de données de JF.
- OS : Ubuntu Server 26.04.1 LTS, noyau 7.0, installation minimale. 4 vCPU, 8 Go de RAM, 250 Go.
- Réseau : IP fixe `172.16.4.100/24`, passerelle `172.16.4.1`, DNS `8.8.8.8` et `1.1.1.1`. Config dans `/etc/netplan/01-ld1.yaml` (l'original est dans `/root/netplan-backup/`).
- Fuseau horaire : `America/Toronto`.
- Domaine : `ledeneigeur.com` (et `ledeneigeur.ca` redirigé). Serveur : `ld1.ledeneigeur.com`. App : un sous-domaine par déneigeur; celui de Louis est `louis.ledeneigeur.com`. Caddy sert chaque sous-domaine avec son propre certificat.
- Utilisateur : `deploy` (sudo avec mot de passe, membre du groupe `docker`). Pas de sudo sans mot de passe.
- SSH : clé seulement, `root` interdit, `AllowUsers deploy` (`/etc/ssh/sshd_config.d/00-ld1.conf`).
- Pare-feu `ufw` : SSH seulement depuis `172.16.4.0/24`; 80 et 443 limités au réseau interne pendant le développement (aucune redirection publique au routeur). `fail2ban` actif sur sshd (backend systemd, `172.16.4.1` exclu).
- MAC de la VM dynamique (décision de JF) : netplan doit reconnaître la carte par le pilote `hv_netvsc`, jamais par la MAC.
- Les connexions arrivent avec la source `172.16.4.1` (NAT source du routeur). À vérifier pour le trafic web public : si c'est aussi le cas, l'app ne verra pas l'IP réelle des visiteurs.
- Docker : paquets Ubuntu (`docker.io`, `docker-compose-v2`, `docker-buildx`), journaux plafonnés à 10 Mo x 3 par conteneur.
- Dossier du projet : `/srv/lmapp` (propriétaire `deploy`).

Première chose à faire dans une nouvelle session : vérifier que Docker est installé et fonctionnel (`docker --version`, `docker compose version`, `docker ps`). Si ce n'est pas le cas, le dire à JF avant de continuer.

## Règles de travail

1. **Rien sans sudo dans le dos de JF.** Toute commande `sudo` est annoncée avec ce qu'elle fait, et JF tape le mot de passe. Le travail de l'app (code, Docker, base) se fait sans sudo.
2. **Avant tout geste destructif ou irréversible** (suppression de données, `docker volume rm`, migration qui détruit une colonne, modification réseau, SSH ou pare-feu, envoi réel de textos ou de courriels à des clients) : montrer le plan, dire ce qui est irréversible, attendre un « go » explicite. Rappeler à JF de prendre un instantané Hyper-V avant une grosse étape.
3. **Docker contourne ufw.** Seul le conteneur Caddy publie des ports (80 et 443). PostgreSQL, l'app et le worker restent sur le réseau Docker interne, sans `ports:`. Jamais de `5432` exposé.
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

## Ordre de travail

Phase 0 restante, puis phase 1 du PRD (section 8) : structure du projet, Docker Compose (`app`, `worker`, `db`, `caddy`), déploiement vide en HTTPS sur `louis.ledeneigeur.com`, accessible seulement du réseau interne ou du VPN au départ (certificat par validation DNS, aucun port public tant que JF n'a pas décidé du mode d'exposition), modèle de données, import CSV, puis le volet argent.

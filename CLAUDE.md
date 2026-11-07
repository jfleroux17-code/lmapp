# CLAUDE.md : consignes pour Claude Code sur ld1

Projet : LMAPP, application de gestion pour Louis Méthot Déneigement.
Porteur : Jean-François Leroux (JF), administrateur du serveur.
Plan complet : `PRD.md` dans ce dossier. Le lire au complet avant toute décision d'architecture.

## Le serveur

- Hôte : `ld1`, VM Hyper-V (Gen 2) sur l'hôte SUPER-01, au centre de données de JF.
- OS : Ubuntu Server 26.04.1 LTS, noyau 7.0, installation minimale. 4 vCPU, 8 Go de RAM, 250 Go.
- Réseau : IP fixe `172.16.4.100/24`, passerelle `172.16.4.1`, DNS `8.8.8.8` et `1.1.1.1`. Config dans `/etc/netplan/01-ld1.yaml` (l'original est dans `/root/netplan-backup/`).
- Fuseau horaire : `America/Toronto`.
- Disque : le volume logique `ubuntu-vg/ubuntu-lv` fait 98 Go sur les 250 Go de la VM (15 % utilisés le 7 novembre 2026). Pas d'agrandissement pour l'instant (décision de JF) : seuil d'alerte à **70 %**, puis agrandissement à chaud par JF (`sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv`, après `sudo vgs`). Libérer de l'espace au besoin avec `docker image prune` et `docker builder prune`.
- Domaine : `ledeneigeur.com` (et `ledeneigeur.ca` redirigé). Serveur : `ld1.ledeneigeur.com`. App : un sous-domaine par déneigeur; celui de Louis est `louis.ledeneigeur.com`. Environnement de test : `test.ledeneigeur.com`. Caddy sert chaque sous-domaine avec son propre certificat.
- DNS chez Cloudflare. `louis.ledeneigeur.com` et `test.ledeneigeur.com` : enregistrements A vers `216.46.12.226` (IP publique de ld1), en DNS seulement (nuage gris). Plus d'enregistrement générique `*` en A. La racine et `www` restent en proxy vers `69.16.231.58`.
- Jeton API Cloudflare dans `edge/.env` (jeton de compte, préfixe `cfat_`, limité à la zone `ledeneigeur.com`, sans expiration). Un jeton de compte se vérifie par `/accounts/{id}/tokens/verify`, pas par `/user/tokens/verify` (qui répond « Invalid API Token »). **Pour inspecter un `.env`, n'afficher que des noms de variables valides (`[A-Z][A-Z0-9_]*`) et masquer toute autre ligne** : une ligne sans `=` est peut-être un secret nu.
- Utilisateur : `deploy` (sudo avec mot de passe, membre du groupe `docker`). Pas de sudo sans mot de passe.
- SSH : clé seulement, `root` interdit, `AllowUsers deploy` (`/etc/ssh/sshd_config.d/00-ld1.conf`).
- Pare-feu `ufw` : SSH seulement depuis `172.16.4.0/24`; 80 et 443 limités au réseau interne. `fail2ban` actif sur sshd (backend systemd, `172.16.4.1` exclu). Rappel : ufw ne protège pas les ports publiés par Docker (règle 3).
- Exposition à Internet (décision de JF, 7 novembre 2026, **en place**) : routeur Mikrotik, redirection du 443 de `216.46.12.226` vers `172.16.4.100`, **limitée à la liste d'adresses `_SLAPP`** (bureau et maison de JF). À terme, ouverture à toutes les IP publiques (Louis en tempête, webhooks, autres déneigeurs) : il faudra alors des protections dans l'app (voir PRD 6.1.1). Seul le 443 est redirigé (le 80 est inutile avec la validation DNS). **Le filtrage se fait au routeur seulement** (décision de JF, 7 novembre 2026 : pas de deuxième couche dans Caddy ni dans l'app). Docker contourne ufw : la règle `_SLAPP` du Mikrotik est donc la seule barrière devant le 443; si elle change, l'app est ouverte à tout Internet. Enregistrements de l'app en DNS seulement (nuage gris).
- MAC de la VM dynamique (décision de JF) : netplan doit reconnaître la carte par le pilote `hv_netvsc`, jamais par la MAC.
- Caddy a l'IP fixe `172.20.0.250` sur le réseau `edge`. L'app ne croit l'en-tête `X-Forwarded-For` que s'il vient de cette adresse (`core.middleware.IPReelleMiddleware`, variable `LMAPP_PROXIES_DE_CONFIANCE`), et Gunicorn non plus (`FORWARDED_ALLOW_IPS`). Si le réseau `edge` est recréé avec un autre sous-réseau, changer ces trois endroits ensemble.
- Docker pige ses sous-réseaux dans `172.17.0.0/16` à `172.31.0.0/16` : conflit possible avec d'autres réseaux de JF (VPN, bureau). À fixer au besoin par `default-address-pools` dans `/etc/docker/daemon.json` (sudo).
- Journaux d'accès de Caddy : `cd /srv/lmapp/edge && docker compose logs caddy` (JSON, `request.remote_ip`).
- NAT source : les connexions **SSH** arrivent avec la source `172.16.4.1`. La redirection du **443**, elle, conserve l'IP réelle du visiteur (vérifié le 7 novembre 2026 : essai de JF depuis la maison, IP publique vue par Caddy). La limitation des abus pourra donc s'appuyer sur l'IP réelle. Ne jamais inscrire les IP de JF dans un fichier suivi par Git : elles vont dans `edge/.env`.
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
  - `edge` (`/srv/lmapp/edge`) : Caddy seul (image maison avec le module `caddy-dns/cloudflare`), frontal HTTPS de tous les environnements, **seul projet qui publie un port**. Certificats Let's Encrypt par validation DNS. Après un changement d'autorité (`acme_ca`), un `reload` ne suffit pas : Caddy garde les certificats en mémoire, il faut `docker compose restart caddy`. Recharger le Caddyfile : `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`.
  - `lmapp` (`/srv/lmapp`) : la prod, `db`, `app` et `worker`, sans aucun port publié.
  - `lmapp-test` (`/srv/lmapp/test`) : le test sur `test.ledeneigeur.com`. Son propre `compose.yaml` et son propre `.env` (jamais de variables partagées avec la prod), base `lmapp_test`, volumes `lmapp_test_pgdata` et `lmapp_test_media`, image `lmapp:test`. Bandeau « ENVIRONNEMENT DE TEST » à l'écran dès que `LMAPP_ENV` n'est pas `prod`.
- Apps Django : `core` (`Entreprise`, `Membre`, `VilleDesservie`, utilitaires `core.telephone` et `core.texte`), `clients` (`Secteur`, `Client`, `Adresse`). Chaque modèle métier a une clé vers `Entreprise`; vérifier dans `clean()` que les objets liés appartiennent à la même entreprise.
- Utilisateurs : modèle `User` de Django, **pas de modèle personnalisé** (les tables existaient déjà). Le rôle (administrateur, opérateur, lecture seule) et l'entreprise passent par `core.Membre`.
- Téléphones toujours stockés en E.164 (`+1XXXXXXXXXX`) via `core.telephone.normaliser`, pour rattacher les textos reçus (E4). Courriels en minuscules, sans espaces, nettoyés dans `clean_fields()` (avant la validation du format).
- Positions : `PointField` en `geography` (SRID 4326), distances en mètres (`position__dwithin=(point, D(m=800))`), index GIST.
- Données d'essai : `cd /srv/lmapp/test && docker compose run --rm app python manage.py donnees_essai` crée « Déneigement Essai » à Sainte-Adèle (ville desservie, secteurs Village, Mont-Rolland, Chantecler, 10 clients, 11 adresses); `--reinitialiser` efface d'abord l'entreprise d'essai seulement. Refuse en prod. Cellulaires dans la plage fictive 555-0100 à 555-0199, courriels en `@example.com` : jamais de vraie donnée en test.
- Import des clients (A9) : gabarit dans `gabarits/gabarit_import_clients.xlsx` (et `.csv`), regénéré par `manage.py gabarit_import`. Une ligne par adresse; même `no_client` pour regrouper les adresses d'un payeur. Ville facultative : vide, c'est la ville par défaut de l'entreprise; une ville non desservie donne un avertissement. Commande, **essai à blanc par défaut** :
  `docker compose run --rm -v /chemin/clients.xlsx:/import/clients.xlsx:ro app python manage.py importer_clients /import/clients.xlsx --entreprise louis`
  puis `--appliquer` (tout ou rien) ou `--appliquer --sauter-erreurs`. Relançable : une ligne déjà en base (même cellulaire ou même adresse) est ignorée. Toujours essayer d'abord en test. Le fichier de Louis contient des données personnelles : le garder hors du dépôt (dossier `data/`, ignoré par Git) et l'effacer après l'import.
- Géocodage (A2) : Nominatim public (`clients/geocodage.py`), au plus une requête par seconde, User-Agent « LMAPP », **seulement l'adresse, jamais le nom du client**. Une adresse créée ou dont la rue, la ville ou le code postal change est mise en file (`clients.signals`, tâche `clients.tasks.geocoder_adresse`, file `geocodage`). Une position `manuelle` ou `gps` n'est jamais écrasée; déplacer le point sur la carte de l'administration la rend manuelle. Zone de service : chaque adresse est cherchée dans la zone (centre et rayon) de sa `VilleDesservie`, et un résultat hors rayon est rejeté; sans résultat dans la zone, la position est le centre de la zone, précision `ville`. Louis : Sainte-Adèle seulement (rayon 8 km), d'autres villes s'ajoutent dans la fiche de l'entreprise (centre rempli automatiquement). Noms de villes comparés sans accents ni majuscules, « Ste » = « Sainte », « St » = « Saint » (`core.texte.cle_ville`). Précision : `adresse`, `rue`, `ville`, `introuvable`; `ville` et `introuvable` sont « à vérifier » (filtre dans l'administration), trop vagues pour les avis de proximité. Rattrapage : `manage.py geocoder_adresses --entreprise louis` (`--maintenant` sans worker). `NOMINATIM_URL` permet un Nominatim installé sur ld1.
- Tests : `cd /srv/lmapp/test && docker compose run --rm app python manage.py test`. Générer les migrations avec le code monté : `docker compose run --rm -v /srv/lmapp/src:/app app python manage.py makemigrations`, puis relire `sqlmigrate` avant d'appliquer.
- Une seule image pour `app` (Gunicorn) et `worker` (`manage.py procrastinate worker`) : `lmapp:test` pour le test, `lmapp:latest` pour la prod. Utilisateur `lmapp` (UID 1000, comme `deploy`), système de fichiers en lecture seule sauf `/tmp` et les médias.
- Réseaux Docker :
  - `edge` (externe, créé une fois avec `docker network create edge`) : partagé entre Caddy et les apps. Chaque app y porte un nom unique (`lmapp-prod-app`, `lmapp-test-app`); Caddy s'adresse à ces noms, jamais à `app`.
  - `lmapp_interne` et `lmapp-test_interne` (sans accès Internet) : la base et les services de chaque environnement, séparés.
  - `lmapp_sortie` et `lmapp-test_sortie` : sortie Internet du worker de chaque environnement; les workers ne sont pas sur le réseau partagé.
- Volumes **externes** `lmapp_pgdata`, `lmapp_media`, `lmapp_test_pgdata`, `lmapp_test_media`, `lmapp_caddy_data` (ce dernier utilisé par `edge`) : `docker compose down -v` ne peut pas les effacer. Ne jamais les supprimer sans le « go » de JF (règle 2).
- **Migrations jamais automatiques au démarrage.** Les lancer à la main : `docker compose run --rm app python manage.py migrate`. Lire le plan (`showmigrations`, `sqlmigrate`) avant toute migration qui touche des données existantes.
- Réglages lus depuis l'environnement (`.env`, modèle dans `.env.example`). `LMAPP_ENV` vaut `prod` ou `test` et sert aux garde-fous sur les envois réels.
- **Du test à la prod** : tout changement de code se bâtit et s'essaie d'abord en test (`cd /srv/lmapp/test && docker compose build && docker compose run --rm app python manage.py migrate && docker compose up -d`). On passe à la prod seulement après validation, et avec le « go » de JF : `cd /srv/lmapp && docker compose build && docker compose run --rm app python manage.py migrate && docker compose up -d`.
- Vérification de santé : `/sante/` répond `{"app": "ok", "base": "ok"}`.
- Pour tester le HTTPS depuis ld1 sans DNS : `curl -k --resolve louis.ledeneigeur.com:443:127.0.0.1 https://louis.ledeneigeur.com/sante/`.

## Ordre de travail

Fait (7 novembre 2026) : dépôt Git, squelette Django, Dockerfile, Compose et `.env`, pile démarrée et validée sur le réseau interne avec le certificat interne de Caddy. Caddy déplacé dans le projet `edge` (décision de JF). Environnement de test `lmapp-test` en marche sur `test.ledeneigeur.com`. Vrais certificats Let's Encrypt pour `louis` et `test` par validation DNS Cloudflare (image `lmapp-caddy:2.11-cloudflare`, bâtie depuis `edge/Dockerfile`). Ouverture au routeur pour `_SLAPP`, testée de l'extérieur; Django et Gunicorn ne croient `X-Forwarded-For` que de Caddy (`172.20.0.250`).

À suivre, dans l'ordre :
1. Phase 1 du PRD (section 8) : modèle de données (`Entreprise` en premier), import CSV, puis le volet argent.

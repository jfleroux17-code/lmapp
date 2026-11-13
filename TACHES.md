# LMAPP : tâches à faire

Liste tenue à jour par Claude Code sur ld1, à chaque étape. Le plan complet est dans `PRD.md`, les consignes techniques dans `CLAUDE.md`.

Mise à jour : 9 novembre 2026.

## Où on en est

- L'app est en prod sur `louis.ledeneigeur.com`, **ouverte à Internet (443) depuis le 9 novembre 2026**, et en test sur `test.ledeneigeur.com` (réservé aux IP de JF). Sauvegardes aux 12 heures, surveillance avec alertes à JF, UptimeRobot de l'extérieur, retour en arrière possible (images étiquetées par commit).
- Fait : phase 1 (clients, import, volet argent, courriels, textos, relances), phase 2 (tournée, hors ligne, avis) et une bonne partie de la V2. Réception des textos et ARRÊT/COMMENCER vérifiés en prod. Site `ledeneigeur.com` en ligne, boîte `info@` branchée (demandes dans l'administration, transférées à JF).
- **La fiche de Louis est prête, mais sa base n'a aucun client, et ses envois réels sont éteints.** La suite dépend de ses réponses (section « Louis ») et de sa liste de clients.

## Jean-François

### Ce qui bloque la suite

- [x] Créer ses comptes administrateur (prod et test).
- [x] App essayée sur l'iPhone de JF, en test (9 novembre 2026) : écran d'accueil, notifications (essai reçu), position pendant la tournée (précision 4 à 6 m). Corrigé à la suite : adresse en premier dans la tournée, champ de date des demandes qui débordait, bouton Messages toujours visible (enveloppe), page de secours au lieu d'un écran blanc pendant un redémarrage. Puis : nom de l'entreprise sur sa propre ligne, bouton Demandes (porte-voix) rouge pour une demande pas encore ouverte, orange pour une ouverte pas réglée.
- [x] Fiche de Louis créée en prod (Louis Méthot Déneigement, `louis`, `louis.ledeneigeur.com`, Sainte-Adèle 8 km, centre rempli).
- [x] Sainte-Adèle cochée « ville par défaut » dans la fiche de Louis.
- [x] Utilisateur `louis` créé, membre « Opérateur » (entre dans l'app, pas dans l'administration).
- [x] Fiche de Louis complétée en prod (8 novembre 2026) : nom légal, adresse, téléphone, courriel, inscrit aux taxes, numéros de TPS et de TVQ (dans la fiche seulement). Le nom affiché reste « Louis Méthot Déneigement » jusqu'à la réponse à la question 14.
- [ ] **Liste des clients de Louis** (photos de son cahier, mise en fichier par JF avec Claude.ai, 9 novembre 2026). Gabarit à jour sur GitHub (`gabarits/`) avec les colonnes ajoutées pour ce fichier : `taxes_incluses`, `service`, `extra_service`, `extra_prix`, `recu_montant`, `recu_date`, `recu_mode`. Reste, côté Louis : le sens de ses X (statut **inactif** pour les ex-clients avant l'import), Proulx (3625-3627) : une entrée ou deux. Numéro civique de JF : reçu (corrigé dans sa ligne à la réception du fichier). Ensuite : essai à blanc en test, puis en prod, fichier effacé après.
- [ ] Poser à Louis les questions de la section « Louis » ci-dessous.
- [ ] **Allumer les envois réels de Louis** (interrupteur de sa fiche) : go de JF, une fois ses clients importés et vérifiés. Jalon de la phase 1 : la première vraie facture ou relance.

### Comptes de services (textos et courriels, phase 1)

- [x] Boîte `louis@ledeneigeur.com` sur le serveur de courriel de JF (`woww.joxs.net`), à la place de SMTP2GO. Connexion IMAP et SMTP vérifiée depuis le worker (8 novembre 2026). MX, SPF et DMARC ajoutés chez Cloudflare.
- [x] DKIM de `ledeneigeur.com` (sélecteur `default`) publié chez Cloudflare (8 novembre 2026).
- [x] DNS inverse de 216.46.12.228 vers `woww.joxs.net` : fait par Beanfield le 9 novembre 2026 (vérifié dans les deux sens, chez Cloudflare et Google).
- [x] Premier courriel d'essai à JF (8 novembre 2026) : SPF, DKIM et DMARC « pass », mais arrivé dans les pourriels (domaine neuf, DNS inverse générique). IP sur aucune liste noire vérifiée.
- [x] Gmail : courriel d'essai marqué « non-spam », `louis@ledeneigeur.com` ajouté aux contacts (JF, 9 novembre 2026). Facultatif plus tard : Google Postmaster Tools pour `ledeneigeur.com`.
- [x] Twilio : compte payant, numéro 450-300-1166, `TWILIO_ACCOUNT_SID` et `TWILIO_AUTH_TOKEN` dans les deux `.env` (8 novembre 2026). Premier texto d'essai livré au cellulaire de JF, depuis le test.
- [x] **JF : deuxième numéro Twilio, réservé à la plateforme** : +1 450 234-7550, acheté le 9 novembre 2026. Mis dans `LMAPP_ALERTES_TEXTO_DE` de la prod par Claude Code, texto d'essai parti (`surveiller --essai-texto`).
- [x] ~~SMTP2GO~~ : abandonné le 8 novembre 2026 (décision de JF), remplacé par le serveur de courriel de JF.
- [x] ~~Boîte IMAP `info@`~~ : remplacée par `louis@ledeneigeur.com` (une boîte par déneigeur), en place.
- [x] ~~Stripe~~ : pas de paiement par carte chez Louis (9 novembre 2026), reporté.

### Serveur (rien d'urgent)

- [x] Netplan par MAC (décision du 7 novembre 2026), configuré par JF. MAC rendue statique dans Hyper-V (`00:15:5d:04:0a:02`) par JF le 10 novembre 2026; redémarrage vérifié (réseau, Docker, prod, test, surveillance).
- [x] Redémarrer ld1 à un moment tranquille : fait par JF le 10 novembre 2026 (avec la MAC statique), tout est reparti seul.
- [x] Vérification externe de `https://louis.ledeneigeur.com/sante/` : UptimeRobot configuré par JF le 9 novembre 2026 (sondes vues dans les journaux de Caddy, réponse 200).
- [x] `sudo ufw status verbose` (7 novembre 2026) : refus par défaut en entrée; SSH depuis `172.16.4.0/24`; 80 et 443 ouverts à tous (ufw ne s'en mêle pas pour le 443 de toute façon, Docker le contourne; rien n'écoute sur le 80). Port 5000 : `BackupFP` (COVE), sur toutes les interfaces, mais bloqué par ufw (aucune règle) : rien à faire.
- [x] Port local 36789 identifié (9 novembre 2026) : `/opt/MXB/bin/ProcessController` de COVE (root), 127.0.0.1 seulement. Rien à faire. Après le redémarrage du 10 novembre : plus en écoute (processus actif); port local 40051 = `containerd`, normal.
- [ ] Donner l'IP publique du bureau pour l'accès à `/admin/` (seule celle de la maison est permise). Elle ira dans `edge/.env`, jamais dans Git.
- [ ] Donner les plages d'adresses des autres réseaux (VPN, bureau, centre de données) : conflit possible avec les plages 172.17 à 172.31 de Docker.
- [x] Copie du dépôt hors de ld1 : GitHub privé `jfleroux17-code/lmapp`, poussé après chaque étape.
- [x] Dépôt GitHub branché dans le Projet Claude de JF (`PRD.md`, `CLAUDE.md`, `TACHES.md`). Après un envoi, synchroniser la source GitHub dans le projet pour voir la dernière version.
- [x] Sauvegardes hors de la VM : COVE, toutes les 12 heures (décision du 7 novembre 2026).
- [x] Heures de COVE inconnues : la base est sauvegardée toutes les 12 heures (3 h 30 et 15 h 30), COVE emporte toujours une copie de moins de 12 heures.
- [x] COVE inclut `/srv/lmapp/sauvegardes/` : sélection `/` au complet (vérifié le 7 novembre 2026, `sudo /opt/MXB/bin/ClientTool control.selection.list`). La copie brute de `/var/lib/docker` (base en marche) n'est pas fiable pour restaurer : toujours repartir des fichiers `.dump`.
- [ ] **Site : référencement et Facebook** (11 novembre 2026, fait côté site : balises, image de partage, schema.org, `robots.txt`, `sitemap.xml`). `site.zip` déposé et vérifié en ligne le 12 novembre 2026. Google Search Console connecté et propriété vérifiée par JF (12 novembre 2026); sitemap soumis et indexation de la page d'accueil demandée le 12 novembre 2026 (quelques jours à quelques semaines avant d'apparaître). Bing Webmaster Tools : importé depuis Search Console le 12 novembre 2026. vérifier le partage dans le Sharing Debugger de Meta. **Avant la campagne Facebook** : vérifier le domaine dans Meta Business (TXT chez Cloudflare); un pixel Meta ou tout autre suivi exige le consentement des visiteurs (Loi 25 : bandeau, refus aussi simple que l'acceptation) et une mise à jour de la politique de confidentialité, sinon s'en passer et mesurer par des liens marqués (`?utm_source=facebook`) et les demandes à info@.
- [x] **Google Tag Manager sur le site** (conteneur `GTM-TPG648K6`, 11 novembre 2026) : `site/consentement.js`, bandeau Accepter ou Refuser (même poids), Tag Manager chargé seulement après « Accepter » (mode Consentement v2, refusé par défaut), lien « Témoins » au bas des pages pour changer d'idée (refus après acceptation : témoins `_ga`, `_fbp` effacés), section « Témoins » dans la politique de confidentialité. Vérifié dans Chrome : aucune requête vers Google avant l'acceptation.
- [x] **Site déposé et Google Analytics branché** (12 novembre 2026) : bandeau en ligne sur ledeneigeur.com, vérifié dans Chrome : aucune requête vers Google avant « Accepter », puis Tag Manager et GA4 (`G-4GS3DNKCNY`) envoient la visite. Plus tard : pixel Meta dans Tag Manager (même consentement).
- [ ] **Sortir dans les réponses de ChatGPT et Claude** (demande de JF, 11 novembre 2026). Fait : `robots.txt` qui laisse entrer leurs robots, `llms.txt`. Fait le 12 novembre 2026 : Google Search Console et Bing Webmaster Tools (ChatGPT cherche surtout par Bing). Reste à JF : fiche Google Business Profile de SLAPP ou de Le Déneigeur; être cité ailleurs (répertoires de logiciels comme Capterra et G2, associations de déneigeurs, articles, Facebook, avis de vrais clients comme Louis). Aucun moyen de le garantir : les assistants citent ce que le Web dit du logiciel.
- [x] **Redirections 301** (12 novembre 2026) : `www.ledeneigeur.com`, `ledeneigeur.ca` et `www.ledeneigeur.ca` vers `https://ledeneigeur.com` (chemin gardé), vérifiées de l'extérieur.
- [ ] **Application en anglais** (demande de JF, 11 novembre 2026), à planifier : langue choisie par utilisateur et langue de chaque client (textos, courriels, factures, gabarits). **Décision de JF (11 novembre 2026)** : Québec seulement pour l'instant, puis l'Ontario, le reste du Canada et les États-Unis; le tout en **phase 3** (PRD section U, U1 à U5).
- [ ] **Site en anglais** (demande de JF, 11 novembre 2026) : même site, traduit. **Nom choisi par JF : The Snow Remover** (11 novembre 2026; PRD U3, phase 3). **`thesnowremover.com` et `thesnowremover.ca` achetés par JF le 11 novembre 2026** (chez le registraire Rebel, comme `ledeneigeur.com`; le `.com` répond déjà par les serveurs DNS de Rebel, le `.ca` pas encore, normal les premières heures). Plus tard, au moment de U3 : DNS chez Cloudflare comme `ledeneigeur.com`. Reste à JF : vérifier la marque de commerce au Canada (Office de la propriété intellectuelle).
- [ ] Trancher les fonctionnalités V1 dans le catalogue du PRD (section 5), au besoin.
- [ ] Offre aux autres déneigeurs (PRD section Q) : **prix revu le 11 novembre 2026 : 99 $ par mois** (abonnement annuel, facturé mensuellement) avec un utilisateur (administrateur et opérateur), **25 $ par mois par utilisateur de plus**, **0,03 $ par texto** (0,015 $ doublé, accents gardés), courriels gratuits, nouveaux modules à part; sur le site le même jour. Précisé par JF le 11 novembre 2026 : textos **reçus** comptés (un par texto reçu), **lecture seule gratuite**, **pas de longs textos** (sur le site le même jour). Le tableau de bord `/admin/plateforme/` donne déjà les textos et segments par mois.
- [x] **Longueur des textos : 201 caractères au plus** (décision de JF, 11 novembre 2026 : 3 segments, accents gardés, signature et liens compris). **Fait en test le 11 novembre 2026** : compteur dans « Écrire » et l'envoi groupé (envoi refusé au-delà), messages types refusés s'ils ne tiennent pas, signature de 40 caractères au plus dans les Réglages, textos automatiques raccourcis (factures, contrats, relances, reçus, invitation), « Dernier avis » par défaut raccourci (migration 0016), filet à l'envoi (« Préparé », texto trop long). **En prod le 11 novembre 2026** (« go » de JF). Un 3e segment coûte un peu plus que 0,03 $ (0,0345 $ CA) : surtout les factures par texto, compensé par les avis courts.
- [x] Site Internet (Q5), **en ligne le 9 novembre 2026** (`ledeneigeur.com` et `www`; politique de confidentialité validée et en ligne, sans l'avis « Ébauche »; `info@` branchée). Archive `site.zip` sur GitHub, refaite à chaque modification. **Nouvelle version le 11 novembre 2026** (captures refaites, écrans « Au bureau », nouvelles fonctions sauf les dépenses, pas encore annoncées, décision de JF; nouveau prix) : à déposer sur le cPanel par JF.
- [ ] Module voix (PRD section R) : **à trancher plus tard**, après l'ouverture du 443 et la réception des textos (décision de JF, 8 novembre 2026). Propositions gardées : R1 (messagerie vocale) en premier, enregistrements gardés 90 jours. Rien n'est commencé. Modèle d'IA : pas de clé de l'API Claude pour l'instant (modèle local possible).
- [ ] Contrat de service avec les déneigeurs (Q7) : **JF s'en occupe de son côté**, pas urgent tant que Louis est le seul client.

## Louis

Questions de la section 10 du PRD, les plus importantes d'abord.

- [x] **Taxes** : inscrit à la TPS et à la TVQ, numéros reçus (8 novembre 2026). Les factures auront les taxes.
- [ ] **Numéro de facture** : quel est le dernier numéro utilisé dans son carnet papier? La numérotation de l'app continuera à partir du suivant (sinon elle commence à 1).
- [ ] **Nom affiché** : ses factures portent « Les Entretiens Paysagers L.M. » (logo « Entretiens LM »). Proposé : nom légal sur les factures, et un nom que ses clients reconnaissent (ex. « Entretiens LM ») à l'écran et à la fin des textos. À confirmer.
- [x] **Versements** (8 novembre 2026) : contrat saisonnier en 2 versements égaux, le 1er novembre et entre la mi-janvier et la fin de janvier; 3e versement possible pour les contrats de plus de 1 200 $ par saison.
- [x] **Type de contrat** : saisonnier seulement, pas de facturation au passage.
- [x] **Détails des versements** (9 novembre 2026) : 2 versements, à l'approbation et le 15 janvier; 3 s'il l'accepte : 1/3 à l'approbation, 1/3 le 15 janvier, 1/3 le 15 février. Envoi et rappel du 2e versement le 10 janvier.
- [ ] **Clients** : combien d'actifs? Combien d'anciens clients lui doivent de l'argent? **Liste en cours** : photos reçues par texto, mises en forme par JF avec claude.ai (9 novembre 2026).
- [ ] **Sa liste de clients** dans le gabarit, ou en photos de ses papiers (noms, adresses, cellulaires, prix entendus, montants dus).
- [x] **Services** (9 novembre 2026) : l'entrée au complet; un seul client de bordage.
- [x] **Numéro de texto** (9 novembre 2026) : Louis accepte que les textos des clients arrivent sur le nouveau numéro d'affaires (450-300-1166). Son cellulaire reste pour les appels.
- [ ] **Courriel et Interac** (9 novembre 2026) : virements reçus à son Gmail. **JF configure avec lui** le transfert des avis d'Interac vers `louis@ledeneigeur.com` (filtre Gmail). Gmail envoie d'abord un code de confirmation à `louis@` : il arrive dans les Messages de l'app (ou dans la boîte). Ensuite, valider la lecture sur un vrai avis.
- [x] **Paiements** (9 novembre 2026) : comptant, virements Interac et chèques, y compris **postdatés** (important). Pas de carte : Stripe reporté.
- [x] **Territoire** : Sainte-Adèle seulement, seul (9 novembre 2026).
- [x] **Comptabilité** (9 novembre 2026) : tout à la main. L'export et le rapport de saison pour le comptable deviennent importants.
- [x] **Clients commerciaux** : aucun pour l'instant (9 novembre 2026).
- [ ] **Matériel** : support de téléphone et chargeur pour le tracteur.
- [ ] **Taux à l'heure et au déplacement** (pour les jobs manuelles l'hiver, comme à Saint-Sauveur, et le paysagement l'été) : $ par heure, $ par km ou par déplacement, minimum facturé, prix du matériel courant; mêmes taux l'hiver et l'été? (JF ne les a pas, 12 novembre 2026; lots C et D : champs dans ses Réglages en attendant.)

## Claude Code

### Demandes de JF du 8 novembre 2026 (faites)

- [x] **Mode de l'entreprise** (PRD K9) : **en prod le 8 novembre 2026**. champ dans `Entreprise`, « déneigeur seul » ou « équipe ». Seul : le propriétaire fait tout dans l'app. Équipe : seuls les administrateurs de l'entreprise modifient les clients, les opérateurs consultent. Louis en « déneigeur seul ».
- [x] **Bouton Annuler partout** (PRD K10) : **en prod le 8 novembre 2026** (formulaires de saisie). sur chaque écran, ramène à l'écran précédent sans rien enregistrer. Rien ne s'enregistre sans un bouton Enregistrer.
- [x] **Modifier un client dans l'app** (PRD A12) : **en prod le 8 novembre 2026** (ajout essayé dans le navigateur). ajout et modification du client et de ses adresses (coordonnées, particularités du terrain, statut, notes) depuis la fiche, au cellulaire, sans l'administration. Gros champs, clavier adapté (téléphone, courriel, code postal).
- [x] **Corriger la position d'une adresse dans l'app** (PRD A13) : **en prod le 8 novembre 2026** (carte Leaflet, tuiles OpenStreetMap). carte plein écran avec repère fixe au centre (on déplace la carte, pas le point), bouton « Je suis devant » (GPS du téléphone), Enregistrer ou Annuler. La position devient `manuelle` ou `gps`, jamais écrasée par le géocodage.
- [x] **Revoir le visuel** : **visuel C (sombre plus net) choisi par JF et en prod le 8 novembre 2026** : noir pur, 20 px de base, cartes et titres plus marqués, onglet actif plein.

### Demandes de Louis du 12 novembre 2026 (relayées par JF, classées)

Ordre proposé : lot A, puis la facturation (une facture par saison, une par passage : avant l'import du fichier de Louis), puis B, C, D, E, F, G. Rien n'est commencé.

**Lot A : petites corrections d'écran**
- [x] (6) « + Nouvelle demande » : chercher et choisir le client; « Lier à un client » sur une demande qui n'en a pas.
- [x] (11a) Adresse complète toujours visible (suite et code postal à côté de la rue, jamais dans « Plus de détails ») : nouveau client, nouvelle adresse, modifier l'adresse.
- [x] (12) Contrat : « + Nouvelle adresse de service » sur place (deux contrats de la même saison pour deux adresses : déjà permis, mais seulement avec une adresse déjà inscrite).
- [x] (13) « Relancer » en haut de la fiche : arriver sur le bloc de relance bien en vue (et vérifier Encaisser et les autres ancres).
- [x] (14) Encaisser : option « Chèque postdaté » (date future : chèque en main, déposé à sa date).
- [x] (4) Dépenses : choisir une capture ou une photo de la photothèque (reçus de l'app Shell), pas seulement la caméra.
- [x] (9) Flèche de retour en haut (sans enregistrer), partout sauf les 5 onglets.
- **Lot A en prod le 12 novembre 2026** (383 tests, vérifié dans Chrome).
- [x] (10) Fluidité : analyse écran par écran du retour après un enregistrement (ex. message ouvert depuis la fiche : retour à la fiche; « Répondre » sur un message), **présentée à JF avant d'être appliquée** (accord de JF le 12 novembre 2026 : un seul retour, la flèche; retour d'où l'on vient après un enregistrement; Répondre, Appeler, Lier à un client sur un message). En prod.

**Ajouts de JF (12 novembre 2026)**
- [x] Chaque utilisateur change lui-même son mot de passe (Plus, « Mon mot de passe »). En prod le 12 novembre 2026.
- [x] Double authentification (MFA) par Google Authenticator (13 novembre 2026) : en prod, **au choix pour l'instant** (`LMAPP_DOUBLE_AUTH_OBLIGATOIRE=0` dans le `.env` de la prod); en test, obligatoire pour les administrateurs.
- [ ] **JF, avec Louis** : rendre la double authentification obligatoire en prod (`LMAPP_DOUBLE_AUTH_OBLIGATOIRE=1`, puis `docker compose up -d`); Louis installe Google Authenticator et note ses codes de secours.
- [x] **Nouveau `site.zip` déposé et vérifié en ligne** (13 novembre 2026 : fonctions à jour, 8 captures, 6 cellulaire et 2 bureau, style.css et consentement.js en version 20261113-1).
- [ ] **Audit de sécurité** (`docs/audit-securite.md`, 13 novembre 2026) : 19 recommandations. **Faits (go de JF) : 5 (sessions de 12 h pour l'administration, « Déconnecter mes autres appareils »), 9 (alertes de sécurité par courriel), 10 (Argon2).** **4 et 6, étape 1 faite** (rapports DMARC à dmarc@, CSP en rapport seulement); vers le 20 novembre 2026 : lire `rapports_dmarc` et les rapports CSP, puis proposer à JF DMARC quarantine et la CSP active. Reste à décider : les autres, et le point 7 (redémarrage).
- [x] Données de test riches dans test.ledeneigeur.com (12 novembre 2026) : 19 clients, scénarios de tous les cas. Recommencer à neuf : `cd /srv/lmapp/test && docker compose run --rm app python manage.py donnees_essai --reinitialiser`.

**Lot B : tournée avec ou sans avis aux clients (avant les premières neiges)** : fait et en prod le 13 novembre 2026.
- [x] (7) Au démarrage, chaque fois (jamais retenu par le cellulaire) : « Avec avis aux clients » ou « Sans avis aux clients » (choix de Louis, selon son jugement, pas de règle d'heure). Sans avis : position active pour les statistiques, **aucun avis** pendant toute l'opération (début, proximité, terminé, manuels). Bandeau visible sur l'écran de tournée. La position ne dépend plus des avis.
- [x] (2) Fiche du client : ne pas recevoir les avis de proximité ni les avis « terminé ».
- [x] (8) « Propriétaire non occupant (ne pas envoyer les avis de déneigement) » : le propriétaire garde factures, relances, reçus et contrat; les avis de déneigement vont aux locataires inscrits (« Autre personne à joindre »). ARRÊT d'un locataire : ses avis seulement.

**Lot C : temps mesuré** : fait et en prod le 13 novembre 2026.
- [x] (1) Temps passé à chaque entrée (par la position), gardé par opération; rapport de tournée, statistiques à la demande et en fin de saison, par client, pour ajuster le prix. Fait le 13 novembre 2026 : `tournee/temps.py` (calculé à la fin de l'opération), rapport (Tournée, Dernières opérations), « Temps par client » (Plus), revenu par heure sur place.
- [x] (3) Job de déneigement manuel depuis la fiche : départ (GPS), distance et temps de route, temps sur place; gardé; facturation à la pièce d'après ces données.

**Lot D : clients d'été (paysagement)** : fait et en prod le 13 novembre 2026 (taux de Louis à inscrire dans Réglages, Factures et taxes, quand on les aura).
- [x] (5) Fiche du client : hiver, été, ou été et hiver. Factures à la pièce (temps, matériel, déplacement) depuis la fiche, PDF envoyé au client. Tournée, contrats et avis d'hiver sans les clients d'été seulement.

**Lot E : nouveau client en un passage** : fait et en prod le 13 novembre 2026 (et date d'envoi de la facture, pour un client inscrit en plein été : demande de JF du 13 novembre) (contrat de la saison dans « + Nouveau client », services et prix, versements; facture de la saison prête; « Émettre et envoyer » d'une tape; prix des saisons en haut de la fiche).
- [x] (11b) Création : où mettre la neige, obstacles, nombre de versements, services et prix de la saison, puis contrat, facture PDF et « Envoyer la facture » dans la fiche. Client existant : prix des saisons précédentes dans la fiche.

**Lot F : cartes** : fait et en prod le 13 novembre 2026.
- [x] (16) Entrées numérotées sur la carte en direct **et** dans « Ordre de la tournée » : jaune pas encore fait, vert fait, rouge sauté; adresses mal placées (géocodage à la ville près) listées à part.

**Lot G : météo** : fait et en prod le 13 novembre 2026 (`core/meteo_point.py`).
- [x] (15) Option 1 retenue par JF : modèles d'Environnement Canada (GeoMet, grille fine) au point exact de chaque ville desservie; avertissements officiels de la page régionale.

**Décisions de JF (12 novembre 2026)** :
- [x] **Fait le 13 novembre 2026, en prod.** **Contrat saisonnier : une seule facture par client et par saison, pour le total**, émise à la signature, avec l'échéancier (montants et dates des versements) imprimé dessus; les paiements s'appliquent à cette facture. **À la date d'un versement, pas de nouvelle facture : un rappel de versement** au client (montant, date, lien de la facture), proposé à Louis d'une tape. Relances : retard compté depuis le versement échu non payé. Chèques postdatés rattachés au versement. Import : taxes une seule fois sur le total. **Remplace la facture par versement (B3)**; à faire avant l'import du fichier de Louis.
- **Contrat au passage : une facture par passage, payable sur réception** (délai réglable dans les Réglages). À la fin de l'opération, écran « Factures des passages », tout coché, émises et envoyées d'une tape (un Fait corrigé en Sauté ne laisse rien à annuler).
- Nouveau client (lot E) : la facture créée est donc celle de la saison au complet.
- Taux de Louis : question ajoutée dans sa section.
- **Propriétaire non occupant** (lot B) : factures, relances, reçus et contrat au propriétaire seulement, **jamais aux locataires**; avis des opérations (début, proximité, terminé, manuels) aux locataires seulement, **jamais au propriétaire**.

**Android** : rien à refaire (app web). Essai de 10 minutes sur un vrai Android à faire en test (connexion, tournée, position, photo, notification).

### Possible sans attendre

- [x] Premiers écrans de Louis (PWA mobile) : connexion, recherche, fiche client. En prod le 7 novembre 2026.
- [x] Icône de l'app (flocon jaune, générique) : iPhone, manifeste PWA, onglet. En prod le 7 novembre 2026.
- [x] Avant l'ouverture à toutes les IP : limiter les essais de connexion (fait le 7 novembre 2026 : blocage temporaire après 10 échecs par IP ou 20 par nom d'utilisateur en 15 minutes, `/connexion/` et `/admin/`).
- [x] `/admin/` réservé aux IP de JF et HSTS, dans Caddy (7 novembre 2026). Pour l'instant : IP de la maison seulement.
- [x] **Ouverture du 443 à tous : faite le 9 novembre 2026** (règles NAT séparées par JF : 443 public, 22 dans `_SLAPP`; balayages « avant » et « après » conformes; essais au cellulaire conformes).
- [x] Règle NAT désactivée « QNAP Danik » qui visait encore l'IP de ld1 : supprimée par JF le 9 novembre 2026.
- [x] Twilio, numéro 450-300-1166, « A message comes in » vers `https://louis.ledeneigeur.com/webhooks/twilio/textos/` (POST), configuré par JF. **Réception des textos vérifiée en prod le 9 novembre 2026** : texto « Bonjour » de JF reçu (signature valide, 200), dans les Messages de Louis, non lu.
- [x] Désabonnement par texto (E11) vérifié en prod le 9 novembre 2026, avec un client fictif au cellulaire de JF : « ARRÊT » désabonne (réponse en français reçue par JF), « COMMENCER » réabonne. Client fictif et les 5 textos d'essai effacés le jour même (journal vidé pour ce client).
- [x] Numéro de texto d'affaires 450-300-1166 inscrit dans la fiche de Louis en prod (9 novembre 2026, go de JF), pour la réception. Envois réels toujours éteints. `TWILIO_URL_STATUT` dans le `.env` de la prod (suivi de livraison).
- [x] Sauvegarde de la base (K3) toutes les 12 heures : en prod le 7 novembre 2026, test de restauration réussi.
- [x] Volet argent, les 5 étapes (étape 5, envois de factures, relances et reçus : 8 novembre 2026). Étape 1 : modèle (saisons, services, contrats et versements, factures, paiements, soldes d'ouverture) et administration. **En prod le 8 novembre 2026** (aucune facture encore; numérotation à 1 en attendant le numéro du carnet de Louis). Étape 2, PDF de la facture : **en prod le 8 novembre 2026** (lien « Voir le PDF » dans l'administration). Étapes 3 et 4, écrans de Louis (facture au cellulaire, paiements comptant, Interac, chèque, débit) et comptes à recevoir : **en prod le 8 novembre 2026**. Aussi, en prod : import des prix (contrats) et des soldes dus avec les clients, colonnes bleues du gabarit; brouillons créés chaque nuit pour les versements de contrat arrivés à leur date (C5). Ensuite : envois et relances (attendent Twilio et SMTP2GO).
- [x] Phase 2 (3 étapes), en prod. Étape 1 : opérations et passages (F1 à F6, F8, F11) : **en prod le 8 novembre 2026**. Étape 2, mode hors ligne (F10) : **en prod le 8 novembre 2026** (essayé dans un vrai navigateur : réseau coupé, page rechargée sans réseau, envoi au retour). Étape 3, avis de proximité (G1 à G5) : **en prod le 8 novembre 2026**, préparés sans envoi tant que Twilio n'est pas là (essayé dans un vrai navigateur avec une position simulée). Ordre de la tournée à l'écran (F1, boutons ▲ et ▼ par arrêt et par secteur) : **en prod le 8 novembre 2026**. Reste pour plus tard : position de Louis sur une carte (G6, V2).
- [x] Archivage des courriels dans la base et nettoyage des boîtes de 2 Go (réception et envoyés, effacés après 30 jours) : **en prod le 8 novembre 2026**. Les 7 courriels déjà là (4 reçus, 3 envoyés) archivés et relus sans erreur; premiers effacements vers le 8 décembre 2026.
- [x] Virements Interac (D5) : **en prod le 8 novembre 2026** (avis simulé, proposé sur la bonne facture, enregistré d'une tape). Reste du côté de Louis : voir « Courriel et Interac ».
- [x] Courriels reçus (E5, E6, E7) : **en prod le 8 novembre 2026**. Fiche de Louis : adresse de réponse `louis@ledeneigeur.com` (interrupteur des envois toujours éteint). Lecture de la boîte aux 2 minutes, partie du UID 4 (historique non importé).
- [x] Relances graduées (C8) : **en prod le 8 novembre 2026** (rappel reçu par JF à son adresse Peripheriq, facture jointe; texto vers un numéro fictif bloqué comme prévu). Jalon de la phase 1 : la première vraie relance, quand Louis aura ses clients et que l'interrupteur sera allumé.
- [x] Envoi des courriels et facture par courriel (E3, C4) : **en prod le 8 novembre 2026** (interrupteur de Louis éteint; adresse d'affaires et numéro de texto à mettre dans sa fiche le moment venu) (facture d'essai 1001 envoyée à JF, PDF joint, copie dans les envoyés : reçue en boîte de réception chez Gmail, et chez Peripheriq derrière Proofpoint après quelques minutes de retard).
- [x] Envoi des textos par Twilio (M1) : **en prod le 8 novembre 2026**; numéro 450-300-1166 dans la fiche de Louis le 9 novembre. Interrupteur « envois réels activés » éteint (rien ne part); en test, seulement le cellulaire de JF. Allumage : voir la tâche de JF.
- [x] Reçus de paiement (C13) : **en prod le 8 novembre 2026**. Case « Envoyer un reçu au client » (cochée) au paiement, et à l'enregistrement d'un virement Interac; canal préféré du client, facture jointe au courriel, solde restant.
- [x] À collecter (D3) : **en prod le 8 novembre 2026**. Montant à collecter sur la carte de l'arrêt (client au comptant), liste « À collecter » dans l'ordre de la tournée (gardée hors ligne).
- [x] Bilan de la saison (J1) dans l'écran Comptes : **en prod le 8 novembre 2026** (facturé, encaissé, taxes, clients servis, opérations et passages).
- [x] Écrire à un client depuis sa fiche (E2, E3) et envoi groupé à tous ou à un secteur (E10, avis de service ou commercial selon la LCAP) : **en prod le 8 novembre 2026**.
- [x] Notifications sur le cellulaire (E8, Web Push) : **en prod le 8 novembre 2026** (abonnement et envoi réussis avec Chrome). Essai sur iPhone : tâche de JF.
- [x] Demandes des clients (H1, H2) : **en prod le 8 novembre 2026** (créée depuis un message reçu dans le navigateur, urgente cochée d'office pour un oubli).
- [x] Lien public de la facture (L1) et facture par texto (C4) : **en prod le 8 novembre 2026** (page sans compte par lien secret, PDF, « Ouverte par le client »). Les clients n'y auront accès qu'à l'ouverture du 443 au public.
- [x] Appels notés à la main dans le fil du client (E6) : **en prod le 8 novembre 2026** (reçu ou fait, résumé, demande possible).
- [x] Loi 25, minimum (K5) : **en prod le 8 novembre 2026** : effacement à la demande du client (administration, avec confirmation) et registre des incidents de confidentialité. Reste : politique de confidentialité à valider (site).
- [x] Photo de l'entrée (A5) : **en prod le 8 novembre 2026** (appareil photo du cellulaire, réduite avant l'envoi, gardée dans la base).
- [x] État de compte PDF par client (C10) et export pour le comptable en CSV (C12) : **en prod le 8 novembre 2026**. Format propre à QuickBooks, Sage ou Acomba : quand Louis dira quel logiciel son comptable utilise (question « Comptabilité »).
- [x] Journal des actions (K4) : **en prod le 8 novembre 2026** (administration, « Journal des actions »; gardé 2 ans).
- [x] Photo du passage (F7) : **en prod le 8 novembre 2026** (bouton « + Photo » à l'arrêt, heure et position, avant ou après; réseau requis).
- [x] Surveillance (PRD 6.7) : **en prod le 9 novembre 2026** (service `surveillance`, alertes à JF par texto pour les pannes graves, par courriel pour le reste; essai réel réussi).
- [x] Plusieurs personnes à joindre par client (A3) : **en prod le 9 novembre 2026**.
- [x] Balises (A11) : **en prod le 9 novembre 2026** (écran « Balises » : à poser, à retirer).
- [x] Saison suivante copiée de la précédente, prix ajustés en % (B5) : **en prod le 9 novembre 2026**.
- [x] Contrat en PDF envoyé au client par courriel ou texto (B6) : **en prod le 9 novembre 2026**.
- [x] Trop-perçu gardé en crédit et appliqué à la facture suivante (D7) : **en prod le 9 novembre 2026**.
- [x] Livraison et coût de chaque texto (E13), totaux dans le tableau de la plateforme : **en prod le 9 novembre 2026**.
- [x] Revenus par secteur (J2) et rapport de fin de saison pour le comptable (J3, PDF) : **en prod le 9 novembre 2026**.
- [x] Dossier de dommage : photos, entente de réparation, coût (H3) : **en prod le 9 novembre 2026**.
- [x] Prévisions d'Environnement Canada sur l'écran de tournée (I1) : **en prod le 9 novembre 2026** (ville de prévision : Saint-Sauveur).
- [x] Carte en direct de la position du cellulaire pendant une opération, pour JF et les administrateurs (G6) : **en prod le 9 novembre 2026**.
- [x] Tableau de bord de la plateforme (Q1, `/admin/plateforme/`, superutilisateur seulement) : **en prod le 8 novembre 2026** (boîte de Louis : 0,2 Mo sur 2 Go). Segments de textos comptés à l'envoi, quota de la boîte lu à chaque passage.
- [x] Site Internet de présentation (Q5) : **en ligne sur le cPanel de JF le 9 novembre 2026** (fichiers vérifiés identiques à l'archive). Boîte `info@` branchée (demandes dans l'administration, transférées à JF), alertes de la surveillance envoyées de `info@`. Reste : tâche de JF.
- [ ] Arrivée d'un déneigeur venant d'un logiciel concurrent (Q3) : ~~correspondance des colonnes à l'import~~ (fait le 8 novembre 2026 : entêtes anglais reconnus, `--depuis <logiciel>`, `--correspondance`). Reste : un fichier de correspondance par logiciel, à faire avec un vrai export en main.
- [x] Ajout d'un déneigeur en quelques minutes (Q4) : commande `ajouter_deneigeur` (en prod), et administration à `admin.ledeneigeur.com` (Q6) **en prod le 8 novembre 2026** (DNS par JF, bloc Caddy, `/admin/` de `louis` en 404).
- [x] **Échéancier des contrats (B3, C5)** : en prod le 9 novembre 2026. Fiche de l'entreprise (versements par défaut, dates, jours d'avance), échéancier créé par l'import (colonne `versements`) et par l'administration, facture préparée d'avance avec avis au cellulaire, écran « Versements à envoyer » (une tape). Vérifié dans Chrome en test.
- [x] **Chèques postdatés (D9)** : en prod le 9 novembre 2026. Fiche du client (« + Chèque postdaté »), écran `/cheques/` (déposé d'une tape à sa date, retourné, rendu), avis au cellulaire le jour venu, mention sur la facture et son PDF, pas de relance proposée pendant qu'un chèque est en main. Reste à voir avec Louis : une colonne d'import pour les chèques qu'il a déjà en main, si c'est utile.
- [x] **Dépenses par photo (PRD S1, S2)** : en prod le 9 novembre 2026. Comptes, « Dépenses (photo du reçu) » : photo, total, catégorie, taxes calculées; rapport de saison (PDF) et export CSV. Lecture automatique du reçu (S3) : plus tard, avec une clé d'API.
- [x] **Audit UX/UI du 9 novembre 2026** (`LMAPP audit UX UI (mobile et administration).md`) : appliqué et en prod le 9 novembre 2026 (sauvegarde de la prod et du test, étiquette Git `avant-audit-ux-20261109-221429` avant de commencer). Fait : confirmation à maintenir 1 seconde avant « Démarrer » quand des clients sont avisés, puis 10 secondes pour retenir les avis; Démarrer en haut, météo sur une ligne; barre d'onglets en bas (Tournée, Clients, Argent, Messages, Plus), Déconnexion dans Plus; bandeau « Simulation » tant que les envois réels sont éteints; fiche client (Appeler, Écrire, Itinéraire, solde, Encaisser, Relancer en haut); « Reçu 344,93 $ » collé en bas d'une facture due, feuille de paiement; page Argent en « À faire » et « Outils »; balises, ordre, pastilles des factures, messages (avis Interac en carte d'action); formulaire client court; total avec taxes en direct; contrastes, focus, dates « 1er nov. »; mode Soleil; Fait et Sauté côte à côte, écran gardé allumé; administration (bandeau PRODUCTION, état des envois réels, accueil en cartes, titres en français, pas de suppression d'entreprise ni de client, thème, pages 404 et 500).
- [x] **Audit UX, deuxième vague (approuvée par JF, 9 novembre 2026)** : « Annuler » 5 secondes après Fait ou Sauté, indicateur GPS, app de navigation choisie dans Plus, écran vert après un paiement, rang tapé directement dans l'Ordre (à la place du glisser-déposer), vue bureau (onglets à gauche, fiche et Argent en deux colonnes). Aussi : ville de la météo choisie dans Plus.
- [ ] Audit UX, pas retenu ou pas encore décidé par JF (lui demander avant de faire quoi que ce soit) : mode Nuit forcé au coucher du soleil (refusé); icône des Demandes (porte-voix gardé). Faits le 10 novembre 2026 : tableau de la plateforme en cartes (4 blocs), filtres de l'administration en panneau au-dessus des listes sous 1280 px. Page « Réglages » de Louis dans Plus : faite le 10 novembre 2026 (fiche, secteurs, services, saisons, villes, utilisateurs). Contrats et soldes antérieurs dans la fiche du client : faits le 10 novembre 2026. Louis passé administrateur (go de JF). Réglages pendant une opération : accès de la personne en tournée bloqué, confirmation pour elle.
- [ ] Saison d'été, paysagement (PRD T) : à définir avec Louis, plus tard.
- [x] Facturation des entreprises par l'app (Q2) : faite le 11 novembre 2026 (brouillon le 1er du mois, émission et envoi par JF dans l'administration, écran « Mon abonnement » pour le déneigeur). **Reste à JF** : numéros de TPS et de TVQ de SLAPP, adresse complète, délai de paiement (15 jours par défaut) et instructions de paiement, à mettre dans le `.env` (`PLATEFORME_*`); dire si Louis est facturé (case « abonnement facturé » de sa fiche, éteinte).
- [x] Avis « Ébauche » retiré de la politique de confidentialité, durées réelles écrites, `site.zip` refait (9 novembre 2026).
- [x] **Répétition de bout en bout en test** (10 novembre 2026, demande de JF) : import fictif de 13 lignes (taxes incluses, extra, reçu avant l'app, solde antérieur, deux adresses d'un payeur, ex-client qui doit, ville non desservie, erreurs, doublon), relance de l'import sans doublon, brouillons de versement (tâche de nuit), « Émettre et envoyer 8 factures », crédit appliqué à l'émission, paiements avec reçu et surplus en crédit, relance, chèque postdaté, bilan et rapport de saison recomptés à la main. Corrigé : `donnees_essai --reinitialiser` plantait (virements, demandes); entreprise d'essai sans dates de versement; texte de l'import qui annonçait le 1er versement facturé « à l'import » (c'est la nuit suivante); reçu qui taisait le surplus gardé en crédit (600 $ remis, reçu de 570 $) et « virement interac » en minuscule.
- [ ] Test de restauration chaque mois (`sh outils/tester_restauration.sh`), prochain vers le 7 décembre 2026.

### En attente

- Prix et services de Louis (questions 4 et 5) : contrat saisonnier seulement (réglé le 8 novembre 2026), 2 versements par défaut, 3 au-delà de 1 200 $ par saison (seuil et dates en configuration). Le modèle accepte aussi « au passage », gardé pour plus tard. Reste la question 5 (services).
- Deuxième déneigeur (PRD section P) : tout est prêt (`ajouter_deneigeur`, administration à `admin.ledeneigeur.com`). Les étapes réseau (Cloudflare, `Caddyfile`, `DJANGO_ALLOWED_HOSTS`, boîte, Twilio) se feront avec le go de JF, quand il y en aura un.

## Fait

- 9 novembre 2026, en prod : fiche de Louis réglée pour ses versements (2 par défaut, dates « 15/01 15/02 », factures préparées 5 jours d'avance); services « Déneigement de l'entrée » et « Bordage » créés (sans prix : le prix est au contrat).
- 9 novembre 2026, en prod : **durées de conservation** (positions GPS effacées après 120 jours, demandes à info@ après 2 ans), écrites dans la politique de confidentialité.
- 9 novembre 2026, en prod : **boîte `info@ledeneigeur.com` de la plateforme** lue aux 2 minutes, chaque demande gardée dans l'administration (statut, note) et transférée à JF. Premier transfert parti (courriel de configuration de cPanel). Alertes de la surveillance envoyées de `info@` (essai reçu par JF).

- 9 novembre 2026, en prod (essayés en test d'abord) : **relances proposées (C9, option B)**, éteintes par défaut (case « relances proposées chaque matin » dans la fiche de l'entreprise, à allumer avec Louis); **gabarits par défaut** dans la console de JF (administration, « Gabarits par défaut (toutes les entreprises) »), écran « Messages types » des déneigeurs (lecture seule, cloner, revenir au défaut); **photos jointes aux messages (E14)**; **alertes de la surveillance en silence pendant les déploiements** (`outils/silence.sh`). UptimeRobot sur `/sante/` (JF).

- 7 novembre 2026 : dépôt Git (copie sur GitHub privé), squelette Django, Docker (projets `edge`, `lmapp`, `lmapp-test`), vrais certificats Let's Encrypt, ouverture filtrée par IP au routeur (IP réelle conservée), modèle des clients, import Excel et CSV avec gabarit, géocodage avec zone de service Sainte-Adèle, données d'essai, déploiements en prod, comptes administrateur de JF en prod et en test.

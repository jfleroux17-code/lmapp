# LMAPP : tâches à faire

Liste tenue à jour par Claude Code sur ld1, à chaque étape. Le plan complet est dans `PRD.md`, les consignes techniques dans `CLAUDE.md`.

Mise à jour : 8 novembre 2026.

## Où on en est

- L'app tourne en prod (`louis.ledeneigeur.com`) et en test (`test.ledeneigeur.com`) : HTTPS avec vrais certificats, accès limité à `_SLAPP` par le Mikrotik, sauvegarde avant chaque déploiement, retour en arrière possible (images étiquetées par commit).
- En place : modèle des clients (entreprise, villes desservies, secteurs, clients, adresses), import par fichier Excel ou CSV, géocodage limité à la zone de Sainte-Adèle.
- **La base de prod est vide.** Rien n'avance côté Louis tant que sa fiche `Entreprise` et sa liste de clients n'y sont pas.

## Jean-François

### Ce qui bloque la suite

- [x] Créer ses comptes administrateur (prod et test).
- [ ] Essayer les premiers écrans sur son iPhone, en test : `https://test.ledeneigeur.com/` (avec son compte administrateur de test; réseau de la maison ou du bureau, à cause du filtre `_SLAPP`). Dans Safari : Partager, « Sur l'écran d'accueil ».
- [x] Fiche de Louis créée en prod (Louis Méthot Déneigement, `louis`, `louis.ledeneigeur.com`, Sainte-Adèle 8 km, centre rempli).
- [x] Sainte-Adèle cochée « ville par défaut » dans la fiche de Louis.
- [x] Utilisateur `louis` créé, membre « Opérateur » (entre dans l'app, pas dans l'administration).
- [x] Fiche de Louis complétée en prod (8 novembre 2026) : nom légal, adresse, téléphone, courriel, inscrit aux taxes, numéros de TPS et de TVQ (dans la fiche seulement). Le nom affiché reste « Louis Méthot Déneigement » jusqu'à la réponse à la question 14.
- [ ] Envoyer le gabarit d'import à Louis, ou transcrire ses papiers : `scp deploy@172.16.4.100:/srv/lmapp/gabarits/gabarit_import_clients.xlsx .`
- [ ] Poser à Louis les questions de la section « Louis » ci-dessous.

### Comptes de services (textos et courriels, phase 1)

- [x] Boîte `louis@ledeneigeur.com` sur le serveur de courriel de JF (`woww.joxs.net`), à la place de SMTP2GO. Connexion IMAP et SMTP vérifiée depuis le worker (8 novembre 2026). MX, SPF et DMARC ajoutés chez Cloudflare.
- [x] DKIM de `ledeneigeur.com` (sélecteur `default`) publié chez Cloudflare (8 novembre 2026).
- [ ] JF : DNS inverse de 216.46.12.228 vers `woww.joxs.net` : **demandé à Beanfield, en attente**.
- [x] Premier courriel d'essai à JF (8 novembre 2026) : SPF, DKIM et DMARC « pass », mais arrivé dans les pourriels (domaine neuf, DNS inverse générique). IP sur aucune liste noire vérifiée.
- [ ] JF : dans Gmail, « non-spam », ajouter `louis@ledeneigeur.com` aux contacts et répondre au courriel d'essai. Facultatif : Google Postmaster Tools pour `ledeneigeur.com` (valeur TXT à donner à Claude Code).
- [x] Twilio : compte payant, numéro 450-300-1166, `TWILIO_ACCOUNT_SID` et `TWILIO_AUTH_TOKEN` dans les deux `.env` (8 novembre 2026). Premier texto d'essai livré au cellulaire de JF, depuis le test.
- [x] ~~SMTP2GO~~ : abandonné le 8 novembre 2026 (décision de JF), remplacé par le serveur de courriel de JF.
- [x] ~~Boîte IMAP `info@`~~ : remplacée par `louis@ledeneigeur.com` (une boîte par déneigeur), en place.
- [ ] Stripe : seulement si des clients veulent payer par carte (question 8 de Louis).

### Serveur (rien d'urgent)

- [ ] Netplan par MAC (décision du 7 novembre 2026), configuré par JF avec de l'aide. Instantané avant, `sudo netplan try` depuis la console Hyper-V. Si la MAC reste dynamique dans Hyper-V, la VM peut perdre son réseau quand elle est déplacée ou réimportée.
- [ ] Redémarrer ld1 à un moment tranquille (services signalés par apt).
- [x] Vérification externe de `https://louis.ledeneigeur.com/sante/` : UptimeRobot configuré par JF le 9 novembre 2026 (sondes vues dans les journaux de Caddy, réponse 200).
- [x] `sudo ufw status verbose` (7 novembre 2026) : refus par défaut en entrée; SSH depuis `172.16.4.0/24`; 80 et 443 ouverts à tous (ufw ne s'en mêle pas pour le 443 de toute façon, Docker le contourne; rien n'écoute sur le 80). Port 5000 : `BackupFP` (COVE), sur toutes les interfaces, mais bloqué par ufw (aucune règle) : rien à faire.
- [ ] `sudo ss -tlnp 'sport = :36789'` : processus inconnu sur un port local (127.0.0.1 seulement, donc pas joignable de l'extérieur).
- [ ] Donner l'IP publique du bureau pour l'accès à `/admin/` (seule celle de la maison est permise). Elle ira dans `edge/.env`, jamais dans Git.
- [ ] Donner les plages d'adresses des autres réseaux (VPN, bureau, centre de données) : conflit possible avec les plages 172.17 à 172.31 de Docker.
- [x] Copie du dépôt hors de ld1 : GitHub privé `jfleroux17-code/lmapp`, poussé après chaque étape.
- [x] Dépôt GitHub branché dans le Projet Claude de JF (`PRD.md`, `CLAUDE.md`, `TACHES.md`). Après un envoi, synchroniser la source GitHub dans le projet pour voir la dernière version.
- [x] Sauvegardes hors de la VM : COVE, toutes les 12 heures (décision du 7 novembre 2026).
- [x] Heures de COVE inconnues : la base est sauvegardée toutes les 12 heures (3 h 30 et 15 h 30), COVE emporte toujours une copie de moins de 12 heures.
- [x] COVE inclut `/srv/lmapp/sauvegardes/` : sélection `/` au complet (vérifié le 7 novembre 2026, `sudo /opt/MXB/bin/ClientTool control.selection.list`). La copie brute de `/var/lib/docker` (base en marche) n'est pas fiable pour restaurer : toujours repartir des fichiers `.dump`.
- [ ] Trancher les fonctionnalités V1 dans le catalogue du PRD (section 5), au besoin.
- [ ] Offre aux autres déneigeurs (PRD section Q) : **prix revu le 8 novembre 2026 : 99 $ par mois**, un volume de textos et courriels compris, surplus facturé, nouveaux modules à part. Reste, quand les occasions viendront : le **volume compris** et le **prix du surplus** (coût Twilio : 1,15 $ US par mois par numéro, 0,0083 $ US par segment entrant ou sortant). Le tableau de bord `/admin/plateforme/` donne déjà les quantités par mois.
- [x] Site Internet (Q5) : nom **« Le Déneigeur »**, exploitant SLAPP Technologies Inc., contact `info@ledeneigeur.com` (boîte à créer par JF) et 514 360-3227. **Hébergé sur le cPanel de JF** (racine et `www` déjà pointées par JF). Archive prête : `/srv/lmapp/site.zip`, à extraire dans `public_html`.
- [ ] Module voix (PRD section R) : **à trancher plus tard**, après l'ouverture du 443 et la réception des textos (décision de JF, 8 novembre 2026). Propositions gardées : R1 (messagerie vocale) en premier, enregistrements gardés 90 jours. Rien n'est commencé. Modèle d'IA : pas de clé de l'API Claude pour l'instant (modèle local possible).
- [ ] Contrat de service avec les déneigeurs (Q7) : **JF s'en occupe de son côté**, pas urgent tant que Louis est le seul client.

## Louis

Questions de la section 10 du PRD, les plus importantes d'abord.

- [x] **Taxes** : inscrit à la TPS et à la TVQ, numéros reçus (8 novembre 2026). Les factures auront les taxes.
- [ ] **Numéro de facture** : quel est le dernier numéro utilisé dans son carnet papier? La numérotation de l'app continuera à partir du suivant (sinon elle commence à 1).
- [ ] **Nom affiché** : ses factures portent « Les Entretiens Paysagers L.M. » (logo « Entretiens LM »). Proposé : nom légal sur les factures, et un nom que ses clients reconnaissent (ex. « Entretiens LM ») à l'écran et à la fin des textos. À confirmer.
- [x] **Versements** (8 novembre 2026) : contrat saisonnier en 2 versements égaux, le 1er novembre et entre la mi-janvier et la fin de janvier; 3e versement possible pour les contrats de plus de 1 200 $ par saison.
- [x] **Type de contrat** : saisonnier seulement, pas de facturation au passage.
- [ ] **Détails des versements** : date du 2e versement (fixe ou au cas par cas)? Dates d'un échéancier en 3 versements? (Louis rappelle JF le 9 novembre.)
- [ ] **Clients** : combien d'actifs? Combien d'anciens clients lui doivent de l'argent, et à peu près combien en tout?
- [ ] **Sa liste de clients** dans le gabarit, ou en photos de ses papiers (noms, adresses, cellulaires, prix entendus, montants dus).
- [ ] **Services** : entrée seulement, ou aussi bordage de la ville, pelletage, abrasif, toitures?
- [ ] **Numéro de texto** : accepte-t-il que les clients textent un nouveau numéro d'affaires? Ses clients ont son 514-962-6273, qui pourrait rester pour les appels seulement.
- [ ] **Courriel et Interac** : ses clients connaissent son Gmail (sur ses factures). Reste : dépôt automatique Interac, sur quelle adresse?
- [ ] **Carte de crédit et débit** : des clients veulent-ils vraiment payer par carte? Son carnet a une case « carte débit » : a-t-il un terminal de paiement?
- [ ] **Véhicules** : un seul, ou un tracteur et un camion? (Sainte-Adèle seulement et seul pour l'instant : réglé.)
- [ ] **Comptabilité** : qui la fait, dans quel logiciel?
- [ ] **Clients commerciaux** : stationnements, immeubles à logements?
- [ ] **Matériel** : support de téléphone et chargeur pour le tracteur.

## Claude Code

### Priorité : demandes de JF du 8 novembre 2026 (avant que Louis essaie l'app)

Après son essai des écrans. Une étape à la fois, chacune en test, montrée à JF sur son iPhone avant la suivante.

- [ ] **Mode de l'entreprise** (PRD K9) : **en prod le 8 novembre 2026**. champ dans `Entreprise`, « déneigeur seul » ou « équipe ». Seul : le propriétaire fait tout dans l'app. Équipe : seuls les administrateurs de l'entreprise modifient les clients, les opérateurs consultent. Louis en « déneigeur seul ».
- [ ] **Bouton Annuler partout** (PRD K10) : **en prod le 8 novembre 2026** (formulaires de saisie). sur chaque écran, ramène à l'écran précédent sans rien enregistrer. Rien ne s'enregistre sans un bouton Enregistrer.
- [ ] **Modifier un client dans l'app** (PRD A12) : **en prod le 8 novembre 2026** (ajout essayé dans le navigateur). ajout et modification du client et de ses adresses (coordonnées, particularités du terrain, statut, notes) depuis la fiche, au cellulaire, sans l'administration. Gros champs, clavier adapté (téléphone, courriel, code postal).
- [ ] **Corriger la position d'une adresse dans l'app** (PRD A13) : **en prod le 8 novembre 2026** (carte Leaflet, tuiles OpenStreetMap). carte plein écran avec repère fixe au centre (on déplace la carte, pas le point), bouton « Je suis devant » (GPS du téléphone), Enregistrer ou Annuler. La position devient `manuelle` ou `gps`, jamais écrasée par le géocodage.
- [x] **Revoir le visuel** : **visuel C (sombre plus net) choisi par JF et en prod le 8 novembre 2026** : noir pur, 20 px de base, cartes et titres plus marqués, onglet actif plein.

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
- [ ] Virements Interac (D5) : **en prod le 8 novembre 2026** (avis simulé, proposé sur la bonne facture, enregistré d'une tape). Pour la prod : Louis confirme son adresse Interac et transfère les avis d'Interac de son Gmail vers `louis@ledeneigeur.com` (filtre Gmail). Valider la lecture sur un vrai avis.
- [x] Courriels reçus (E5, E6, E7) : **en prod le 8 novembre 2026**. Fiche de Louis : adresse de réponse `louis@ledeneigeur.com` (interrupteur des envois toujours éteint). Lecture de la boîte aux 2 minutes, partie du UID 4 (historique non importé).
- [x] Relances graduées (C8) : **en prod le 8 novembre 2026** (rappel reçu par JF à son adresse Peripheriq, facture jointe; texto vers un numéro fictif bloqué comme prévu). Jalon de la phase 1 : la première vraie relance, quand Louis aura ses clients et que l'interrupteur sera allumé.
- [x] Envoi des courriels et facture par courriel (E3, C4) : **en prod le 8 novembre 2026** (interrupteur de Louis éteint; adresse d'affaires et numéro de texto à mettre dans sa fiche le moment venu) (facture d'essai 1001 envoyée à JF, PDF joint, copie dans les envoyés : reçue en boîte de réception chez Gmail, et chez Peripheriq derrière Proofpoint après quelques minutes de retard).
- [ ] Envoi des textos par Twilio (M1) : **en prod le 8 novembre 2026**, interrupteur éteint pour Louis (rien ne part), numéro de texto pas encore dans sa fiche. Garde-fous : interrupteur « envois réels activés » dans la fiche de l'entreprise (éteint par défaut, à allumer en prod seulement avec le « go » de JF), et en test seulement le cellulaire de JF. Ensuite : réception des textos (il faut ouvrir le 443 à Twilio), envoi des factures et relances.
- [ ] Reçus de paiement (C13) : **en prod le 8 novembre 2026**. Case « Envoyer un reçu au client » (cochée) au paiement, et à l'enregistrement d'un virement Interac; canal préféré du client, facture jointe au courriel, solde restant.
- [ ] À collecter (D3) : **en prod le 8 novembre 2026**. Montant à collecter sur la carte de l'arrêt (client au comptant), liste « À collecter » dans l'ordre de la tournée (gardée hors ligne).
- [ ] Bilan de la saison (J1) dans l'écran Comptes : **en prod le 8 novembre 2026** (facturé, encaissé, taxes, clients servis, opérations et passages).
- [ ] Écrire à un client depuis sa fiche (E2, E3) et envoi groupé à tous ou à un secteur (E10, avis de service ou commercial selon la LCAP) : **en prod le 8 novembre 2026**.
- [ ] Notifications sur le cellulaire (E8, Web Push) : **en prod le 8 novembre 2026** (abonnement et envoi réussis avec Chrome). À essayer sur l'iPhone de JF : ajouter `test.ledeneigeur.com` à l'écran d'accueil, ouvrir de là, Messages, « Activer les notifications ».
- [ ] Demandes des clients (H1, H2) : **en prod le 8 novembre 2026** (créée depuis un message reçu dans le navigateur, urgente cochée d'office pour un oubli).
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
- [ ] Site Internet de présentation (Q5) : archive `/srv/lmapp/site.zip` prête le 8 novembre 2026 (liens relatifs, captures au visuel C). Reste pour JF : la déposer dans `public_html`, créer `info@ledeneigeur.com`, valider les durées de conservation de la politique et retirer l'avis « Ébauche ».
- [ ] Arrivée d'un déneigeur venant d'un logiciel concurrent (Q3) : ~~correspondance des colonnes à l'import~~ (fait le 8 novembre 2026 : entêtes anglais reconnus, `--depuis <logiciel>`, `--correspondance`). Reste : un fichier de correspondance par logiciel, à faire avec un vrai export en main.
- [x] Ajout d'un déneigeur en quelques minutes (Q4) : commande `ajouter_deneigeur` (en prod), et administration à `admin.ledeneigeur.com` (Q6) **en prod le 8 novembre 2026** (DNS par JF, bloc Caddy, `/admin/` de `louis` en 404).
- [ ] Facturation des entreprises par l'app (Q2), quand les tarifs seront fixés.
- [ ] Test de restauration chaque mois (`sh outils/tester_restauration.sh`), prochain vers le 7 décembre 2026.

### En attente

- Prix et services de Louis (questions 4 et 5) : contrat saisonnier seulement (réglé le 8 novembre 2026), 2 versements par défaut, 3 au-delà de 1 200 $ par saison (seuil et dates en configuration). Le modèle accepte aussi « au passage », gardé pour plus tard. Reste la question 5 (services).
- Deuxième déneigeur (PRD section P) : déplacer `/admin/` vers une adresse neutre réservée à JF (proposé : `admin.ledeneigeur.com`), et documenter l'ajout d'un sous-domaine (Cloudflare, `Caddyfile`, `DJANGO_ALLOWED_HOSTS`, fiche `Entreprise`). Attend qu'il y ait un deuxième déneigeur.

## Fait

- 7 novembre 2026 : dépôt Git (copie sur GitHub privé), squelette Django, Docker (projets `edge`, `lmapp`, `lmapp-test`), vrais certificats Let's Encrypt, ouverture filtrée par IP au routeur (IP réelle conservée), modèle des clients, import Excel et CSV avec gabarit, géocodage avec zone de service Sainte-Adèle, données d'essai, déploiements en prod, comptes administrateur de JF en prod et en test.

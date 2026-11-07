# LMAPP : tâches à faire

Liste tenue à jour par Claude Code sur ld1, à chaque étape. Le plan complet est dans `PRD.md`, les consignes techniques dans `CLAUDE.md`.

Mise à jour : 7 novembre 2026.

## Où on en est

- L'app tourne en prod (`louis.ledeneigeur.com`) et en test (`test.ledeneigeur.com`) : HTTPS avec vrais certificats, accès limité à `_SLAPP` par le Mikrotik, sauvegarde avant chaque déploiement, retour en arrière possible (images étiquetées par commit).
- En place : modèle des clients (entreprise, villes desservies, secteurs, clients, adresses), import par fichier Excel ou CSV, géocodage limité à la zone de Sainte-Adèle.
- **La base de prod est vide.** Rien n'avance côté Louis tant que sa fiche `Entreprise` et sa liste de clients n'y sont pas.

## Jean-François

### Ce qui bloque la suite

- [x] Créer ses comptes administrateur (prod et test).
- [ ] Créer la fiche de Louis dans `https://louis.ledeneigeur.com/admin/`, « Entreprises », « Ajouter » :
  - nom « Louis Méthot Déneigement », identifiant `louis`, domaine `louis.ledeneigeur.com`;
  - section « Villes desservies » : Sainte-Adèle, rayon 8 km, « ville par défaut » cochée (le centre se remplit seul);
  - section « Membres » : s'ajouter comme administrateur;
  - taxes décochées tant que Louis n'a pas répondu.
- [ ] Envoyer le gabarit d'import à Louis, ou transcrire ses papiers : `scp deploy@172.16.4.100:/srv/lmapp/gabarits/gabarit_import_clients.xlsx .`
- [ ] Poser à Louis les questions de la section « Louis » ci-dessous.

### Comptes de services (textos et courriels, phase 1)

- [ ] Twilio : compte, numéro local (450 ou 579), `TWILIO_ACCOUNT_SID` et `TWILIO_AUTH_TOKEN` dans `/srv/lmapp/.env` et `/srv/lmapp/test/.env`.
- [ ] SMTP2GO : sous-compte de Louis, domaine `ledeneigeur.com` vérifié (SPF, DKIM, DMARC chez Cloudflare), `SMTP2GO_API_KEY` dans les `.env`.
- [ ] Boîte IMAP (proposé : `info@ledeneigeur.com`), MX chez Cloudflare, accès dans les `.env`.
- [ ] Stripe : seulement si des clients veulent payer par carte (question 8 de Louis).

### Serveur (rien d'urgent)

- [ ] Netplan par pilote (`hv_netvsc`) plutôt que par MAC, puisque la MAC reste dynamique. Depuis la console Hyper-V, `sudo netplan try`, instantané avant. Seul point qui peut faire perdre le réseau à la VM si elle est déplacée ou réimportée.
- [ ] Redémarrer ld1 à un moment tranquille (services signalés par apt).
- [ ] `sudo ufw status verbose` et `sudo ss -tlnp 'sport = :36789'` (processus inconnu sur un port local).
- [ ] Donner les plages d'adresses des autres réseaux (VPN, bureau, centre de données) : conflit possible avec les plages 172.17 à 172.31 de Docker.
- [x] Copie du dépôt hors de ld1 : GitHub privé `jfleroux17-code/lmapp`, poussé après chaque étape.
- [ ] Brancher le dépôt GitHub dans le Projet Claude (claude.ai, connaissances du projet) : `PRD.md`, `CLAUDE.md`, `TACHES.md`.
- [ ] Où envoyer les sauvegardes nocturnes hors de la VM (stockage Peripheriq ou compartiment S3).
- [ ] Trancher les fonctionnalités V1 dans le catalogue du PRD (section 5), au besoin.

## Louis

Questions de la section 10 du PRD, les plus importantes d'abord.

- [ ] **Taxes** : inscrit à la TPS et à la TVQ? Si oui, les deux numéros. *Décide du calcul des factures.*
- [ ] **Prix** : contrat saisonnier, au passage, ou les deux? Combien de versements, à quelles dates?
- [ ] **Clients** : combien d'actifs? Combien d'anciens clients lui doivent de l'argent, et à peu près combien en tout?
- [ ] **Sa liste de clients** dans le gabarit, ou en photos de ses papiers (noms, adresses, cellulaires, prix entendus, montants dus).
- [ ] **Services** : entrée seulement, ou aussi bordage de la ville, pelletage, abrasif, toitures?
- [ ] **Numéro de texto** : accepte-t-il que les clients textent un nouveau numéro d'affaires?
- [ ] **Courriel et Interac** : adresse d'affaires déjà connue des clients? Dépôt automatique Interac, sur quelle adresse?
- [ ] **Carte de crédit** : des clients veulent-ils vraiment payer par carte?
- [ ] **Véhicules** : un seul, ou un tracteur et un camion? (Sainte-Adèle seulement et seul pour l'instant : réglé.)
- [ ] **Comptabilité** : qui la fait, dans quel logiciel?
- [ ] **Clients commerciaux** : stationnements, immeubles à logements?
- [ ] **Matériel** : support de téléphone et chargeur pour le tracteur.

## Claude Code

### Possible sans attendre

- [ ] Premiers écrans de Louis (PWA mobile) : connexion, recherche, fiche client.
- [ ] Sauvegarde nocturne de la base (K3) : préparable, la copie hors VM attend la destination.

### En attente

- `Saison`, `Contrat`, `SoldeOuverture`, `Facture`, `Paiement` : réponses de Louis sur les taxes et les prix.
- Textos et courriels : comptes Twilio, SMTP2GO et boîte IMAP.
- Import des prix et des soldes dus : modèles `Contrat` et `SoldeOuverture`.

## Fait

- 7 novembre 2026 : dépôt Git (copie sur GitHub privé), squelette Django, Docker (projets `edge`, `lmapp`, `lmapp-test`), vrais certificats Let's Encrypt, ouverture filtrée par IP au routeur (IP réelle conservée), modèle des clients, import Excel et CSV avec gabarit, géocodage avec zone de service Sainte-Adèle, données d'essai, déploiements en prod, comptes administrateur de JF en prod et en test.

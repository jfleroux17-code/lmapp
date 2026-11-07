# LMAPP : Plan de projet (PRD v1.2)

**Application de gestion pour Louis Méthot Déneigement**
Porteur du projet : Jean-François Leroux
Date : 7 novembre 2026 (v1.2 : Caddy dans un projet `edge` séparé, environnement de test en marche, vrais certificats Let's Encrypt par validation DNS, DNS `louis` et `test` en place; v1.1 : dépôt Git et pile Docker en marche sur `ld1` (validée sur le réseau interne), test sur `test.ledeneigeur.com`, ouverture au routeur filtrée par IP source, état du DNS Cloudflare et du disque en 6.1.1; v1.0 : sous-domaine louis.ledeneigeur.com, MAC dynamique, pas de port public au départ, CLAUDE.md déposé sur ld1; v0.9 : Claude Code réellement installé et connecté sur `ld1` (2.1.319); v0.8 : serveur `ld1` installé et sécurisé, IP fixe 172.16.4.100, état du serveur en 6.1.1; v0.7 : domaine ledeneigeur.com et découpage par sous-domaine; v0.6 : iPhone 17 Pro Max confirmé, décision de bâtir, SMTP2GO et boîte IMAP, hébergement sans frais, section O, specs de la VM)
Statut : brouillon à valider avant tout développement

---

## 1. Le problème

Louis gère son entreprise de déneigement entièrement à la main : liste de clients sur papier, prix entendus de vive voix, factures manuscrites ou inexistantes, suivi des paiements de mémoire. Conséquences directes :

- Des clients lui doivent de l'argent depuis des saisons antérieures et il n'a aucun outil pour les relancer rapidement.
- Les clients payés comptant ne laissent aucune trace : impossible de savoir qui a payé quoi, quand.
- Pendant une bordée, les clients appellent pour savoir quand il passe, et les autos dans les entrées ralentissent la tournée.
- Toute la communication client (appels, textos personnels) est éparpillée et perdue.

Louis travaille sur la route, cellulaire en main. Tout ce qui touche la tournée, les avis clients, les textos et la facturation doit se faire au cellulaire, à une main, avec des gants, dans un tracteur ou un camion.

## 2. Objectifs et critères de succès

### Objectifs
1. Informatiser la liste de clients, les adresses, les prix et les modes de paiement.
2. Permettre à Louis de facturer et d'encaisser depuis son cellulaire, incluant le comptant.
3. Récupérer les comptes en souffrance des saisons passées par envoi de factures et de rappels par courriel et texto.
4. Centraliser tous les échanges clients (textos, courriels) dans la fiche du client.
5. Aviser automatiquement les clients à l'approche de Louis pour qu'ils dégagent leur entrée.

### Critères de succès (mesurables, première saison)
- 100 % des clients actifs saisis avec adresse géolocalisée, prix et mode de paiement.
- Chaque passage facturable produit une facture en moins de 30 secondes au cellulaire.
- Un état des comptes à recevoir disponible en un écran, avec relance en un geste.
- Au moins une relance envoyée à chaque ancien compte en souffrance dans les deux premières semaines d'utilisation.
- Tout texto reçu d'un client se retrouve automatiquement dans sa fiche, sans intervention.
- Avis de proximité envoyé aux clients du secteur avant le passage, avec un délai configurable.
- Louis utilise l'app seul, sans assistance, après une courte formation.

## 3. Utilisateurs

| Utilisateur | Appareil | Ce qu'il fait |
|---|---|---|
| Louis (opérateur et propriétaire) | iPhone 17 Pro Max | Tournée, avis, textos, facturation, encaissement, consultation des fiches |
| Jean-François (administrateur) | Ordinateur | Configuration, import des données, correctifs, sauvegardes, supervision |
| Clients de Louis | Leur propre cellulaire ou courriel | Reçoivent des avis, des factures, des rappels; répondent par texto ou courriel; paient |
| Aide ou remplaçant (plus tard) | Cellulaire | Suit la tournée, marque les passages |

## 4. Tour d'horizon du marché québécois

Il existe déjà plusieurs logiciels de déneigement faits au Québec. Voici ce qu'ils offrent, ce qui sert de référence pour le catalogue de fonctionnalités de la section 5.

| Logiciel | Origine | Points saillants | Prix connus |
|---|---|---|---|
| **SnowTrack** (snowtrack.net) | Québec | Suivi GPS en temps réel, création de routes sur carte, app chauffeur, facturation TPS/TVQ, revenus par route, tableaux de bord. Pas de SMS ni de portail client mentionnés. | Essai 14 jours, prix non affichés |
| **Flokon** (flokon.ca) | Québec | Contrats avec signature électronique et renouvellement en lot, paiements en ligne, routes par équipe, avis clients par texto ou appel vocal avant le passage, suivi des véhicules (app ou module GPS), historique des passages avec photos horodatées, export Excel. Un client rapporte 90 % moins d'appels en tempête. | Forfaits Alertes, Gestion, Flotte; prix non affichés |
| **UsoftCRM** (usoftsolutions.ca) | Québec (depuis 2006) | Le plus complet : plusieurs contacts par client, contrats renouvelés en un clic avec ajustement de prix, appels de service et plaintes, routes optimisées, facturation auto après visite ou par versements, encaissement carte et prélèvement préautorisé, portail client, avis par courriel, texto ou message vocal, pointage GPS automatique des bons de travail, comptabilité. | Logiciel principal 1 134 $/an (la page affiche un tarif réduit de 567 $ à 300 clients ou moins, mais la facture réelle inclut le logiciel de base); module technicien 250 $/an par accès (nécessaire pour travailler au cellulaire); portail client 300 à 567 $/an; textos en sus; support 100 $/h après 2 h. Facture réaliste pour Louis : 1 400 à 2 000 $/an plus les textos. |
| **Follosoft** (via Naxella) | Québec (créé par Chasse-Neige, Laval) | Routes, flotte, estimations, textos d'avis d'arrivée pour déplacer les véhicules, données terrain en temps réel, réassignation de routes, passerelle de paiement Naxella. Utilisé par plus de 600 déneigeurs. | Non affichés |
| **Horizon CRM** (horizoncrm.ca) | Québec | Contrats saisonniers à renouvellement auto, signature électronique, facturation récurrente avec Stripe ou Clover, météo intégrée au calendrier, SMS automatiques à l'approche de la propriété, portail client, gestion de flotte, RH, sous-traitants, apps iOS et Android, intégrations QuickBooks et Sage 50. | Mensuel fixe, prix non affichés |
| **Déneigeur Pro** (deneigeurpro.ca) | Québec | Clients, routes, communications automatisées. Site peu détaillé. | Non affichés |
| **ManuGo** (manugo.io) | Québec | Généraliste services; routes, contrats récurrents, photos avant/après horodatées, facturation après intervention, rappels de renouvellement. | Non affichés |
| **ProgressionLIVE** | Québec (Trois-Rivières) | Gestion d'appels de service généraliste (CVC, plomberie). Texto « en route », bon de travail PDF, intégration comptable. Pas spécialisé déneigement. | Non affichés |
| Jobber, GorillaDesk, Service Autopilot, Upper, Arborgold | Canada et États-Unis | Généralistes de services à domicile avec module déneigement : devis, horaire, facturation, paiements par carte, CRM, routage. Interface anglaise d'abord, taxes québécoises à configurer soi-même. | Abonnements mensuels par utilisateur |

### Ce qu'on en retient

1. **Les fonctions de base sont les mêmes partout** : fiche client géolocalisée, contrat saisonnier avec prix, route ordonnée, statut de passage, avis texto avant le passage, facturation TPS/TVQ, paiement en ligne, historique.
2. **L'avis de proximité par géolocalisation** existe déjà (Horizon CRM, Follosoft, Flokon). C'est une attente normale des clients maintenant, pas un gadget.
3. **Aucun ne gère bien le comptant ni les vieux comptes** : ils supposent carte ou prélèvement. Le cas de Louis (comptant, Interac, dettes passées) est justement là où une app maison a un avantage.
4. **Bâtir plutôt qu'acheter : décision prise (7 novembre 2026).** Le logiciel québécois le plus complet (UsoftCRM) revient à 1 400 à 2 000 $ par année plus les textos une fois qu'on ajoute le module cellulaire et le portail, et les autres n'affichent pas leurs prix. Louis n'a pas ce budget, et JF veut l'aider. L'app maison donne en plus la souplesse (comptant, Interac, recouvrement sur mesure) et aucun abonnement. L'hébergement ne coûte rien : la VM roule sur les serveurs de JF dans son centre de données. Les courriels passent par le compte SMTP2GO de JF. Seuls coûts récurrents : le numéro et les textos (quelques dollars par mois en saison) et le renouvellement du domaine `ledeneigeur.com`, déjà enregistré par JF. La maintenance est assumée par JF. L'offre de l'app à d'autres déneigeurs est une possibilité pour plus tard; l'architecture la prévoit sans la bâtir (section P).

## 5. Catalogue complet des fonctionnalités

Chaque fonctionnalité a un code pour qu'on puisse cocher ce qui part en version 1. La colonne « Proposition » est ma recommandation de départ, à discuter.

Légende : **V1** = version de base, **V2** = saison suivante ou dès que V1 roule, **Plus tard** = quand le besoin se présente.

### A. Clients et fiches

| Code | Fonctionnalité | Proposition |
|---|---|---|
| A1 | Fiche client : nom, téléphone cellulaire, courriel, adresse de service, adresse de facturation si différente, notes | V1 |
| A2 | Géolocalisation automatique de l'adresse (latitude, longitude) à la saisie, avec correction manuelle sur carte | V1 |
| A3 | Plusieurs contacts par client (conjoint, locataire, gestionnaire d'immeuble) | V2 |
| A4 | Plusieurs adresses de service pour un même payeur (ex. un propriétaire avec deux immeubles) | V2 |
| A5 | Particularités du terrain : où mettre la neige, obstacles, borne-fontaine, pente, consignes spéciales, photo de l'entrée | V1 |
| A6 | Préférences de communication : texto, courriel ou les deux; langue | V1 |
| A7 | Statut du client : actif, inactif, en recouvrement, liste noire | V1 |
| A8 | Recherche rapide (nom, adresse, téléphone) adaptée au cellulaire | V1 |
| A9 | Import initial par fichier CSV ou Excel à partir des papiers de Louis | V1 |
| A10 | Historique des propriétaires d'une adresse (changement de proprio en cours de saison) | Plus tard |
| A11 | Balises ou piquets : nombre installés, date d'installation, date de retrait | V2 |

### B. Contrats, prix et saison

| Code | Fonctionnalité | Proposition |
|---|---|---|
| B1 | Prix entendu avec le client pour la saison, en texte libre et en montant | V1 |
| B2 | Types de contrat : saisonnier forfaitaire, au passage, à l'heure, sur demande | V1 (saisonnier et au passage) |
| B3 | Modalités de paiement : montant unique, 2, 3 ou 4 versements avec dates | V1 |
| B4 | Services inclus ou en extra : entrée, bordage de rue laissé par la ville, pelletage manuel (balcon, escalier), abrasif, déneigement de toiture | V1 (liste simple) |
| B5 | Saison : dates de début et de fin, création de la saison suivante en copiant les clients et prix de l'année précédente avec ajustement en % | V2 |
| B6 | Contrat PDF généré et envoyé au client par courriel ou texto | V2 |
| B7 | Signature électronique du contrat par le client | Plus tard |
| B8 | Grille de prix par type d'entrée (simple, double, longueur) pour les nouvelles demandes | Plus tard |

### C. Facturation et comptes à recevoir

| Code | Fonctionnalité | Proposition |
|---|---|---|
| C1 | Création d'une facture en quelques tapes au cellulaire : client, service, montant, taxes | V1 |
| C2 | Taxes TPS et TVQ calculées automatiquement, avec numéros d'inscription sur la facture, ou facture sans taxes si Louis est petit fournisseur (à confirmer, section 10) | V1 |
| C3 | Numérotation séquentielle des factures, PDF généré automatiquement | V1 |
| C4 | Envoi de la facture par courriel et par texto (lien vers le PDF) | V1 |
| C5 | Factures automatiques pour les versements prévus au contrat (échéancier) | V1 |
| C6 | Saisie des soldes d'ouverture : montants dus des saisons passées par client, avec note | V1 |
| C7 | Écran « Comptes à recevoir » : qui doit quoi, depuis combien de temps, tri par montant et par ancienneté | V1 |
| C8 | Relance en un geste : courriel ou texto avec facture jointe, ton gradué (rappel, deuxième avis, dernier avis) | V1 |
| C9 | Relances automatiques planifiées (ex. 15, 30, 60 jours) avec arrêt dès que payé | V2 |
| C10 | État de compte PDF par client (toutes les factures et paiements) | V2 |
| C11 | Note de crédit, rabais, radiation d'une créance irrécouvrable | V2 |
| C12 | Export comptable (CSV pour comptable ou pour QuickBooks, Sage, Acomba) | V2 |
| C13 | Reçu automatique au client à chaque paiement reçu | V1 |

### D. Paiements

| Code | Fonctionnalité | Proposition |
|---|---|---|
| D1 | Mode de paiement préféré dans la fiche : Interac, comptant, carte de crédit, chèque | V1 |
| D2 | Comptant : bouton « Reçu comptant » sur la facture, qui enregistre date, montant, et envoie un reçu texto ou courriel au client. C'est la trace écrite qui manque aujourd'hui. | V1 |
| D3 | Comptant : liste « À collecter aujourd'hui » basée sur la tournée (clients comptant avec solde dû sur la route du jour) | V1 |
| D4 | Interac : instructions de virement sur la facture (adresse courriel ou numéro, question de sécurité ou dépôt automatique), enregistrement manuel du virement reçu | V1 |
| D5 | Interac : détection automatique des virements reçus en lisant les courriels de notification d'Interac dans une boîte dédiée, avec appariement au client par nom ou montant | V2 |
| D6 | Carte de crédit : lien de paiement sur la facture (Stripe ou Square), marquage automatique « payé » | V1 ou V2 selon le volume de clients carte |
| D7 | Paiement partiel, trop-perçu appliqué à la facture suivante | V2 |
| D8 | Prélèvement préautorisé (PPA) sur compte bancaire | Plus tard |

### E. Communications : textos, courriels, historique unifié

| Code | Fonctionnalité | Proposition |
|---|---|---|
| E1 | Numéro de texto d'affaires dédié (numéro local 450 ou 579) distinct du cellulaire personnel de Louis | V1 |
| E2 | Envoi de textos individuels depuis la fiche client | V1 |
| E3 | Envoi de courriels individuels depuis la fiche client | V1 |
| E4 | Réception des textos : la réponse du client est rattachée automatiquement à sa fiche par son numéro | V1 |
| E5 | Réception des courriels : réponse rattachée automatiquement à la fiche par l'adresse courriel ou par un identifiant dans le sujet | V1 |
| E6 | Historique unifié par client : textos, courriels, avis automatiques, appels notés à la main, dans un seul fil chronologique | V1 |
| E7 | Boîte de réception globale : tous les messages entrants non lus, avec accès rapide à la fiche | V1 |
| E8 | Notification sur le cellulaire de Louis quand un client répond | V1 |
| E9 | Gabarits de messages (début de tempête, passage terminé, facture, rappel, fin de saison) modifiables | V1 |
| E10 | Envoi groupé : à tous les clients, à un secteur, aux clients d'une route | V1 |
| E11 | Gestion du désabonnement : un client qui texte ARRÊT ou STOP n'est plus sollicité pour le commercial, mais reçoit encore les avis de service | V1 |
| E12 | Avis par appel vocal automatisé pour les clients sans cellulaire | Plus tard |
| E13 | Journal d'envoi : livré, échoué, coût par message | V2 |
| E14 | Pièces jointes (photo d'un dommage, du passage) dans les textos et courriels | V2 |

### F. Tournée et opérations

| Code | Fonctionnalité | Proposition |
|---|---|---|
| F1 | Liste des arrêts de la tournée dans l'ordre habituel de Louis, modifiable par glisser-déposer | V1 |
| F2 | Secteurs : regroupement des clients par secteur ou par route | V1 |
| F3 | Démarrer une opération (bordée) : date, heure, type (neige, verglas, bordage de la ville, finition) | V1 |
| F4 | Marquer un passage « fait » en une tape, avec heure automatique; « sauté » avec raison (auto dans l'entrée, client absent, non payé) | V1 |
| F5 | Historique des passages par client (date, heure, type) consultable et envoyable au client en cas de litige | V1 |
| F6 | Navigation : bouton qui ouvre Google Maps, Apple Plans ou Waze vers le prochain arrêt | V1 |
| F7 | Photo du passage (avant ou après) horodatée et géolocalisée | V2 |
| F8 | Notes de passage (dommage constaté, obstacle, demande du client) | V1 |
| F9 | Optimisation automatique de l'ordre des arrêts | Plus tard (Louis connaît sa route) |
| F10 | Mode hors ligne : la liste de la tournée reste accessible sans réseau cellulaire, les actions se synchronisent au retour du signal | V1 (important dans les Laurentides) |
| F11 | Passage facturable généré automatiquement pour les clients « au passage » | V1 |
| F12 | Plusieurs opérateurs ou véhicules avec routes assignées | Plus tard |
| F13 | Suivi des heures de travail et des heures machine | Plus tard |

### G. Géolocalisation et avis de proximité

| Code | Fonctionnalité | Proposition |
|---|---|---|
| G1 | Position du cellulaire de Louis captée par l'app pendant une opération en cours | V1 |
| G2 | Avis automatique aux clients situés dans un rayon configurable (ex. 500 m ou 1 km) ou aux N prochains arrêts : « Louis sera chez vous dans environ X minutes, merci de libérer l'entrée » | V1 |
| G3 | Un seul avis par client par opération (pas de doublons quand Louis repasse dans le coin) | V1 |
| G4 | Avis manuel de secours : bouton « Aviser le secteur » si la géolocalisation ne fonctionne pas | V1 |
| G5 | Avis de début d'opération à tous les clients (« les opérations débutent, ordre habituel ») et de fin de passage par client | V1 |
| G6 | Position de Louis visible par JF en temps réel sur une carte (supervision, sécurité) | V2 |
| G7 | Historique des trajets (trace GPS d'une opération) | Plus tard |
| G8 | Lien envoyé au client pour voir la position du tracteur en direct | Plus tard |

### H. Appels de service, plaintes et dommages

| Code | Fonctionnalité | Proposition |
|---|---|---|
| H1 | Création d'une demande de service à partir d'un texto ou courriel reçu (ex. « vous avez oublié mon bordage ») | V2 |
| H2 | Suivi de la demande : ouverte, planifiée, réglée | V2 |
| H3 | Dossier de dommage : photo, description, entente de réparation, coût | V2 |
| H4 | Demandes de nouveaux clients (formulaire web simple) | Plus tard |

### I. Météo et déclenchement

| Code | Fonctionnalité | Proposition |
|---|---|---|
| I1 | Prévisions Environnement Canada pour le secteur affichées dans l'app | V2 |
| I2 | Alerte à Louis quand une accumulation dépasse un seuil | Plus tard |
| I3 | Journal météo par opération (accumulation déclarée) pour justifier les passages | Plus tard |

### J. Rapports et tableau de bord

| Code | Fonctionnalité | Proposition |
|---|---|---|
| J1 | Tableau de bord : facturé, encaissé, à recevoir, nombre de clients actifs, opérations de la saison | V1 |
| J2 | Revenus par secteur ou par route | V2 |
| J3 | Rapport de fin de saison pour le comptable (ventes, taxes perçues, encaissements par mode) | V2 |
| J4 | Rapport des clients en souffrance avec ancienneté | V1 (c'est l'écran C7) |
| J5 | Coûts de communication (SMS envoyés, montant) | V2 |

### K. Administration, sécurité et conformité

| Code | Fonctionnalité | Proposition |
|---|---|---|
| K1 | Connexion sécurisée (mot de passe fort, option code à usage unique), session longue sur le cellulaire de Louis | V1 |
| K2 | Rôles : administrateur (JF), opérateur (Louis), lecture seule (comptable) | V1 |
| K3 | Sauvegarde automatique quotidienne de la base de données avec copie hors du serveur | V1 |
| K4 | Journal des actions (qui a modifié quoi) | V2 |
| K5 | Conformité Loi 25 : données personnelles minimales, politique de confidentialité, suppression sur demande, registre d'incidents | V1 (minimum) |
| K6 | Conformité LCAP (loi anti-pourriel) : consentement noté dans la fiche, mécanisme de désabonnement, identification de l'expéditeur dans chaque message commercial | V1 |
| K7 | Interface entièrement en français québécois | V1 |
| K8 | Mises à jour de l'app sans intervention de Louis (application web) | V1 |

### L. Portail client

| Code | Fonctionnalité | Proposition |
|---|---|---|
| L1 | Page de facture publique par lien sécurisé (voir et payer sans compte) | V1 (découle de C4 et D6) |
| L2 | Portail client complet : factures, historique des passages, contrat, demandes de service | Plus tard |

### M. Intégrations

| Code | Fonctionnalité | Proposition |
|---|---|---|
| M1 | Fournisseur SMS (Twilio ou Telnyx) | V1 |
| M2 | Envoi des courriels par SMTP2GO (sous-compte dédié à Louis sur le compte de JF, domaine d'envoi ledeneigeur.com) et réception par une boîte IMAP dédiée lue par l'app | V1 |
| M3 | Géocodage et cartes (OpenStreetMap et Nominatim, ou Google Maps) | V1 |
| M4 | Paiement par carte (Stripe ou Square) | V1 ou V2 |
| M5 | Export vers logiciel comptable | V2 |
| M6 | Calendrier (opérations planifiées dans le calendrier de Louis) | Plus tard |

### O. Assistant IA pour les réponses aux clients (demandé par JF, pour plus tard)

Objectif : pendant une tempête, Louis conduit. Les clients textent « vous passez quand? », « combien je vous dois? », « renvoyez-moi ma facture ». L'assistant répond aux questions de base à partir du dossier du client, et laisse à Louis tout ce qui demande un jugement. Un humain reste dans la boucle au départ; l'automatisation complète vient seulement quand les réponses proposées sont fiables.

| Code | Fonctionnalité | Proposition |
|---|---|---|
| O1 | Classification automatique des messages entrants : question sur le passage, paiement, demande de facture, plainte, dommage, demande de service, nouveau client, autre | V2 |
| O2 | Brouillon de réponse proposé à Louis dans le fil du client, qu'il approuve, modifie ou rejette en une tape (aucun envoi sans son accord) | V2 |
| O3 | Réponse automatique sans intervention pour les questions de base, à partir des données du dossier : prochain passage prévu ou position dans la tournée, solde dû, renvoi de la facture ou du reçu, confirmation de réception d'un paiement, heures et secteur | Plus tard (après validation de O2 sur une saison ou une partie de saison) |
| O4 | Escalade obligatoire à Louis : plainte, dommage, prix, négociation, résiliation, ton agressif, toute question hors du dossier. L'assistant répond seulement qu'il transmet à Louis. | Avec O3 |
| O5 | Transparence : chaque réponse automatique est identifiée comme provenant de l'assistant automatisé, et un mot-clé (« LOUIS ») permet au client de demander une réponse humaine | Avec O3 |
| O6 | Journal des réponses IA : ce qui a été proposé, envoyé, modifié ou rejeté, pour ajuster les consignes | V2 |
| O7 | Résumé d'une longue conversation client en quelques lignes dans la fiche | Plus tard |
| O8 | Extraction automatique d'informations dans les messages (nouveau numéro, nouvelle adresse courriel, déménagement) proposée comme mise à jour de la fiche | Plus tard |
| O9 | Création automatique d'une demande de service (H1) à partir d'un message classé « plainte » ou « demande de service » | Plus tard |

Technologie : API Claude (Anthropic) appelée par le worker en arrière-plan, avec le dossier du client (statut, solde, prochains passages, gabarits approuvés) fourni en contexte et des consignes strictes en français québécois. Coût estimé : quelques dollars par mois au volume de Louis. Garde-fous : jamais d'engagement sur une heure précise, jamais de prix ni de rabais, jamais de réponse sur un dossier en recouvrement sans Louis, limite du nombre de réponses automatiques par client par jour.

### P. Hors de la portée du projet (pour être clair)
- Opérations d'été (tonte, aménagement).
- Gestion de flotte et d'entretien mécanique.
- Paie et RH.
- Contrats municipaux ou commerciaux à appels d'offres.
- Offre de l'app à d'autres déneigeurs (multi-entreprise). Pas un objectif de V1, mais on garde la porte ouverte à peu de frais : une table `Entreprise` dès le départ, à laquelle tout le reste est rattaché, et aucune donnée de Louis codée en dur (nom, taxes, numéro de texto, textes des gabarits, tout en configuration). Ajouter un deuxième déneigeur deviendra une question d'écrans d'administration et de facturation de l'usage, pas une réécriture. Le nom de domaine générique ledeneigeur.com va dans ce sens.

## 6. Architecture technique recommandée

### 6.1 Système d'exploitation de la VM : Ubuntu Server 26.04.1 LTS

**Choix : Ubuntu Server 26.04.1 LTS (Resolute Raccoon), 64 bits.**

Pourquoi :
- Version LTS sortie en avril 2026, première version de maintenance (26.04.1) publiée le 27 août 2026, donc stabilisée.
- Soutenue jusqu'en avril 2031 sans frais, 10 ans de plus avec Ubuntu Pro (gratuit jusqu'à 5 machines).
- Docker 29, PostgreSQL et Python 3.14 disponibles directement dans les dépôts officiels.
- La plus documentée, et celle que Claude Code connaît le mieux pour l'automatisation.

**Spécifications de la VM (fixées par JF le 7 novembre 2026) :**
- 4 vCPU, 8 Go de RAM, 250 Go de disque. C'est plus que ce que Louis seul demande; la marge sert à l'environnement de test, aux sauvegardes locales et à d'autres déneigeurs plus tard (section P) sans changer de serveur.
- Installation minimale, sans interface graphique, avec OpenSSH activé.
- Adresse IP fixe interne `172.16.4.100`, nom d'hôte `ld1`, derrière le pare-feu de JF.
- Un compte `deploy` avec sudo et clé SSH (pas de mot de passe SSH).
- **Domaine : `ledeneigeur.com`** (principal) et `ledeneigeur.ca` (redirigé vers le .com), enregistrés par JF le 7 novembre 2026. Découpage :
  - `ld1.ledeneigeur.com` : le serveur (SSH, administration). Enregistrement A vers l'IP publique.
  - Un sous-domaine par déneigeur pour l'app, `louis.ledeneigeur.com` pour Louis (décidé le 7 novembre 2026). Même IP; Caddy sert chaque sous-domaine et obtient son certificat HTTPS.
  - `test.ledeneigeur.com` : l'environnement de test (décidé le 7 novembre 2026).
  - Le même domaine sert d'envoi SMTP2GO et de boîte IMAP de réception, à moins que Louis ait déjà un domaine à lui.
  - Ce découpage colle à l'offre éventuelle à d'autres déneigeurs (section P).
- Ports : redirection au routeur limitée à quelques IP sources choisies par JF, 443 seulement proposé (voir « Exposition à Internet » en 6.1.1). Le SSH n'est pas exposé à tout Internet : accès par le réseau interne de JF (règle ufw) ou par VPN.
- Instantanés (snapshots) de la VM avant chaque mise à jour majeure.

### 6.1.1 État du serveur `ld1` (installé le 7 novembre 2026)

| Élément | Valeur |
|---|---|
| Nom d'hôte | `ld1` (`ld1.ledeneigeur.com`) |
| Hyperviseur | Hyper-V Gen 2 sur l'hôte SUPER-01 (VM « LMAPP-JF »), services d'intégration Hyper-V installés |
| OS | Ubuntu Server 26.04.1 LTS, noyau 7.0, installation minimale, à jour |
| Réseau | IP fixe `172.16.4.100/24`, passerelle `172.16.4.1`, DNS `8.8.8.8` et `1.1.1.1`, IPv6 désactivé. Config : `/etc/netplan/01-ld1.yaml`, original dans `/root/netplan-backup/` |
| Fuseau horaire | `America/Toronto` |
| Compte | `deploy`, sudo avec mot de passe, groupe `docker` |
| SSH | Clé ED25519 de JF seulement, mot de passe désactivé, `root` interdit, `AllowUsers deploy` (`/etc/ssh/sshd_config.d/00-ld1.conf`) |
| Disque | Disque virtuel de 250 Go, mais le volume logique `ubuntu-vg/ubuntu-lv` ne fait que 98 Go (allocation partielle de l'installateur). À agrandir |
| Pare-feu | `ufw` : SSH seulement depuis `172.16.4.0/24`, 80 et 443 limités au réseau interne (selon CLAUDE.md; à confirmer avec `sudo ufw status verbose`), tout le reste refusé en entrée. ufw ne protège pas les ports publiés par Docker |
| DNS | Zone `ledeneigeur.com` chez Cloudflare. `louis` et `test` : A vers `216.46.12.226`, DNS seulement. Racine et `www` en proxy vers `69.16.231.58`. Plus de générique `*` en A |
| Certificats | Let's Encrypt pour `louis.ledeneigeur.com` et `test.ledeneigeur.com`, obtenus le 7 novembre 2026 par validation DNS Cloudflare (jeton dans `edge/.env`), renouvelés automatiquement par Caddy |
| IP publique | `216.46.12.226` (IP de sortie de ld1, mesurée le 7 novembre 2026; l'IP d'entrée peut différer si le routeur en a plusieurs) |
| fail2ban | Actif sur sshd (backend systemd), bannissement 1 h après 5 échecs en 10 minutes, `172.16.4.1` exclu |
| Docker | Paquets Ubuntu `docker.io`, `docker-compose-v2`, `docker-buildx`; journaux plafonnés à 10 Mo x 3 par conteneur, `deploy` dans le groupe `docker`, testé avec hello-world |
| Git | 2.53, installé par apt le 7 novembre 2026. Dépôt `/srv/lmapp` sur la branche `main`, sans dépôt distant pour l'instant |
| Dossier du projet | `/srv/lmapp`, propriétaire `deploy` : code Django dans `src/`, `Dockerfile`, `compose.yaml`, `Caddyfile`, `.env` (600, hors Git) |
| Pile Docker | En marche depuis le 7 novembre 2026. Projet `edge` : Caddy 2.11, frontal commun à la prod et au test, seul à publier un port (443 TCP). Projet `lmapp` (prod) : `db` (PostgreSQL 17.11, PostGIS 3.7), `app` (Django 5.2 LTS, Python 3.13, Gunicorn), `worker` (Procrastinate), aucun port publié. Réseau partagé `edge` entre Caddy et les apps; base sur un réseau sans accès Internet. Projet `lmapp-test` (test, `test.ledeneigeur.com`) : sa propre base `lmapp_test`, ses volumes, son image `lmapp:test`, bandeau « ENVIRONNEMENT DE TEST » à l'écran. Volumes externes `lmapp_pgdata`, `lmapp_media`, `lmapp_caddy_data`. Certificat interne de Caddy en attendant la validation DNS. Validée sur le réseau interne (`/sante/`, admin, fichiers statiques) |
| Claude Code | Version 2.1.319, installateur natif (`~/.local/bin/claude`, mises à jour automatiques), PATH ajouté dans `~/.bashrc` de `deploy`, connecté au compte claude.ai de JF (`claude auth login`), `claude doctor` sans problème. Installé le 7 novembre 2026. Consignes dans `/srv/lmapp/CLAUDE.md`. |

Points à régler :
- **MAC dynamique dans Hyper-V** : JF garde la MAC dynamique (décision du 7 novembre 2026). La config netplan ne doit donc pas dépendre de la MAC : elle doit reconnaître la carte par son pilote Hyper-V (`hv_netvsc`) plutôt que par l'adresse `00:15:5d:04:0a:02`, sinon la VM perd son réseau si la MAC change (déplacement ou réimportation de la VM).
- **NAT source** : les connexions SSH arrivent avec la source `172.16.4.1` (la passerelle). Si le trafic web public arrive aussi ainsi après le NAT des ports 80 et 443, l'app ne verra pas l'IP réelle des visiteurs (journaux, limitation des abus). À vérifier et, si possible, corriger au routeur (redirection de port sans NAT source).
- **Docker contourne ufw** : un port publié par un conteneur est ouvert même si ufw le bloque. Seul Caddy publie un port (443); la base, l'app et le worker restent sur les réseaux Docker internes. Une règle dans la chaîne `DOCKER-USER` pourra filtrer les IP sur ld1 même, en plus du routeur.
- ~~**DNS public** : enregistrements A `louis` et `test` vers `216.46.12.226` en DNS seulement, suppression du générique `*`.~~ **Fait.** Reste, pour l'accès interne ou VPN tant que le routeur ne redirige rien : faire pointer ces noms vers `172.16.4.100` dans le DNS interne (ou le fichier `hosts` des postes).
- ~~**Certificat**~~ **Fait le 7 novembre 2026.** Validation DNS par Cloudflare (Let's Encrypt ne peut pas valider par HTTP si l'accès est filtré par IP). Il faut un jeton API Cloudflare limité à « Zone : DNS : Modifier » sur `ledeneigeur.com`, déposé par JF dans `/srv/lmapp/edge/.env` (Caddy seul le reçoit), et une image Caddy avec le module `caddy-dns/cloudflare`.
- **Disque** : agrandir le volume logique à la taille du disque (`sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv`, après vérification avec `sudo vgs`).
- **Port local `127.0.0.1:36789`** : un processus d'un autre utilisateur que `deploy` écoute sur ce port, en local seulement. À identifier avec `sudo ss -tlnp 'sport = :36789'`.
- **Services à redémarrer** : apt a signalé des services à redémarrer (dbus, logind, networkd-dispatcher, unattended-upgrades) après l'installation de git. Un redémarrage de la VM au prochain moment tranquille règle ça.
- **Exposition à Internet** : décision de JF du 7 novembre 2026 : ouvrir au routeur, de `216.46.12.226` vers `172.16.4.100`, **seulement pour quelques IP sources** choisies par JF. Pas encore en place. Le 443 seulement est proposé, puisque le certificat passe par la validation DNS. Le filtrage principal se fait au routeur, avec une liste `IP_PERMISES` dans Caddy en deuxième couche, à condition que l'IP réelle des visiteurs arrive jusqu'à ld1 (voir « NAT source »). L'ouverture plus large (webhooks Twilio et SMTP2GO, liens de factures des clients) sera décidée avant la mise en service : leurs IP changent, donc il faudra des routes de webhook vérifiées par signature, ou un tunnel Cloudflare avec contrôle d'accès.

### 6.2 Base de données : PostgreSQL 17 avec l'extension PostGIS

**Choix : PostgreSQL 17 + PostGIS**, sur la même VM pour commencer, dans un conteneur Docker avec volume persistant.

Pourquoi :
- Libre, robuste, sauvegardes simples (`pg_dump`), restauration testable.
- PostGIS gère directement les calculs de distance (« quels clients sont à moins de 800 m de Louis ») et les secteurs géographiques.
- Peut aussi servir de file d'attente pour les tâches en arrière-plan (envoi de SMS, relances), ce qui évite d'ajouter Redis.

Alternatives écartées : MariaDB (pas d'équivalent sérieux à PostGIS), SQLite (correct pour un prototype, mais pas pour les webhooks concurrents et les tâches planifiées).

### 6.3 Application

Recommandation : **une application web progressive (PWA) mobile d'abord**, plutôt qu'une app native à publier sur l'App Store et Google Play.

- Louis l'installe sur son écran d'accueil, elle se comporte comme une app, elle fonctionne sur iPhone et Android avec le même code, et les mises à jour sont instantanées.
- Pas de frais ni de délais d'approbation des magasins d'applications.
- Limite connue : sur iPhone, la géolocalisation en arrière-plan (app fermée ou écran verrouillé) n'est pas offerte à une app web, et les notifications et le mode hors ligne exigent que l'app soit installée sur l'écran d'accueil. Voir le point 6.5.

Pile proposée :
- **Backend : Python 3.12+ avec Django** (ORM, migrations, authentification, administration prête à l'emploi pour JF, internationalisation en français). Django REST Framework seulement si on veut une API ouverte plus tard.
- **Interface : gabarits Django + HTMX + Alpine.js + Tailwind CSS**. Rapide à bâtir, rapide à charger sur un réseau cellulaire faible, peu de JavaScript à maintenir. Service worker pour le mode hors ligne (liste de tournée en cache, file d'actions à synchroniser).
- **Tâches planifiées et en arrière-plan : Procrastinate** (file de tâches sur PostgreSQL) pour les envois de SMS et de courriels, les relances, la détection de proximité.
- **Serveur web : Caddy** en frontal (HTTPS automatique avec Let's Encrypt, reverse proxy vers Gunicorn), seul conteneur à publier des ports.
- **Conteneurs : Docker Compose** (services : `app`, `worker`, `db`, `caddy`). Un seul fichier pour tout déployer et redéployer, dans `/srv/lmapp`.
- **PDF des factures : WeasyPrint** à partir d'un gabarit HTML.
- **Cartes et géocodage : Leaflet + OpenStreetMap** (gratuit), géocodage avec Nominatim ou l'API Google Geocoding si la précision des adresses rurales des Laurentides l'exige.

Alternative si JF préfère l'écosystème JavaScript : Node.js avec Next.js ou SvelteKit, Prisma, même PostgreSQL. Le choix est ouvert, mais Django donne un back-office d'administration gratuit dès le premier jour, ce qui compte pour l'import des données de Louis et les corrections à la main.

### 6.4 Services externes

| Besoin | Choix recommandé | Remarques |
|---|---|---|
| Textos (envoi et réception) | **Twilio** avec un numéro local québécois (450 ou 579) | Environ 0,01 $ US par SMS plus la location du numéro (environ 1,15 $ US par mois). Réception par webhook vers `louis.ledeneigeur.com`. Telnyx est l'alternative moins chère. Important : on ne peut pas envoyer depuis le numéro personnel de Louis; les clients textent le nouveau numéro d'affaires, qu'on leur communique au départ. |
| Courriels (envoi) | **SMTP2GO**, compte de JF, avec un **sous-compte dédié à Louis** et le domaine d'envoi **ledeneigeur.com** vérifié (SPF, DKIM, DMARC) | Décidé le 7 novembre 2026. Envoi par API ou SMTP depuis l'app. Les webhooks SMTP2GO (remis, rebond, pourriel, ouverture) alimentent le journal d'envoi E13 et marquent les factures « livrées ». Le sous-compte isole les statistiques et la réputation de Louis de celles de Peripheriq. |
| Courriels (réception) | Une **boîte IMAP dédiée**, proposée : `info@ledeneigeur.com`, fournie par JF, interrogée par le worker de l'app (IMAP IDLE si le serveur le permet, sinon toutes les 60 secondes) | Décidé le 7 novembre 2026. SMTP2GO n'offre pas la réception. Les courriels sortants portent cette boîte comme adresse de réponse et un identifiant dans le sujet; les réponses sont rattachées à la fiche (E5). Les messages traités sont déplacés dans un dossier « Traités » pour ne jamais être lus deux fois. Les notifications Interac peuvent aussi y arriver (D5). Le MX de ledeneigeur.com dépend de l'endroit où JF crée la boîte. |
| Paiement par carte | **Stripe** (liens de paiement, webhook de confirmation) | 2,9 % + 0,30 $ par transaction. À activer seulement si des clients veulent payer par carte. |
| Interac | Pas d'API pour une petite entreprise | Instructions sur la facture, dépôt automatique du côté de Louis, et appariement manuel ou semi-automatique via les courriels de notification. |
| Cartes | OpenStreetMap et Leaflet | Gratuit; Google Maps en option. |

### 6.5 Le cas particulier de la géolocalisation (Louis a un iPhone 17 Pro Max)

Cellulaire confirmé : **iPhone 17 Pro Max**. Ça fixe les règles du jeu, parce que Safari sur iPhone est le plus restrictif des deux plateformes pour une app web.

Ce que l'iPhone permet à une app web installée sur l'écran d'accueil :
- **App ouverte à l'écran** (téléphone sur un support dans le tracteur, écran allumé) : la position est captée en continu avec le GPS de l'iPhone, qui est très précis. C'est le mode V1 : Louis démarre l'opération, laisse l'app à l'écran, et les avis de proximité partent tout seuls. L'app empêchera l'écran de s'éteindre pendant une opération (Wake Lock) et affichera le prochain arrêt en gros, pour qu'elle serve aussi de tableau de bord.
- **App en arrière-plan ou écran verrouillé** : iOS coupe la géolocalisation d'une app web. Aucun contournement fiable. Si Louis veut le téléphone dans sa poche avec les avis qui partent quand même, il faut une coquille native (Capacitor) avec la permission « Position : toujours », distribuée par TestFlight ou l'App Store (compte développeur Apple, 99 $ US par année). Prévu en V2 si le mode V1 ne convient pas à Louis sur le terrain.
- **Notifications** : iOS accepte les notifications web (Web Push) seulement si l'app est installée sur l'écran d'accueil. L'installation sera donc la première étape de la formation de Louis, et E8 (avertir Louis quand un client répond) en dépend.
- **Hors ligne** : une app installée sur l'écran d'accueil conserve ses données en cache sans la limite de 7 jours que Safari impose aux sites ordinaires. F10 fonctionne, à condition encore une fois que l'app soit installée et non juste ouverte dans Safari.
- **Navigation** : les liens vers Apple Plans, Google Maps et Waze fonctionnent tous à partir de l'app (F6).
- **Plan B toujours disponible** : le bouton « Aviser le secteur » (G4) et l'avis aux N prochains arrêts à partir du dernier passage marqué « fait », qui ne dépendent pas du GPS.

Décision : **V1 en app web installée sur l'écran d'accueil, mode « téléphone sur support, écran allumé » pendant les opérations.** Réévaluation après la première tempête réelle; si Louis veut le téléphone dans sa poche, on passe à Capacitor en V2.

### 6.6 Modèle de données (ébauche)

- `Entreprise` (nom, coordonnées, numéros de taxes, numéro de texto, sous-compte SMTP2GO, boîte de réception, configuration) : une seule au départ, Louis Méthot Déneigement; tout le reste s'y rattache (voir section P)
- `Client` (identité, contacts, préférences, statut, consentement LCAP)
- `Adresse` (adresse civique, latitude, longitude, secteur, particularités, photo)
- `Saison` (dates)
- `Contrat` (client, adresse, saison, type, prix, services, échéancier de versements)
- `Facture` (numéro, client, contrat ou passage, lignes, taxes, total, statut, PDF)
- `Paiement` (facture, mode, montant, date, référence, reçu envoyé)
- `SoldeOuverture` (client, montant, saison d'origine, note)
- `Operation` (date, type, statut, opérateur)
- `Passage` (opération, adresse, statut fait ou sauté, heure, note, photo)
- `Message` (client, direction entrant ou sortant, canal texto ou courriel, contenu, statut, coût, lien vers passage ou facture)
- `Gabarit` (type, texte avec variables)
- `PositionGPS` (opération, horodatage, latitude, longitude)
- `AvisProximite` (opération, client, heure d'envoi) pour éviter les doublons
- `Utilisateur` (rôle)
- `ReponseIA` (message entrant, classification, brouillon proposé, décision de Louis, réponse envoyée) pour la section O

### 6.7 Exploitation

- Sauvegarde `pg_dump` chaque nuit, chiffrée, copiée hors de la VM (stockage Peripheriq ou un compartiment S3 compatible). Test de restauration mensuel.
- Mises à jour de sécurité automatiques (`unattended-upgrades`), pare-feu `ufw`, `fail2ban` sur SSH : en place sur `ld1`.
- Surveillance : vérification de disponibilité HTTPS et alerte si la file de tâches bloque (un SMS non parti pendant une tempête, c'est le pire scénario).
- Environnement de test séparé (projet Compose `lmapp-test` sur la même VM avec une autre base, sur `test.ledeneigeur.com`) pour ne jamais tester sur les vrais clients. Caddy est dans un projet `edge` à part (décision du 7 novembre 2026) : on peut arrêter, reconstruire ou casser le test sans toucher à la prod, et inversement.

## 7. Contraintes et conformité

- **Taxes** : si Louis est inscrit à la TPS et à la TVQ, les numéros doivent figurer sur les factures et les taux (5 % et 9,975 %) s'appliquent. S'il est petit fournisseur (moins de 30 000 $ de ventes taxables sur quatre trimestres), pas de taxes à percevoir. À confirmer avec lui ou son comptable avant de coder la facturation.
- **Loi 25 (protection des renseignements personnels)** : on garde le minimum (nom, coordonnées, adresse, historique de service et de paiement), on documente où c'est hébergé (chez Peripheriq, au Québec), et on prévoit la suppression sur demande.
- **LCAP (loi anti-pourriel)** : les avis de passage et les factures sont des messages de service, permis. Les messages à caractère commercial (renouvellement, offre) exigent un consentement et un lien ou mot de désabonnement. On note le consentement dans la fiche à l'import.
- **Réseau cellulaire** : couverture inégale dans les Laurentides. Mode hors ligne pour la tournée (F10) obligatoire.
- **Ergonomie hivernale** : gros boutons, peu de texte à taper, actions en une tape, mode sombre pour la nuit, contraste élevé. Louis doit pouvoir tout faire à une main.
- **Langue** : interface et messages en français québécois. Gabarits en anglais seulement si des clients le demandent.

## 8. Plan de réalisation

Le calendrier est serré : la saison est commencée. Priorité à ce qui rapporte de l'argent (facturation, recouvrement, comptant), puis la tournée et les avis.

### Phase 0 : Préparation (semaine 1)
- ~~JF : installation de la VM Ubuntu 26.04.1 LTS, IP fixe, SSH par clé, pare-feu.~~ **Fait le 7 novembre 2026** (section 6.1.1).
- ~~Claude Code installé sur la VM.~~ **Fait le 7 novembre 2026** (2.1.319, connecté au compte de JF). `CLAUDE.md` et `PRD.md` déposés dans `/srv/lmapp`.
- JF : DNS (`louis.ledeneigeur.com` et `test.ledeneigeur.com`, voir 6.1.1), netplan par pilote plutôt que par MAC, agrandissement du disque, jeton API Cloudflare, redirection au routeur filtrée par IP source.
- JF et Louis : réponses aux questions ouvertes (section 10).
- Louis : liste de ses clients (même en photo de ses papiers) pour l'import.
- Création des comptes : Twilio (numéro 450), sous-compte SMTP2GO et boîte de réception, Stripe si retenu.
- Claude Code : ~~structure du projet, dépôt Git, Docker Compose, base de données~~ **fait le 7 novembre 2026**; déploiement vide en HTTPS validé sur le réseau interne avec le certificat interne de Caddy. Environnement de test en marche sur `test.ledeneigeur.com`. Vrais certificats Let's Encrypt en place. Reste l'ouverture filtrée par IP.

### Phase 1 : Version de base, volet argent (semaines 2 à 4)
Fonctionnalités : A1, A2, A5, A6, A7, A8, A9, B1, B2, B3, B4, C1 à C8, C13, D1 à D4, D6 (si retenu), E1 à E11, J1, K1 à K3, K5 à K8, L1, M1 à M3.
Livrable : Louis a ses clients dans l'app, facture au cellulaire, enregistre les paiements comptant et Interac, envoie des factures et des relances aux vieux comptes, et les réponses des clients arrivent dans les fiches.
Jalon : première vraie relance envoyée aux comptes en souffrance.

### Phase 2 : Tournée et avis de proximité (semaines 4 à 6)
Fonctionnalités : F1 à F6, F8, F10, F11, G1 à G5.
Livrable : Louis démarre une opération, suit sa liste, marque les passages, et les clients reçoivent un avis automatique avant son arrivée.
Jalon : une tempête complète gérée dans l'app.

### Phase 3 : Consolidation et premier assistant IA (janvier et février)
Fonctionnalités : A3, A4, A11, B5, B6, C9 à C12, D5, D7, E13, E14, F7, G6, H1 à H3, I1, J2, J3, J5, K4, O1, O2, O6.
Livrable : automatisation des relances, rapports pour le comptable, demandes de service, et l'assistant qui classe les messages entrants et propose des brouillons que Louis approuve en une tape. Le reste de la saison sert à mesurer la qualité des brouillons.

### Phase 4 : Préparation de la saison suivante (printemps et été 2027)
- Renouvellement des contrats en lot avec ajustement de prix (B5, B6).
- Bilan de la saison avec Louis, ajustement du catalogue.
- Réponses automatiques de l'assistant pour les questions de base (O3 à O5), si les brouillons de la phase 3 ont été fiables.
- Décision sur l'app native (géolocalisation en arrière-plan) et sur le portail client.
- Décision sur l'offre à d'autres déneigeurs (section P).

### Méthode de travail
- Développement dans Claude Code, installé directement sur `ld1` sous le compte `deploy`, dans `/srv/lmapp`, avec un dépôt Git. Consignes permanentes dans `/srv/lmapp/CLAUDE.md`.
- Pas de sudo sans mot de passe : JF tape le mot de passe pour les rares tâches système. Instantané Hyper-V avant chaque grosse étape.
- Chaque fonctionnalité livrée est testée sur l'environnement de test, puis montrée à Louis sur son cellulaire avant la mise en production.
- Un court point hebdomadaire JF et Louis pendant les phases 1 et 2.

## 9. Risques

| Risque | Impact | Mitigation |
|---|---|---|
| Louis n'adopte pas l'app (habitude du papier) | Projet inutile | Interface minimaliste, formation sur place, commencer par ce qui lui fait gagner de l'argent (recouvrement) |
| Textos bloqués ou filtrés par les opérateurs cellulaires | Avis non reçus en tempête | Numéro local dédié, volume raisonnable, texte identifiant l'expéditeur, surveillance des échecs, plan B par courriel |
| Géolocalisation peu fiable (iPhone, écran éteint) | Avis de proximité manqués | Mode app ouverte sur support, bouton manuel G4, avis par prochains arrêts |
| Factures dans les pourriels | Recouvrement raté | SPF, DKIM, DMARC, fournisseur transactionnel, texto en doublon |
| Perte de données | Catastrophe pour Louis | Sauvegardes nocturnes hors VM, test de restauration, instantanés Hyper-V |
| Réseau cellulaire absent sur la route | Tournée bloquée | Mode hors ligne F10 |
| Mauvaise qualité des données papier à l'import | Avis envoyés aux mauvais numéros | Validation des numéros et adresses à l'import, premier message de bienvenue qui demande confirmation |
| Port de conteneur exposé par erreur (Docker contourne ufw) | Base de données accessible de l'extérieur | Seul Caddy publie des ports, règle inscrite dans CLAUDE.md, vérification avec un balayage externe après chaque déploiement |
| Portée qui grossit (été, flotte, multi-entreprises) | Retards | Section P respectée, nouvelles demandes notées pour la phase 4 |

## 10. Questions ouvertes (à régler avant la phase 1)

1. ~~Louis a un iPhone ou un Android?~~ **Réglé le 7 novembre 2026 : iPhone 17 Pro Max.** Voir 6.5.
2. **Louis est-il inscrit à la TPS et à la TVQ?** Décide du calcul des taxes sur les factures.
3. **Combien de clients actifs, et combien d'anciens comptes en souffrance?** Pour dimensionner l'import et estimer les coûts de SMS.
4. **Modèle de prix dominant** : contrat saisonnier payable en un ou plusieurs versements, ou facturation au passage? Les deux? Combien de versements, à quelles dates?
5. **Services offerts** : entrée seulement, ou aussi bordage, pelletage manuel, abrasif, toitures?
6. **Numéro de texto** : Louis accepte-t-il que les clients textent un nouveau numéro d'affaires plutôt que son cellulaire personnel? (C'est nécessaire pour la réception automatique.)
7. **Courriel d'affaires et Interac** : réception par une boîte IMAP fournie par JF sur ledeneigeur.com (réglé le 7 novembre 2026, adresse proposée `info@ledeneigeur.com`). Reste à confirmer l'adresse exacte et l'endroit où la boîte est hébergée (MX), et à savoir si Louis a déjà une adresse d'affaires que les clients connaissent. A-t-il le dépôt automatique Interac, et sur quelle adresse? Si c'est une adresse différente, on peut rediriger les notifications Interac vers la boîte IMAP pour D5.
8. **Carte de crédit** : y a-t-il réellement des clients qui veulent payer par carte? Sinon, on reporte Stripe.
9. **Secteurs desservis** : quelles municipalités? Un seul tracteur ou plusieurs véhicules? Louis travaille-t-il seul?
10. **Comptabilité** : qui fait sa comptabilité, et dans quel logiciel? Pour savoir quel export préparer.
11. ~~Nom de domaine~~ **Réglé le 7 novembre 2026 : `ledeneigeur.com` (principal) et `ledeneigeur.ca`, app de Louis sur `louis.ledeneigeur.com`.** Voir 6.1. Reste : l'adresse courriel exacte (question 7).
12. **Clients commerciaux** (stationnements, immeubles à logements)? Ils ont souvent des exigences de facturation différentes.
13. ~~Confirmation du choix bâtir plutôt qu'acheter~~ **Réglé le 7 novembre 2026 : on bâtit.** Voir section 4, point 4.

## 11. Prochaines étapes

**JF**
1. ~~Installer la VM Ubuntu Server 26.04.1 LTS, créer `deploy` avec clé SSH.~~ Fait.
2. Faire reconnaître la carte réseau par son pilote dans netplan (la MAC reste dynamique).
3. DNS chez Cloudflare : enregistrements A `louis.ledeneigeur.com` et `test.ledeneigeur.com` vers `216.46.12.226` en DNS seulement, suppression du générique `*`, noms internes vers `172.16.4.100`. Créer un jeton API Cloudflare (« Zone : DNS : Modifier » sur `ledeneigeur.com`) et le déposer dans `/srv/lmapp/edge/.env` (lu par Caddy seulement). Redirection du 443 au routeur, limitée aux IP choisies, idéalement sans NAT source. Instantané Hyper-V avant.
   - Agrandir le volume logique à 250 Go et identifier le processus du port local 36789 (section 6.1.1).
   - Créer le compte administrateur Django (`docker compose exec app python manage.py createsuperuser`, depuis sa propre session SSH).
4. Créer le sous-compte SMTP2GO de Louis, y ajouter ledeneigeur.com et publier SPF, DKIM et DMARC; créer la boîte IMAP de réception. Déposer la clé API SMTP2GO et les accès IMAP (serveur, port 993 TLS, identifiant, mot de passe) directement dans `/srv/lmapp/.env` sur la VM, jamais dans le clavardage.
5. Poser les questions de la section 10 à Louis.
6. Trancher les fonctionnalités V1 dans le catalogue (section 5).
7. ~~Prendre un instantané Hyper-V de `ld1`, puis lancer Claude Code dans `/srv/lmapp`.~~ Fait.

**Louis**
1. Rassembler sa liste de clients, prix et montants dus (photos des papiers suffisent).
2. Dire s'il est inscrit aux taxes.
3. Se procurer un support de téléphone pour le tracteur ou le camion et un chargeur, puisque l'app restera à l'écran pendant les opérations.

**Claude Code (sur ld1)**
1. ~~Vérifier Docker, initialiser le dépôt Git.~~ Fait.
2. ~~Structure du projet, Docker Compose~~, déploiement vide en HTTPS : validé en interne. Environnement de test en marche, vrais certificats en place. Reste l'ouverture filtrée par IP.
3. Modèle de données et import CSV.
4. Phase 1 dans l'ordre de la section 8.

---

### Sources consultées pour le tour d'horizon
- SnowTrack : https://www.snowtrack.net/
- Flokon : https://flokon.ca/
- Usoft Solutions (UsoftCRM) : https://usoftsolutions.ca/
- Follosoft via Naxella : https://naxella.com/follosoft/ et https://www.chasse-neige.ca/expertise
- Horizon CRM : https://www.horizoncrm.ca/deneigement-entretien
- Déneigeur Pro : https://deneigeurpro.ca/
- ManuGo : https://manugo.io/metiers/deneigement
- ProgressionLIVE : https://www.progressionlive.com/
- Jobber (module déneigement) : https://www.getjobber.com/
- Ubuntu 26.04 LTS : https://documentation.ubuntu.com/release-notes/26.04/ et https://ubuntu.com/download/server

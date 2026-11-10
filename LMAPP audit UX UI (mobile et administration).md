# LMAPP : audit UX/UI (mobile et administration)

Nov 9, 2026 · @JF Leroux

## Contexte et limites

Audit fait le 9 novembre 2026 en lecture seule, sur test.ledeneigeur.com (390 x 844, 768 x 1024) et admin.ledeneigeur.com/admin (1440 x 900, 1024 x 768). Aucun formulaire qui enregistre ou envoie n'a été soumis, sauf la connexion.

- **Usagers retenus** : l'app mobile sert Louis seul, sur la route (iPhone 17 Pro Max sur un support, gants, nuit, réseau faible). L'administration sert Jean-François et, le soir, Louis au bureau.
- **Attention, l'administration pointe sur la production.** Elle contient 0 client, mais l'entreprise « Louis Méthot Déneigement » avec ses vraies coordonnées (téléphone, courriel, adresse, nom légal). Les données fictives sont seulement dans test. Je n'ai rien modifié et aucune capture de la fiche entreprise n'est incluse.
- **Non vérifié** : l'écran d'une opération en cours (le seul moyen de le voir est de démarrer une opération, ce qui envoie des textos), le comportement hors ligne réel et la page de facture vue par le client.
- Mesures prises dans le navigateur : ratios de contraste WCAG calculés sur les couleurs réelles, tailles des zones tactiles en px CSS, temps de chargement (navigation API).

## Résumé

L'app mobile a de bonnes fondations (gros boutons, contrastes élevés, chargement en 71 ms), mais les gestes clés de Louis sont enfouis loin sous la ligne de flottaison. L'administration est l'admin Django brut : correcte pour Jean-François, inutilisable pour Louis.

**Forces**

1. Ergonomie de base solide : boutons de 60 à 80 px de haut, texte de 17,5 à 22,5 px, la plupart des contrastes entre 9:1 et 19:1, claviers mobiles adaptés (tel, email, decimal).
2. Rapidité et robustesse : page de 8 Ko, chargée en 71 ms, service worker actif, protection contre le double envoi des formulaires.
3. Vocabulaire juste et en français québécois : « À collecter », « Relancer », « Reçu comptant », tutoiement cohérent, messages d'erreur clairs.

**Problèmes les plus importants**

1. **Un seul tap envoie un texto à tous les clients** : « Démarrer : Neige » part sans confirmation ni annulation, avec « Aviser tous les clients » coché par défaut. Avec des gants, c'est un accident garanti.
2. **Les actions principales sont deux à trois écrans plus bas** : « Démarrer » est à 1 413 px (la météo prend l'écran), « Enregistrer le paiement » à 1 821 px, le solde du client à 1 450 px sur une fiche de 3 211 px. La navigation est en haut, hors de la zone du pouce, et disparaît au défilement.
3. **L'administration n'est pas un outil de travail pour Louis** : 30 tables techniques (dont « Procrastinate jobs »), aucun indicateur, texte de 11 à 13 px, titres du type « Sélectionnez l'objet client à changer », seule action en lot = « Supprimer ».

## Recommandations : application mobile

Trié par sévérité. Mesures prises à 390 x 844 sauf indication.

| Écran | Constat | Impact sur l'usager | Sévérité | Effort | Recommandation précise |
| --- | --- | --- | --- | --- | --- |
| Tournée | « Démarrer : Neige » envoie l'opération et un texto à tous les clients en un tap; case « Aviser tous les clients » cochée par défaut; aucune confirmation ni annulation | Un tap accidentel (gants, poche, support) texte toute la clientèle; impossible à reprendre | Critique | Faible | Feuille de confirmation qui résume : type, nombre de clients avisés, bouton « Confirmer » à maintenir 1 s. Puis 10 s d'annulation avant l'envoi réel des textos (file d'attente retardée). |
| Tournée | Les 4 boutons « Démarrer » sont à 1 413 px, sous 6 blocs de météo ouverts par défaut (page de 2 061 px) | Louis doit défiler deux écrans avec des gants pour faire la tâche principale de l'app | Critique | Faible | Mettre « Démarrer » en haut. Météo réduite à une ligne (« Cette nuit : neige 5 cm ») dépliable, fermée par défaut. |
| Toutes | Navigation (Tournée, Clients, Factures, Comptes) en haut de page, hors de la zone du pouce, et elle défile avec la page; l'en-tête collant ne garde que 3 boutons | Pour changer d'onglet, il faut remonter puis atteindre le haut d'un écran de 6,9 po | Majeure | Moyen | Barre d'onglets fixe en bas, 4 ou 5 onglets avec icône + libellé, 64 px de haut + zone sécurisée iOS (env(safe-area-inset-bottom)). |
| En-tête | « Déconnexion » est un gros bouton (142 x 46) toujours visible à côté des notifications | Tap accidentel : Louis doit retaper son mot de passe sur la route | Majeure | Faible | Déplacer dans un onglet « Plus » ou « Réglages », avec confirmation. |
| En-tête | Icône mégaphone orange pour « Demandes », enveloppe sans compteur pour « Messages » | Le mégaphone évoque une annonce, pas une plainte; un texto non lu ne se voit pas | Majeure | Faible | Libellés visibles sous les icônes; pastille de non-lus sur Messages; icône drapeau ou cloche pour Demandes. |
| Facture | « Enregistrer le paiement » est à 1 821 px, sous l'aperçu, le PDF et les envois; page de 2 068 px | Encaisser du comptant à la porte demande trois écrans de défilement | Majeure | Faible | Bouton collant en bas « Reçu 344,93 $ comptant » quand la facture est due; le détail des modes s'ouvre en feuille. |
| Facture | « Annuler » et « Enregistrer le paiement » côte à côte, même taille (138 x 105 et 166 x 105) | Risque d'effacer la saisie avec des gants | Mineure | Faible | Retirer « Annuler » (le retour suffit) ou en faire un lien discret; bouton principal pleine largeur. |
| Fiche client | Page de 3 211 px; le solde (« Doit 724,93 $ ») arrive à 1 450 px après 3 liens jaunes, l'appel, les contacts et la carte | Les deux questions de Louis (combien il doit, où il reste) demandent deux écrans | Majeure | Moyen | En haut : nom, statut, solde en gros, 3 boutons ronds (Appeler, Texto, Itinéraire), puis « Encaisser » et « Relancer ». Le reste en sections repliables. |
| Fiche client | Trois actions en liens jaunes de même poids (Modifier, Écrire, Noter un appel) | Aucune hiérarchie; « Modifier », rarement utile sur la route, est le premier | Mineure | Faible | Regrouper dans un menu « … »; garder seulement les actions fréquentes en boutons. |
| Fiche client | « Village · arrêt 40 » alors que la liste d'ordre affiche 4 | Numéro qui ne correspond à rien pour Louis | Mineure | Faible | Afficher le rang réel (« 4e arrêt du Village »), pas la valeur technique. |
| Ordre de la tournée | Adresses tronquées à « 120, rue de… »; déplacement seulement d'une place à la fois avec ▲ ▼ | Impossible de distinguer deux adresses semblables; déplacer un arrêt de 6 places = 6 taps et 6 rechargements | Majeure | Moyen | Adresse sur deux lignes; poignée de glisser-déposer (F1 du PRD) en plus des flèches; libellés accessibles « Monter Ginette Tremblay ». |
| Balises | Noms tronqués (« Ginett… ») par le champ et le bouton; bouton vert « Posées » qui ressemble à un statut | Louis ne sait pas si c'est fait ou à faire | Majeure | Faible | Nom pleine largeur sur une ligne, puis rangée « − 4 + » et bouton « Marquer posées »; une fois fait, carte grisée avec ✓ et date. |
| Comptes | 9 liens empilés (versements, relances, chèques, Interac, dépenses, rapport, export, saison suivante, brouillons) et l'onglet s'appelle « Comptes » mais la page « À recevoir » | Tiroir fourre-tout; les tâches du soir et celles de fin de saison sont mêlées | Majeure | Moyen | Deux groupes : « À faire » (cartes avec compteur : relances, versements, brouillons, Interac à apparier) et « Outils » (rapport, export, saison suivante, dépenses). Même nom pour l'onglet et la page. |
| Comptes | « Encaissé 258,69 $ » et « Encaissé, 30 jours 258,69 $ » affichés tous les deux | Chiffre en double, lecture plus lente | Mineure | Faible | Garder Facturé, Encaissé, À recevoir; mettre « plus de 60 jours » dans la carte À recevoir. |
| Factures | Statut « à émettre » coupé sur deux lignes sous le montant; statuts en texte coloré seulement | Liste plus difficile à balayer; le rouge et le vert portent seuls le sens | Mineure | Faible | Pastilles de statut (Brouillon, Envoyée, Due, En retard, Payée) avec texte + couleur, sur une ligne. |
| Messages | Le courriel Interac apparaît comme un message de la cliente, sans action | Louis doit lui-même faire le lien avec la facture | Majeure | Moyen | Carte spéciale « Virement Interac 158,69 $ » avec « Appliquer à la facture n° … » prérempli (base de D5). |
| Messages | Bloc « Notifications refusées » et deux liens avant la liste des messages | La liste, ce qui compte, est sous la ligne de flottaison | Mineure | Faible | Bandeau d'une ligne pour les notifications; filtres Reçus/Envoyés en haut; « Écrire » en bouton flottant. |
| Nouveau client | 26 champs sur 4 021 px; adresse de facturation avant l'adresse de service; prénom et nom non obligatoires | Saisie longue au cellulaire; l'info vitale (adresse de service, cellulaire) est loin | Majeure | Moyen | Mode court par défaut : nom, cellulaire, adresse de service, secteur, prix. Le reste dans « Plus de détails ». Adresse de facturation masquée derrière « Différente de l'adresse de service ». |
| Nouvelle facture | Pas de total avec taxes avant « Créer le brouillon »; puces de service tassées (« Pelletage du balcon » sur 3 lignes) | Louis ne voit pas ce que le client paiera; lecture difficile | Mineure | Faible | Total TPS + TVQ calculé en direct sous le prix; prix sous le libellé de la puce, pas à côté. |
| Toutes | Thème noir seulement (pas de version claire) | Noir et gris peu lisibles en plein soleil sur la neige (reflets) | Majeure | Moyen | Mode « Soleil » clair à très fort contraste, commutable en un tap dans l'en-tête, en plus du mode nuit actuel. |
| Toutes | Aucun style de focus défini; gris #6A7282 sur noir = 4,34:1 (« Annuler cette facture »), gris sur carte = 2,22:1 (« (+1) »); contours de boutons #3D444D = 2,1:1 | Échecs WCAG 1.4.3, 1.4.11 et 2.4.7 | Mineure | Faible | Texte secondaire #9AA4B2 (8,3:1 sur noir, 7,2:1 sur carte); contour #5B6573 (3,1:1 sur carte); anneau de focus jaune 3 px. |
| Facture | Case « garder le surplus en crédit » de 18 x 30 px | Sous le minimum de 44 px; ratable avec des gants | Mineure | Faible | Toute la rangée cliquable, case de 30 px, hauteur 56 px. |
| Textes | « 1 Nov au 15 Avr », « 1 septembre » | Abréviations et ordinal non conformes au français québécois | Mineure | Faible | « 1er nov. au 15 avr. », « 1er septembre » (filtre de date commun). |
| Tablette | À 768 px, colonne unique étirée pleine largeur | Espace perdu; boutons de 700 px de large | Mineure | Moyen | Largeur max. 640 px centrée, ou fiche client en 2 colonnes (infos à gauche, argent à droite). |

## Recommandations : administration

Le constat de fond : admin.ledeneigeur.com est l'admin Django par défaut, un outil de base de données. Il convient à Jean-François pour la configuration, pas à Louis pour sa facturation du soir. Pour Louis, la meilleure réponse est une **vue bureau de l'app mobile** (même app, mise en page large), pas un admin rhabillé.

| Écran | Constat | Impact sur l'usager | Sévérité | Effort | Recommandation précise |
| --- | --- | --- | --- | --- | --- |
| Ensemble | Louis doit utiliser l'admin le soir, mais elle expose 30 tables techniques (Procrastinate jobs, États de la boîte courriel, Gabarits par défaut) | Louis ne s'y retrouvera pas; risque de modifier une table interne | Critique | Élevé | Louis travaille dans l'app (louis.ledeneigeur.com) en vue bureau ≥ 1024 px : liste à gauche, détail à droite. L'admin reste réservée à Jean-François (rôle administrateur). |
| Tableau de bord | Liste de modèles par application Django; aucun chiffre, aucune alerte (sauf « 1 nouvelle » demande) | Jean-François ne voit pas d'un coup d'oeil si tout roule (envois en échec, file bloquée) | Majeure | Moyen | Page d'accueil « Plateforme » : cartes Envois en échec, Tâches en attente depuis + 5 min, Dernière sauvegarde, Envois réels activés oui/non par entreprise, Demandes à info@. |
| Entreprise | « Envois réels activés » est une case parmi 51 champs, au milieu d'une page de 3 425 px | L'interrupteur qui fait partir de vrais textos est invisible; erreur coûteuse | Critique | Faible | Bandeau en haut de la fiche et dans l'en-tête de l'app : « Envois réels : ACTIVÉS » (rouge) ou « Simulation » (gris); bascule avec confirmation et journal. |
| Entreprise | Sections nommées avec les codes du PRD : « Versements des contrats (B3, C5) », « Relances proposées (C9) » | Jargon interne visible par un futur déneigeur client de SLAPP | Mineure | Faible | Retirer les codes des libellés (les garder en commentaire de code). |
| Listes (Entreprises, Clients…) | Seule action en lot : « Supprimer les entreprises sélectionnés »; bouton « Supprimer » sur chaque fiche à côté de « Enregistrer » | Suppression d'une entreprise entière à deux clics de distance | Majeure | Faible | Retirer la suppression en lot sur Entreprise, Client, Facture, Paiement; remplacer par « Désactiver »; actions utiles en lot : exporter CSV, changer de secteur, marquer inactif. |
| Listes | « 0 clients » sous une recherche vide, sans explication | Liste vide qui ressemble à une panne | Mineure | Faible | État vide : « Aucun client pour Louis Méthot Déneigement. Importer un fichier CSV » + lien vers l'import (A9). |
| Listes | Titres Django : « Sélectionnez l'objet client à changer », « Modification de entreprise », « 8 journal des actions », filtre « Par par », « Par consent aux messages » | Fautes et tournures traduites qui nuisent au sérieux | Mineure | Faible | Renommer : « Clients », « Modifier l'entreprise », « 8 actions », « Par auteur », « Par consentement » (verbose\_name et verbose\_name\_plural). |
| Journal des actions | Heures écrites « 17 05 17 »; tableau plus large que l'écran à 1440 px | Lecture difficile; défilement horizontal | Mineure | Faible | Format « 9 nov. 2026, 17 h 05 »; colonnes Champs et Entreprise tronquées avec infobulle. |
| Plateforme (usage) | 25 colonnes, défilement horizontal dès 1440 px, en-têtes en majuscules de 11 px sur 5 lignes | Impossible de comparer deux mois ou deux entreprises sans se perdre | Majeure | Moyen | Regrouper en 4 blocs (Communications, Facturation, Tournée, Espace) affichés en cartes par entreprise; tableau complet seulement dans l'export CSV. |
| Ensemble | Texte de 11 à 14 px (en-têtes 11 px, barre latérale 12 px, cellules 13 px) | Fatigue visuelle le soir, surtout pour Louis | Mineure | Faible | Base 16 px, tableaux 15 px, en-têtes 13 px en petites capitales plutôt qu'en majuscules. |
| Ensemble à 1024 px | Barre latérale (200 px) + filtres (160 px) laissent environ 350 px au contenu | Listes écrasées sur un portable ou une tablette en paysage | Majeure | Faible | Fermer la barre latérale par défaut sous 1280 px; filtres dans un panneau déroulant au-dessus de la liste. |
| Ensemble | Thème bleu-gris Django, titre jaune, aucun lien visuel avec l'app noire et jaune; nom « LMAPP : administration » | Deux produits qui ne se ressemblent pas; nom de projet interne visible | Mineure | Faible | Appliquer les jetons du système de design (section suivante) au thème admin; nommer « Le Déneigeur : administration ». |
| Erreur 404 | Page blanche en anglais : « Not Found. The requested resource was not found on this server. » | Sentiment de site cassé | Mineure | Faible | Gabarits 404 et 500 en français avec lien de retour, dans les deux interfaces. |
| Admin en production | L'admin pointe sur la base de production, l'app de test sur une autre base | Confusion possible : on croit tester dans l'admin alors qu'on touche aux vraies données de Louis | Majeure | Faible | Bandeau permanent « PRODUCTION » rouge dans l'admin (comme le bandeau jaune de test), et une admin de test séparée. |

## Gains rapides (impact élevé, effort faible)

Dans l'ordre où je les ferais. Les sept premiers tiennent dans une journée de travail de Claude Code sur ld1.

- [ ] Confirmation + 10 s d'annulation sur « Démarrer » quand des clients seront avisés.
- [ ] Remonter les boutons « Démarrer » en haut de Tournée; météo réduite à une ligne, fermée par défaut.
- [ ] Bandeau « Envois réels : ACTIVÉS / Simulation » visible dans l'app et dans l'admin.
- [ ] Bandeau rouge « PRODUCTION » dans l'admin.
- [ ] Sortir « Déconnexion » de l'en-tête.
- [ ] Bouton collant « Reçu ... $ comptant » au bas de la facture due.
- [ ] Solde du client et bouton « Encaisser » remontés en haut de la fiche client.
- [ ] Pastille de non-lus sur Messages; libellé sous l'icône Demandes.
- [ ] Balises : nom pleine largeur, bouton « Marquer posées », carte grisée une fois fait.
- [ ] Retirer la suppression en lot (et le bouton Supprimer) sur Entreprise, Client, Facture, Paiement.
- [ ] Corriger les textes : titres d'admin, « Par par », « Par consent », « sélectionnés », « 1er nov. », codes B3/C5/C9, page 404 en français.
- [ ] Contraste : texte secondaire #9AA4B2, contours #5B6573, anneau de focus jaune.

## Les 5 changements les plus importants

Chaque écran est décrit de haut en bas, à 390 x 844, tel qu'il devrait apparaître à Louis. Les mesures sont en px CSS.

### 1. Tournée : démarrer sans défiler, sans accident

1. **En-tête collant (56 px)** : « Déneigement Essai » à gauche, bascule Soleil/Nuit à droite. Plus de Déconnexion.
2. **Ligne météo (56 px, repliée)** : « Cette nuit : neige, min. +1 · Saint-Sauveur » et un chevron. Le détail s'ouvre au tap.
3. **Grand bouton « Démarrer : Neige »** jaune, pleine largeur, 88 px. Dessous, une rangée de 3 boutons de 64 px : Verglas, Bordage, Finition.
4. **Case « Aviser les 9 clients »** affichée sous le bouton avec le nombre réel.
5. **Au tap : feuille de confirmation** qui monte du bas. Titre « Démarrer une opération Neige? », ligne « 9 clients recevront un texto », aperçu du texte, bouton « Maintenir pour démarrer » (anneau qui se remplit en 1 s), lien « Annuler ».
6. **Après le démarrage : bandeau « Textos envoyés dans 10 s · Annuler »** pendant 10 secondes, puis « 9 textos envoyés ».
7. Plus bas : À collecter (avec le total, ex. « 1 012,37 $ »), Ordre, Balises, Dernières opérations.
8. **Barre d'onglets fixe en bas** (voir le point 5).

### 2. Pendant l'opération : le tableau de bord du tracteur

C'est l'écran que l'app affiche une fois l'opération lancée, téléphone sur le support (non observé dans l'audit; voici la cible).

1. **Bande d'état** verte : « Neige · en cours depuis 1 h 12 · 4 sur 10 » et un indicateur GPS (point vert = position captée, gris = perdue). Indicateur « Hors ligne : 2 actions en attente » en orange si le réseau tombe.
2. **Carte du prochain arrêt**, la moitié de l'écran : adresse en 32 px gras sur deux lignes, nom du client en 20 px, consignes du terrain en jaune (« Neige à gauche, borne-fontaine »).
3. **Deux boutons géants côte à côte, 120 px de haut** : « Fait ✓ » (vert, 2/3 de la largeur) et « Sauté » (contour, 1/3). « Sauté » ouvre 4 raisons en gros boutons : Auto dans l'entrée, Absent, Non payé, Autre.
4. **Rangée de 3 boutons de 64 px** : Itinéraire (ouvre l'app choisie une fois dans les réglages), Appeler, Note.
5. **Bandeau « Annuler » de 5 s** après chaque Fait ou Sauté.
6. Liste des 3 arrêts suivants en petit, sous la ligne de flottaison.
7. Écran maintenu allumé (Wake Lock) et mode Nuit forcé après le coucher du soleil.

### 3. Fiche client : l'argent et le contact d'abord

1. **Bloc identité** : « Marcel Côté », pastille « Recouvrement », adresse « 45, chemin de l'Exemple · 4e arrêt du Village ».
2. **Trois boutons ronds de 64 px** avec libellé dessous : Appeler, Texto, Itinéraire.
3. **Carte Argent** : « Doit 724,93 $ » en 32 px rouge, dessous « 2 factures · la plus vieille : 69 jours ». Deux boutons de 64 px : « Encaisser » (vert, ouvre la feuille de paiement de la facture la plus ancienne) et « Relancer » (jaune, propose le bon niveau : Rappel, Deuxième avis, Dernier avis).
4. **Fil récent** : les 3 derniers messages, avec « Tout voir ».
5. **Sections repliables**, fermées par défaut : Factures et paiements, Contrat 2026-2027, Terrain et consignes, Contacts, Demandes, Notes.
6. **Menu « … » en haut à droite** : Modifier le client, Noter un appel, Nouvelle facture, Chèque postdaté, État de compte.

Résultat attendu : la fiche passe de 3 211 px à environ 1 000 px ouverte, et l'encaissement passe de 2 écrans de défilement à 0.

### 4. Encaisser comptant en deux taps

1. Sur une facture due, **barre collante en bas (88 px)** : « Reçu 344,93 $ » avec le mode préféré du client (« Comptant ») affiché dessous.
2. Tap : **feuille de paiement** avec le montant prérempli en 40 px, modifiable au clavier décimal; 5 puces de mode; « Envoyer un reçu par texto » coché.
3. **Bouton pleine largeur « Enregistrer 344,93 $ comptant »**, pas de bouton Annuler (glisser la feuille vers le bas suffit).
4. Confirmation : écran vert « Payée · reçu envoyé » pendant 2 s, puis retour à la fiche avec le nouveau solde.
5. « Annuler cette facture » déménage dans le menu « … » de la facture.

### 5. Navigation au pouce

1. **Barre d'onglets fixe en bas, 64 px + zone sécurisée** : Tournée, Clients, Argent (ancien « Comptes », factures incluses), Messages (pastille de non-lus), Plus.
2. Icône 28 px + libellé 13 px sous chaque onglet; onglet actif en jaune avec fond plus clair.
3. **« Plus »** regroupe : Demandes, Balises, Dépenses, Rapports, Messages types, Réglages, Déconnexion.
4. **En-tête réduit à 56 px**, collant, avec seulement le titre de l'écran et une action contextuelle à droite.
5. Sur iPad et ordinateur (≥ 1024 px), la même barre devient une colonne à gauche, liste au centre, détail à droite : c'est la vue bureau pour Louis le soir.

## Système de design minimal commun

Je garde l'identité déjà présente dans l'app (noir et jaune chasse-neige) et je la formalise en jetons CSS, partagés par l'app et le thème de l'admin. Deux thèmes : **Nuit** (actuel, par défaut le soir) et **Soleil** (nouveau, pour le jour sur la neige). Tous les ratios ci-dessous sont calculés (WCAG 2.2).

**Palette**

| Jeton | Nuit | Soleil | Usage | Contraste |
| --- | --- | --- | --- | --- |
| fond | #000000 | #FFFFFF | Fond de page | Référence |
| surface | #12161C | #F2F4F7 | Cartes, champs | Référence |
| texte | #F5F7FA | #0B0D10 | Texte principal | 16,9:1 / 19,5:1 |
| texte-2 | #9AA4B2 | #3D4450 | Dates, adresses, aide | 7,2:1 / 8,9:1 sur surface |
| bordure | #5B6573 | #6B7280 | Contours de champs et boutons secondaires | 3,1:1 / 4,8:1 |
| accent | #F5C400 | #F5C400 (fond) et #7A5F00 (texte) | Action principale, onglet actif, focus | Noir sur jaune 12,8:1; #7A5F00 sur blanc 6,1:1 |
| succès | #3FB950 | #1A7F37 | Payé, Fait, Encaisser | 7,1:1 / 5,1:1 |
| danger | #FF6B6B | #C62828 | Doit, En retard, Recouvrement | 6,5:1 / 5,6:1 |
| avertissement | #FF9A3C | #B45309 | Demandes à régler, hors ligne | 8,6:1 / 5,0:1 |
| info | #58A6FF | #1D4ED8 | Liens secondaires, GPS | 7,2:1 sur surface |

Règle : la couleur ne porte jamais le sens seule. Chaque statut a un mot (Payée, Due, En retard) et, au besoin, une icône.

**Typographie**

- Police système (SF Pro sur iPhone, Segoe UI sur Windows) : rapide, nette, déjà en place. Chiffres tabulaires (font-variant-numeric: tabular-nums) pour tous les montants.
- Échelle mobile : 32 (montant ou adresse clé), 24 (titre d'écran), 20 (nom, bouton), 17 (texte courant, minimum), 15 (métadonnée). Rien sous 15 px dans l'app.
- Échelle bureau et admin : 28, 20, 16 (base), 15 (tableaux), 13 (en-têtes de colonnes en petites capitales).
- Graisses : 400 et 700 seulement.

**Espacement, formes, zones tactiles**

- Grille de 8 px : 8, 16, 24, 32, 48. Marge d'écran mobile 16 px.
- Rayons : 12 px (boutons, champs), 16 px (cartes), pilule pour les pastilles.
- Hauteurs : bouton principal 64 px (88 à 120 px en opération), secondaire 56 px, champ 56 px, rangée de liste 64 px, onglet 64 px. Minimum absolu 48 x 48 px, écart de 8 px entre deux cibles.
- Focus : anneau accent de 3 px, décalage de 2 px, sur tout élément actif (:focus-visible).

**Composants de base**

| Composant | Variantes | Règles |
| --- | --- | --- |
| Bouton | Principal (jaune, texte noir), Succès (vert), Secondaire (contour), Danger (contour rouge), Lien | Un seul principal par écran; actions irréversibles = confirmation ou annulation de 5 à 10 s |
| Barre d'onglets | 5 onglets, icône + libellé | Fixe en bas sur mobile, colonne à gauche sur bureau |
| Carte | Standard, Cliquable (chevron), Alerte | Titre 20 px, métadonnée 15 px texte-2 |
| Rangée de liste | Nom + adresse à gauche, montant + pastille à droite | Texte jamais tronqué sur une adresse : deux lignes |
| Pastille de statut | Brouillon, Envoyée, Due, En retard, Payée, Recouvrement, Urgent | Mot + couleur, fond à 15 % d'opacité |
| Champ | Texte, Téléphone, Montant, Date, Liste | Libellé au-dessus, aide dessous, erreur en rouge avec icône, bon clavier (inputmode) |
| Feuille du bas | Confirmation, Paiement, Raisons | Monte du bas, se ferme en glissant, bouton principal pleine largeur |
| Bandeau | Info, Annuler (minuteur), Hors ligne, Test, Production, Envois réels | Collant sous l'en-tête, une ligne |
| État vide | Icône, phrase, action | Toujours une action proposée (Importer, Créer) |

**Mise en oeuvre** : un fichier `tokens.css` (variables CSS pour les deux thèmes) branché dans la configuration Tailwind de l'app, et le même fichier chargé dans le gabarit `admin/base_site.html` pour remplacer les variables du thème Django (--primary, --secondary, --body-bg, etc.).

## Annexe : captures de l'état actuel

Captures prises le 9 novembre 2026 sur test.ledeneigeur.com (390 x 844) et admin.ledeneigeur.com. Aucune capture de la fiche entreprise (vraies données de Louis).

**Tournée, haut de page** : la météo occupe l'écran, aucun bouton Démarrer visible.

&#91;image: Tournée, haut de page\]

**Tournée, deux écrans plus bas** : les boutons Démarrer et la case Aviser tous les clients, cochée.

&#91;image: Tournée, boutons Démarrer\]

**Fiche client** : trois liens de même poids, le solde n'est pas visible.

&#91;image: Fiche client\]

**Facture, bas de page** : Annuler et Enregistrer le paiement côte à côte, Annuler cette facture en gris pâle.

&#91;image: Facture, paiement\]

**Ordre de la tournée** : adresses tronquées.

&#91;image: Ordre de la tournée\]

**Balises** : noms tronqués, bouton Posées ambigu.

&#91;image: Balises\]

**Comptes** : indicateurs de saison, chiffre Encaissé en double.

&#91;image: Comptes\]

**Nouveau client** : début d'un formulaire de 26 champs; la barre Annuler/Enregistrer collante est une bonne pratique à garder.

&#91;image: Nouveau client\]

**Administration, accueil à 1440 px** : liste de tables Django, aucun indicateur.

&#91;image: Administration, accueil\]

**Administration à 1024 px** : barre latérale et filtres écrasent la liste.

&#91;image: Administration à 1024 px\]

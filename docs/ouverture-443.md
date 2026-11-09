# Ouverture du 443 à tout Internet : dossier à valider par JF

Décision de JF (8 novembre 2026) : on ouvre le 443 à tout Internet seulement après le balayage externe (PRD 6.1.1)
et après validation de : (a) la règle exacte du routeur et du frontal, (b) un test automatisé qui prouve que les
webhooks sans signature valide sont refusés, (c) la liste des chemins publics et restreints.
**Rien n'est ouvert tant que JF n'a pas validé.** L'ouverture elle-même est faite par JF, au routeur.

## Ce qui ne change pas à l'ouverture

- Seul le **443 TCP** est redirigé (`216.46.12.226` vers `172.16.4.100`). Rien d'autre : ni 80, ni 22, ni 5000.
- Seul Caddy publie un port sur ld1. La base, l'app et le worker n'en publient aucun (vérifié après chaque déploiement).
- Un nom inconnu ou l'IP directe : Caddy refuse la connexion TLS (aucun certificat, aucune page). Vérifié le 8 novembre 2026.
- `/admin/` : seulement sur `admin.ledeneigeur.com` (404 ailleurs) et seulement depuis les IP de JF (`LMAPP_IPS_ADMIN`, sinon 403).
- Connexion : blocage temporaire après 10 échecs par IP ou 20 par nom d'utilisateur en 15 minutes.
- Prod : `DEBUG` faux, témoins `Secure`, HSTS d'un an, `X-Frame-Options: DENY`, `nosniff`.

## (a) Règles exactes

### Routeur Mikrotik (fait par JF)

État actuel (relevé par JF le 8 novembre 2026) : **une seule règle NAT couvre 22 et 443 ensemble**, avec `_SLAPP` en
« Src. Address List ». À l'ouverture : **deux règles séparées**, le 443 sans restriction, le 22 qui reste dans `_SLAPP`.

**1. Afficher** la règle actuelle et noter son numéro (`<n>`) :

```
/ip firewall nat print detail where chain=dstnat
/ip firewall filter print detail where chain=forward
```

La deuxième commande sert à vérifier qu'aucune règle `forward` ne limite aussi le 443 à `_SLAPP` (la configuration par
défaut du Mikrotik laisse passer ce qui a été redirigé : `connection-nat-state=dstnat`). S'il y en a une, me la montrer
avant d'aller plus loin.

**2. Ajouter la règle du 443, sans restriction, juste avant l'actuelle** (le 443 reste ouvert à `_SLAPP` pendant tout
le changement, aucune coupure) :

```
/ip firewall nat add chain=dstnat action=dst-nat protocol=tcp dst-address=216.46.12.226 dst-port=443 to-addresses=172.16.4.100 to-ports=443 comment="ld1 443 public (Le Deneigeur)" place-before=<n>
```

**3. Limiter l'ancienne règle au 22** (elle garde `_SLAPP`). Attention : après l'ajout, son numéro a augmenté de 1;
refaire le `print` de l'étape 1 et prendre le nouveau numéro (`<n2>`) :

```
/ip firewall nat set <n2> dst-port=22
```

Résultat attendu au `print` :

```
chain=dstnat action=dst-nat to-addresses=172.16.4.100 to-ports=443 protocol=tcp dst-address=216.46.12.226 dst-port=443   (sans liste)
chain=dstnat action=dst-nat to-addresses=172.16.4.100 protocol=tcp dst-address=216.46.12.226 dst-port=22 src-address-list=_SLAPP
```

(Les autres paramètres de l'ancienne règle ne changent pas; s'ils diffèrent de ce qui est écrit ici, c'est normal.)

**Retour en arrière** (refermer le 443 au public, en deux commandes) :

```
/ip firewall nat remove [find comment="ld1 443 public (Le Deneigeur)"]
/ip firewall nat set <n2> dst-port=22,443
```

### Règles en place (relevées par JF le 9 novembre 2026)

Seules les règles NAT qui visent ld1 sont reprises ici; les autres règles du routeur ne concernent pas LMAPP et
restent hors de ce dépôt.

```
31    ;;; permettre SSH vers lmapp JF _SLAPP
      chain=dstnat action=dst-nat to-addresses=172.16.4.100 protocol=tcp
      dst-address=216.46.12.226 src-address-list=_SLAPP dst-port=22

32    ;;; permettre 443 wan vers lmapp JF
      chain=dstnat action=dst-nat to-addresses=172.16.4.100 to-ports=443 protocol=tcp
      dst-address=216.46.12.226 dst-port=443
```

Conforme à la décision : 443 ouvert à tous, 22 limité à `_SLAPP`. Le commentaire diffère de celui proposé plus haut :
pour revenir en arrière, désactiver la règle 32 (`/ip firewall nat disable 32`, après un `print` pour confirmer le
numéro) plutôt que le `remove [find comment=...]`.

À noter : une ancienne règle **désactivée** (« QNAP Danik », `216.46.29.156:48899` vers `172.16.4.100:8899`) vise
encore l'IP de ld1. Rien n'écoute sur 8899 dans ld1 et ufw le bloquerait, mais si elle était réactivée par erreur, le
port arriverait sur ld1. Proposé : la supprimer, ou lui changer de destination, au choix de JF.

### Frontal Caddy (`edge/Caddyfile`, état actuel)

| Nom | Où ça va | Restriction |
|---|---|---|
| `louis.ledeneigeur.com` | app de prod | aucune au réseau; l'app exige une connexion, sauf les chemins publics (c) |
| `test.ledeneigeur.com` | app de test | tout le site réservé aux IP de JF (proposition 1, en place) |
| `admin.ledeneigeur.com` | app de prod, `/admin/` et `/static/` seulement (le reste : 404) | `/admin/` réservé aux IP de JF |
| tout autre nom, IP directe | rien | refus TLS |

Les trois sites importent le bloc `commun` : HSTS, `nosniff`, `Referrer-Policy: same-origin`, journal d'accès JSON,
et `/admin/` réservé aux IP de JF (403 « Accès refusé. » ailleurs).

### Propositions (acceptées par JF le 8 novembre 2026, en place)

1. **Garder le test fermé** : aujourd'hui, seul le routeur protège `test.ledeneigeur.com`. Une fois le 443 ouvert,
   n'importe qui verrait la page de connexion du test. Proposé : réserver tout le site de test aux IP de JF dans
   Caddy (même liste que l'administration). C'est une deuxième couche dans Caddy, ce que la décision du
   7 novembre 2026 écartait. **Accepté par JF et en place** : depuis une autre IP, 403 « Accès refusé. »; depuis ld1, 200.

   ```
   test.ledeneigeur.com {
   	import commun
   	@pas_jf not remote_ip {$LMAPP_IPS_ADMIN}
   	respond @pas_jf "Accès refusé." 403
   	reverse_proxy lmapp-test-app:8000
   }
   ```
2. **Taille des envois** : plafonner le corps des requêtes à 10 Mo dans `commun` (`request_body { max_size 10MB }`).
   La plus grosse requête légitime est une photo de l'entrée (8 Mo au plus, environ 300 Ko une fois réduite).
   **Accepté et en place** : un envoi de 11 Mo reçoit 413.

## (b) Webhooks : preuve automatisée

- **Test de l'app** (`src/core/tests_exposition.py`, `ExpositionTests.test_webhooks_sans_signature_valide_refuses`,
  roulé à chaque série de tests) : sur `/webhooks/twilio/textos/` et `/webhooks/twilio/statut/`, sans en-tête,
  avec une signature fausse ou vide : 403, et rien n'est enregistré. Sans Auth Token configuré : 403 aussi.
  Les tests existants (`communications/tests.py`, `WebhooksTwilioTests`) vérifient qu'une signature valide est acceptée.
- **Vérification de bout en bout, à travers Caddy** (`outils/verifier_webhooks.sh`, environnement de test), résultat du 8 novembre 2026 :

  ```
  sans signature      : 403
  signature fausse    : 403
  corps modifié       : 403
  signature valide    : 200
  GET                 : 405
  ```

## (c) Chemins publics et restreints

Liste tirée de Django lui-même (`core/tests_exposition.py`). Le test vérifie **chaque** route en visiteur anonyme,
en GET et en POST : toute route absente de la liste des publics doit renvoyer à la connexion, refuser ou répondre 404.
Une route ajoutée plus tard est vérifiée automatiquement.

### Publics (sans compte), 10

| Chemin | Pourquoi |
|---|---|
| `/connexion/` | page de connexion (essais limités) |
| `/deconnexion/` | POST seulement |
| `/f/<jeton>/`, `/f/<jeton>/pdf/` | facture vue par le client, lien secret de 192 bits; jeton inconnu : 404 |
| `/webhooks/twilio/textos/`, `/webhooks/twilio/statut/` | Twilio; signature obligatoire, sinon 403 |
| `/sante/` | répond seulement `{"app": "ok", "base": "ok"}` |
| `/manifest.webmanifest`, `/favicon.ico`, `/sw.js` | fichiers de la PWA, aucune donnée de client |
| `/static/...` | CSS, JavaScript, icônes (aucune donnée) |

### Restreints (connexion et membre de l'entreprise du domaine), 48

Clients et adresses (`/`, `/clients/...`, `/adresses/...`, `/photos/...`), factures et argent (`/factures/...`,
`/comptes/`, `/comptes/export/`, `/virements/...`, `/clients/<id>/etat-de-compte/`), tournée (`/tournee/...`),
demandes (`/demandes/...`), messages (`/messages/...`), notifications (`/notifications/abonnement/`).
Gestes d'écriture : en plus, pas le rôle lecture seule.

### Administration

`/admin/...` : seulement sur `admin.ledeneigeur.com`, seulement depuis les IP de JF, puis compte de JF.

## Balayage externe (PRD 6.1.1), fait par JF

**Balayage « avant » : fait, conforme** (JF, 8 novembre 2026, 23 h 50, réseau cellulaire hors `_SLAPP`,
`nmap 7.80 -Pn -sV -p-`, fichier `nmap_avant.txt` gardé par JF) : 65 531 ports filtrés, dont 22, 443, 5000 et 5432.
21, 80, 554 et 1723 paraissent « open » avec des réponses HTTP 502 « Connection timed out » et « Tunnel Connection
Failed » : c'est le **proxy transparent du fournisseur cellulaire**, pas ld1 ni le Mikrotik. **Faux positifs à ignorer**
dans le balayage « après » s'il est fait du cellulaire. Rien d'exposé.

**Balayage « après » : fait, conforme** (JF, 9 novembre 2026, 0 h 08, réseau cellulaire, `nmap 7.80 -Pn -p 22,80,443,5000,5432,8000`) :
`443/tcp open`; 22, 5000, 5432 et 8000 filtrés (le 22 reste dans `_SLAPP`); 80 « open » : même faux positif du proxy
du fournisseur cellulaire qu'au balayage « avant » (ld1 ne publie pas le 80, le Mikrotik ne le redirige pas).

Attendu (pour mémoire), du même réseau cellulaire : `443/tcp open` (Caddy, TLS 1.2 et 1.3), 22 toujours
filtré (resté dans `_SLAPP`), 5000 et 5432 filtrés, et les mêmes faux positifs 21, 80, 554, 1723 du fournisseur.

À faire **depuis l'extérieur de ld1**, deux fois :

1. **Avant l'ouverture, depuis un réseau hors de `_SLAPP`** (ex. partage de connexion du cellulaire) : rien ne doit répondre.
2. **Juste après l'ouverture, du même réseau** : seul le 443 doit répondre.

Avec nmap (Windows : installateur sur nmap.org; même commandes dans une invite) :

```
nmap -Pn -p- -T4 216.46.12.226
nmap -Pn -sU --top-ports 50 216.46.12.226
nmap -Pn -p 443 --script ssl-enum-ciphers,http-headers 216.46.12.226
```

Attendu : seul `443/tcp open` (après l'ouverture), TLS 1.2 et 1.3 seulement. Le premier balayage dira aussi si
d'autres redirections existent déjà sur cette IP pour d'autres machines. Après, coller les résultats à Claude Code,
qui les note ici et dans le PRD.

Vérifications de navigateur, depuis le cellulaire hors Wi-Fi, après l'ouverture :
- `https://louis.ledeneigeur.com/` : page de connexion;
- `https://admin.ledeneigeur.com/admin/` : « Accès refusé. »;
- `https://test.ledeneigeur.com/` : « Accès refusé. » si la proposition 1 est retenue.

## Après l'ouverture

- Configurer chez Twilio « A message comes in » vers `https://louis.ledeneigeur.com/webhooks/twilio/textos/` (POST).
- Surveiller les journaux de Caddy les premiers jours (`cd /srv/lmapp/edge && docker compose logs caddy`).
- Mettre à jour CLAUDE.md et le PRD (le routeur n'est plus la barrière principale).

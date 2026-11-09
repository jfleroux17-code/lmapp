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

D'abord, afficher les règles actuelles pour repérer celles qui utilisent la liste `_SLAPP` sur le 443 :

```
/ip firewall nat print detail where dst-port=443
/ip firewall filter print detail where dst-port=443
```

Ouverture : retirer la condition de liste d'adresses source de la redirection (et de la règle `forward` qui
l'accompagne, s'il y en a une). Remplacer `<n>` par le numéro affiché par `print` :

```
/ip firewall nat set <n> !src-address-list
/ip firewall filter set <n> !src-address-list
```

La règle de redirection devient alors, en entier :

```
chain=dstnat action=dst-nat to-addresses=172.16.4.100 to-ports=443 protocol=tcp dst-address=216.46.12.226 dst-port=443
```

Retour en arrière (refermer, en une commande chacune) :

```
/ip firewall nat set <n> src-address-list=_SLAPP
/ip firewall filter set <n> src-address-list=_SLAPP
```

La liste `_SLAPP` reste en place : elle ne sert plus au 443, mais elle est prête pour un retour en arrière.

### Frontal Caddy (`edge/Caddyfile`, état actuel)

| Nom | Où ça va | Restriction |
|---|---|---|
| `louis.ledeneigeur.com` | app de prod | aucune au réseau; l'app exige une connexion, sauf les chemins publics (c) |
| `test.ledeneigeur.com` | app de test | **aucune** aujourd'hui (voir proposition 1) |
| `admin.ledeneigeur.com` | app de prod, `/admin/` et `/static/` seulement (le reste : 404) | `/admin/` réservé aux IP de JF |
| tout autre nom, IP directe | rien | refus TLS |

Les trois sites importent le bloc `commun` : HSTS, `nosniff`, `Referrer-Policy: same-origin`, journal d'accès JSON,
et `/admin/` réservé aux IP de JF (403 « Accès refusé. » ailleurs).

### Propositions à valider avant l'ouverture

1. **Garder le test fermé** : aujourd'hui, seul le routeur protège `test.ledeneigeur.com`. Une fois le 443 ouvert,
   n'importe qui verrait la page de connexion du test. Proposé : réserver tout le site de test aux IP de JF dans
   Caddy (même liste que l'administration). C'est une deuxième couche dans Caddy, ce que la décision du
   7 novembre 2026 écartait : à confirmer.

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

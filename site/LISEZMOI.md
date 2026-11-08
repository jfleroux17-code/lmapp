# Site Internet de Le Déneigeur (PRD Q5)

Site statique (HTML et CSS, aucune base de données, aucun script), servi par Caddy depuis ld1.

Avant la mise en ligne :
1. Remplacer `CONTACT_A_CONFIRMER` (index.html, confidentialite.html) par l'adresse de contact choisie par JF.
2. Faire valider la politique de confidentialité (responsable, durées) et retirer l'avis « Ébauche ».
3. Savoir ce qui est servi aujourd'hui à la racine de `ledeneigeur.com` (proxy Cloudflare vers 69.16.231.58).

Mise en ligne (avec le « go » de JF : DNS et Caddy) :
- `edge/compose.yaml` : monter `/srv/lmapp/site` en lecture seule dans le conteneur Caddy (ex. `/srv/site`).
- `edge/Caddyfile` : bloc `ledeneigeur.com, www.ledeneigeur.com { import commun  root * /srv/site  file_server }`
  (`www` redirigé vers la racine au besoin).
- Cloudflare : la racine et `www` en A vers 216.46.12.226, DNS seulement; au routeur, le 443 doit être ouvert à tous
  pour que le public voie le site (décision réseau de JF).

Captures : `images/ecran-*.png`, prises dans l'environnement de test (clients fictifs), bandeau de test retiré.
Aperçu local : ouvrir `index.html` dans un navigateur.

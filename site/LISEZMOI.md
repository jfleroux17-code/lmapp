# Site Internet de Le Déneigeur (PRD Q5)

Site statique (HTML et CSS, aucune base de données, aucun script). **Hébergé sur le serveur cPanel de JF, pas sur ld1**
(décision de JF, 8 novembre 2026) : JF a déjà pointé la racine et `www` de `ledeneigeur.com` vers ce serveur chez
Cloudflare. Aucun bloc Caddy pour la racine, et Claude Code ne touche pas à ces enregistrements DNS.

Le site ne dépend de rien d'autre : tous les liens sont relatifs, les images sont dans `images/`, aucun appel à ld1 ni
à `test.ledeneigeur.com`, aucune police ni script externe.

Exploitant : SLAPP Technologies Inc., 204, rue Saint-Charles, bureau 103, Sainte-Thérèse (Québec) J7E 2B4,
514 360-3227, `info@ledeneigeur.com` (boîte créée par JF). Responsable de la protection des renseignements
personnels : Jean-François Leroux (confirmé par JF).

## Mise en ligne

1. Refaire l'archive au besoin, depuis ld1 : `cd /srv/lmapp && sh outils/archiver_site.sh` (produit `/srv/lmapp/site.zip`,
   hors Git, sans ce fichier LISEZMOI).
2. La prendre sur GitHub (`site.zip` à la racine du dépôt `jfleroux17-code/lmapp`, bouton « Download raw file »), ou par
   `scp deploy@172.16.4.100:/srv/lmapp/site.zip .`
3. cPanel, Gestionnaire de fichiers : `public_html`, Téléverser `site.zip`, puis Extraire. `index.html` doit se
   retrouver directement dans `public_html` (pas dans un sous-dossier).

En ligne depuis le 9 novembre 2026. Politique de confidentialité validée par JF le même jour : si une durée de
conservation change dans l'app, la changer aussi dans `confidentialite.html`.

## Captures

`images/ecran-*.png` (cellulaire, 430 px de large, iPhone Pro Max) et `images/bureau-*` (ordinateur, 1440 px), prises dans l'environnement de test (clients fictifs, `donnees_essai` plus un scénario de tournée), au visuel C, bandeaux de test et de simulation retirés. Refaites le 11 novembre 2026.
Aperçu local : ouvrir `index.html` dans un navigateur.

Pas encore annoncé sur le site (décision de JF, 11 novembre 2026) : les **dépenses par photo du reçu** (S1, S2). Ne pas les ajouter avant son « go ».

**Cache de Cloudflare** : Cloudflare garde `style.css` 4 heures. Après un changement de `style.css`, changer le numéro dans `href="style.css?v=..."` de toutes les pages (date du jour), sinon les visiteurs voient l'ancienne feuille de style.

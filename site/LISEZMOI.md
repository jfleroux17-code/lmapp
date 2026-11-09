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
2. La copier sur le poste de JF : `scp deploy@172.16.4.100:/srv/lmapp/site.zip .`
3. cPanel, Gestionnaire de fichiers : `public_html`, Téléverser `site.zip`, puis Extraire. `index.html` doit se
   retrouver directement dans `public_html` (pas dans un sous-dossier).

Avant de l'annoncer : faire valider les durées de conservation de la politique de confidentialité et retirer l'avis
« Ébauche » en haut de `confidentialite.html`.

## Captures

`images/ecran-*.png`, prises dans l'environnement de test (clients fictifs), au visuel C, bandeau de test retiré.
Aperçu local : ouvrir `index.html` dans un navigateur.

#!/bin/sh
# Archive du site de présentation, prête à extraire dans public_html (cPanel). Voir site/LISEZMOI.md.
# L'archive est suivie par Git (demande de JF, 9 novembre 2026) : la refaire et la pousser à chaque
# modification du site. Dates fixes et ordre trié : même contenu, même archive (pas de faux changement).
set -eu
cd /srv/lmapp/site
python3 -c "
import os, zipfile
chemins = sorted(os.path.join(r, f)[2:] for r, _, fs in os.walk('.') for f in fs if f != 'LISEZMOI.md')
with zipfile.ZipFile('/srv/lmapp/site.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for chemin in chemins:
        info = zipfile.ZipInfo(chemin, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        with open(chemin, 'rb') as f:
            z.writestr(info, f.read())
        print(chemin)
"
echo "Archive : /srv/lmapp/site.zip"

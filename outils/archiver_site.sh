#!/bin/sh
# Archive du site de présentation, prête à extraire dans public_html (cPanel). Voir site/LISEZMOI.md.
set -eu
cd /srv/lmapp/site
rm -f /srv/lmapp/site.zip
python3 -c "
import os, zipfile
with zipfile.ZipFile('/srv/lmapp/site.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for racine, _, fichiers in os.walk('.'):
        for f in sorted(fichiers):
            if f == 'LISEZMOI.md':
                continue
            chemin = os.path.join(racine, f)[2:]
            z.write(chemin, chemin)
            print(chemin)
"
echo "Archive : /srv/lmapp/site.zip"

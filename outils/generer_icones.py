"""Génère les icônes de l'app (flocon jaune sur fond sombre), en SVG et en PNG.

Icône générique, sans nom ni initiales d'un déneigeur (CLAUDE.md, règle 7).
Pillow n'est pas une dépendance de l'app : lancer ce script dans un conteneur
jetable, puis garder les fichiers produits dans le dépôt :

  docker run --rm -v /srv/lmapp:/code -w /code python:3.13-slim sh -c \\
      "pip install -q pillow && python outils/generer_icones.py src/core/static/icones"
"""
import math
import sys
from pathlib import Path

FOND = "#0d1117"
FLOCON = "#f5c400"


def segments(taille, rayon_rel):
    """Les traits du flocon : 6 branches, chacune avec deux paires de ramures."""
    c = taille / 2
    r = taille * rayon_rel
    traits = []
    for k in range(6):
        a = math.radians(90 + 60 * k)
        ux, uy = math.cos(a), -math.sin(a)
        traits.append((c, c, c + ux * r, c + uy * r))
        for position, longueur in ((0.48, 0.30), (0.74, 0.22)):
            px, py = c + ux * r * position, c + uy * r * position
            for signe in (1, -1):
                b = a + signe * math.radians(50)
                traits.append((px, py, px + math.cos(b) * r * longueur, py - math.sin(b) * r * longueur))
    return traits


def svg(taille, rayon_rel, epaisseur_rel):
    lignes = "".join(
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>'
        for x1, y1, x2, y2 in segments(taille, rayon_rel)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {taille} {taille}">'
        f'<rect width="{taille}" height="{taille}" rx="{taille * 0.22:.1f}" fill="{FOND}"/>'
        f'<g stroke="{FLOCON}" stroke-width="{taille * epaisseur_rel:.2f}" stroke-linecap="round">{lignes}</g></svg>\n'
    )


def png(chemin, taille, rayon_rel, epaisseur_rel):
    from PIL import Image, ImageDraw

    sur = 4  # dessin 4 fois plus grand, puis réduit : bords lisses
    T = taille * sur
    img = Image.new("RGB", (T, T), FOND)
    d = ImageDraw.Draw(img)
    e = T * epaisseur_rel
    for x1, y1, x2, y2 in segments(T, rayon_rel):
        d.line((x1, y1, x2, y2), fill=FLOCON, width=round(e))
        for x, y in ((x1, y1), (x2, y2)):  # bouts arrondis
            d.ellipse((x - e / 2, y - e / 2, x + e / 2, y + e / 2), fill=FLOCON)
    img.resize((taille, taille), Image.LANCZOS).save(chemin, optimize=True)


def main(dossier):
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "icone.svg").write_text(svg(512, 0.36, 0.055), encoding="utf-8")
    for taille in (180, 192, 512):
        png(dossier / f"icone-{taille}.png", taille, 0.36, 0.055)
    # « maskable » : le flocon reste dans le cercle central (80 %) que certains appareils gardent
    png(dossier / "icone-512-maskable.png", 512, 0.28, 0.045)
    for f in sorted(dossier.iterdir()):
        print(f"{f.name} : {f.stat().st_size} octets")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icones")

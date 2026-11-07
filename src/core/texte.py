import re
import unicodedata


def cle(texte):
    """Forme de comparaison : sans accents, minuscules, mots séparés par _.

    « Sainte-Adèle » -> sainte_adele, « Prénom » -> prenom.
    """
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")


def cle_ville(texte):
    """Comme cle(), avec les abréviations courantes : « Ste-Adèle » = « Sainte-Adèle »."""
    c = cle(texte)
    c = re.sub(r"(^|_)ste(_|$)", r"\1sainte\2", c)
    c = re.sub(r"(^|_)st(_|$)", r"\1saint\2", c)
    return c

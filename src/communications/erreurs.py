"""Erreurs d'envoi communes aux fournisseurs (Twilio, serveur de courriel)."""


class Indisponible(Exception):
    """Fournisseur injoignable ou surchargé, rien n'est parti : on peut réessayer."""


class Refuse(Exception):
    """Le fournisseur refuse le message (destinataire invalide, compte bloqué...) : ne pas réessayer."""


class Incertain(Exception):
    """Pas de réponse après l'envoi de la demande : le message est peut-être parti. Ne pas réessayer (doublon)."""

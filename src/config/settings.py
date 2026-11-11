"""Réglages de LMAPP.

Tout ce qui varie d'un environnement à l'autre (prod, test) ou qui est secret
vient des variables d'environnement, fournies par /srv/lmapp/.env via Docker
Compose. Rien de propre à Louis ici : ça va dans la table Entreprise.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(nom, defaut=None):
    """Lit une variable d'environnement; erreur claire si elle manque."""
    valeur = os.environ.get(nom, defaut)
    if valeur is None:
        raise ImproperlyConfigured(f"Variable d'environnement manquante : {nom}")
    return valeur


def env_bool(nom, defaut=False):
    return env(nom, str(defaut)).strip().lower() in ("1", "true", "oui", "vrai")


def env_liste(nom, defaut=""):
    return [x.strip() for x in env(nom, defaut).split(",") if x.strip()]


# Environnement : "prod" ou "test". Sert aux garde-fous (envois réels, etc.).
LMAPP_ENV = env("LMAPP_ENV", "test")
# Hors prod, les seuls destinataires permis d'un envoi réel (cellulaires +1..., courriels de JF), séparés par des virgules
LMAPP_DESTINATAIRES_TEST = env_liste("LMAPP_DESTINATAIRES_TEST", "")

# Notifications sur le cellulaire (Web Push, PRD E8) : clés produites par `manage.py cles_vapid`
VAPID_CLE_PRIVEE = env("VAPID_CLE_PRIVEE", "")
VAPID_CLE_PUBLIQUE = env("VAPID_CLE_PUBLIQUE", "")
VAPID_SUJET = env("VAPID_SUJET", "https://ledeneigeur.com")

# Twilio (textos, PRD M1). Le numéro d'envoi est celui de l'entreprise (Entreprise.numero_texto).
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", "")
TWILIO_API = env("TWILIO_API", "https://api.twilio.com")
# Suivi de livraison : URL publique de /webhooks/twilio/statut/, seulement quand Twilio peut joindre ld1 (443 ouvert)
TWILIO_URL_STATUT = env("TWILIO_URL_STATUT", "")

# Courriel d'affaires (PRD E3, E5, C4) : serveur de JF, SMTP et IMAP en SSL. L'adresse d'envoi est
# celle de l'entreprise (Entreprise.courriel_reponse) et doit être le compte IMAP_UTILISATEUR.
SMTP_HOTE = env("SMTP_HOTE", "")
SMTP_PORT = int(env("SMTP_PORT", "465"))
IMAP_HOTE = env("IMAP_HOTE", "")
IMAP_PORT = int(env("IMAP_PORT", "993"))
IMAP_UTILISATEUR = env("IMAP_UTILISATEUR", "")
IMAP_MOT_DE_PASSE = env("IMAP_MOT_DE_PASSE", "")
IMAP_DOSSIER_ENVOYES = env("IMAP_DOSSIER_ENVOYES", "INBOX.Sent")
COURRIEL_HELO = env("COURRIEL_HELO", "ld1.ledeneigeur.com")  # nom donné au serveur de courriel (pas l'IP du conteneur)
# Boîte de la plateforme (info@, adresse du site Internet) : lue par le worker, demandes gardées dans
# l'administration et transférées à JF (core/boite_plateforme.py). Même serveur que les boîtes des déneigeurs.
PLATEFORME_IMAP_UTILISATEUR = env("PLATEFORME_IMAP_UTILISATEUR", "").lower()
PLATEFORME_IMAP_MOT_DE_PASSE = env("PLATEFORME_IMAP_MOT_DE_PASSE", "")
PLATEFORME_TRANSFERT_A = env("PLATEFORME_TRANSFERT_A", "")
# Lecture de la boîte (E5) : en prod seulement par défaut, pour que les vrais courriels des clients
# n'aillent jamais dans la base de test.
COURRIEL_LECTURE_ACTIVE = env_bool("COURRIEL_LECTURE_ACTIVE", LMAPP_ENV == "prod")
# Boîtes limitées à 2 Go : chaque courriel est archivé dans la base, puis effacé de la boîte (réception et
# envoyés) après ce nombre de jours. Négatif : on n'efface jamais.
COURRIEL_GARDER_JOURS = int(env("COURRIEL_GARDER_JOURS", "30"))

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_liste("DJANGO_ALLOWED_HOSTS")
# PRD Q6 : adresse neutre de l'administration (ex. admin.ledeneigeur.com). Vide : /admin/ sur tous les domaines.
LMAPP_HOTE_ADMIN = env("LMAPP_HOTE_ADMIN", "").strip().lower()
if LMAPP_HOTE_ADMIN and LMAPP_HOTE_ADMIN not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(LMAPP_HOTE_ADMIN)
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1")]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.postgres",
    "procrastinate.contrib.django",
    "core",
    "clients",
    "facturation",
    "tournee",
    "communications",
    "demandes",
    "terrain",
]

# IP des proxies dont on croit l'en-tête X-Forwarded-For : Caddy (projet edge),
# IP fixe sur le réseau Docker edge.
LMAPP_PROXIES_DE_CONFIANCE = env_liste("LMAPP_PROXIES_DE_CONFIANCE", "172.20.0.250")

MIDDLEWARE = [
    "core.middleware.IPReelleMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.EntrepriseMiddleware",
    "core.journal.JournalMiddleware",
    "core.middleware.AdminAdresseNeutreMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Avant les gabarits des apps : remplace admin/base_site.html de Django (bandeaux, thème de l'administration)
        "DIRS": [BASE_DIR / "gabarits_prioritaires"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.environnement",
                "core.context_processors.messages_non_lus",
                "core.context_processors.onglet",
            ],
            "builtins": ["core.templatetags.dates_qc"],  # filtre date_qc partout, sans {% load %}
        },
    },
]

# Base de données : PostgreSQL 17 + PostGIS, sur le réseau Docker interne.
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", "db"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Langue et heure
LANGUAGE_CODE = "fr-ca"
# Français seulement, quelle que soit la langue du téléphone (dates des écrans et des PDF)
LANGUAGES = [("fr-ca", "Français")]
TIME_ZONE = "America/Toronto"
USE_I18N = True
USE_TZ = True

# Fichiers statiques servis par WhiteNoise
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("LMAPP_MEDIA_ROOT", str(BASE_DIR / "media")))

# Sécurité. Caddy termine le HTTPS et transmet X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
# Session longue sur le cellulaire de Louis (K1) : 90 jours.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90

# Connexion des écrans de terrain
LOGIN_URL = "terrain:connexion"
LOGIN_REDIRECT_URL = "terrain:accueil"
LOGOUT_REDIRECT_URL = "terrain:connexion"

# Limitation des essais de connexion (core.connexions) : au-delà de ces nombres
# d'échecs dans la fenêtre, blocage temporaire de l'IP ou du nom d'utilisateur.
AUTHENTICATION_BACKENDS = ["core.connexions.AuthentificationLimitee"]
LMAPP_CONNEXION_MAX_IP = int(env("LMAPP_CONNEXION_MAX_IP", "10"))
LMAPP_CONNEXION_MAX_COMPTE = int(env("LMAPP_CONNEXION_MAX_COMPTE", "20"))
LMAPP_CONNEXION_FENETRE_MIN = int(env("LMAPP_CONNEXION_FENETRE_MIN", "15"))
# Prévisions d'Environnement Canada (I1) : API GeoMet
METEO_API = env("METEO_API", "https://api.weather.gc.ca")
# Coût mensuel d'un numéro Twilio (tableau de la plateforme, PRD Q) : 1,15 $ US le 8 novembre 2026
from decimal import Decimal as _D  # noqa: E402

LMAPP_COUT_NUMERO_TWILIO = _D(env("LMAPP_COUT_NUMERO_TWILIO", "1.15"))

# Facturation des entreprises par la plateforme (PRD Q2; prix de JF, 11 novembre 2026), taxes en sus
PLATEFORME_PRIX_ABONNEMENT = _D(env("PLATEFORME_PRIX_ABONNEMENT", "99.00"))  # par mois, un utilisateur compris
PLATEFORME_PRIX_UTILISATEUR = _D(env("PLATEFORME_PRIX_UTILISATEUR", "25.00"))  # par mois, administrateur ou opérateur de plus
PLATEFORME_PRIX_TEXTO = _D(env("PLATEFORME_PRIX_TEXTO", "0.03"))  # envoyé ou reçu; courriels et lecture seule gratuits
PLATEFORME_NOM_LEGAL = env("PLATEFORME_NOM_LEGAL", "SLAPP Technologies Inc.")
PLATEFORME_ADRESSE = env("PLATEFORME_ADRESSE", "204, rue Saint-Charles, bureau 103|Sainte-Thérèse (Québec)  J7E 2B4")  # lignes séparées par « | »
PLATEFORME_TELEPHONE = env("PLATEFORME_TELEPHONE", "514 360-3227")
PLATEFORME_COURRIEL = env("PLATEFORME_COURRIEL", "info@ledeneigeur.com")
PLATEFORME_NUMERO_TPS = env("PLATEFORME_NUMERO_TPS", "")
PLATEFORME_NUMERO_TVQ = env("PLATEFORME_NUMERO_TVQ", "")
PLATEFORME_TAUX_TPS = _D(env("PLATEFORME_TAUX_TPS", "5"))
PLATEFORME_TAUX_TVQ = _D(env("PLATEFORME_TAUX_TVQ", "9.975"))
PLATEFORME_JOURS_PAIEMENT = int(env("PLATEFORME_JOURS_PAIEMENT", "15"))
PLATEFORME_PAIEMENT = env("PLATEFORME_PAIEMENT", "")  # instructions de paiement imprimées sur la facture
# Surveillance (PRD 6.7) : à qui les alertes, et seuils
LMAPP_ALERTES_TEXTO = env("LMAPP_ALERTES_TEXTO", "")
LMAPP_ALERTES_TEXTO_DE = env("LMAPP_ALERTES_TEXTO_DE", "")
LMAPP_ALERTES_COURRIEL = env("LMAPP_ALERTES_COURRIEL", "")
LMAPP_SURVEILLANCE_HOTES = env_liste("LMAPP_SURVEILLANCE_HOTES", "")
LMAPP_DISQUE_SEUIL = int(env("LMAPP_DISQUE_SEUIL", "70"))
LMAPP_SAUVEGARDE_TEMOIN = env("LMAPP_SAUVEGARDE_TEMOIN", "/sauvegardes/derniere_reussite")
LMAPP_SILENCE_FICHIER = env("LMAPP_SILENCE_FICHIER", "/etat/silence_jusqu_a")  # outils/silence.sh
# Journal des actions (K4) : durée de conservation, en jours
LMAPP_JOURNAL_JOURS = int(env("LMAPP_JOURNAL_JOURS", "730"))
# Durées de conservation (Loi 25), écrites aussi dans la politique de confidentialité du site (site/confidentialite.html) :
# positions GPS du véhicule pendant les tournées, et demandes reçues à info@ (clients potentiels). Décision de JF, 9 novembre 2026.
LMAPP_POSITIONS_JOURS = int(env("LMAPP_POSITIONS_JOURS", "120"))
LMAPP_DEMANDES_SITE_JOURS = int(env("LMAPP_DEMANDES_SITE_JOURS", "730"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    # WeasyPrint et fontTools racontent chaque étape d'un PDF : seulement les problèmes
    "loggers": {n: {"level": "WARNING"} for n in ("weasyprint", "fontTools")},
}

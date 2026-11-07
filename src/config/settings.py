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

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_liste("DJANGO_ALLOWED_HOSTS")
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
    "procrastinate.contrib.django",
    "core",
    "clients",
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
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.environnement",
            ],
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
LANGUAGES = [("fr", "Français"), ("en", "English")]
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

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
}

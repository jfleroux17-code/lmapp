# Image unique de LMAPP : sert au service « app » (Gunicorn) et au service
# « worker » (Procrastinate). Seule la commande change, dans compose.yaml.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Toronto \
    XDG_CACHE_HOME=/tmp/.cache

# Bibliothèques système :
#  - gdal-bin : GDAL, GEOS et PROJ pour GeoDjango et PostGIS
#  - pango, harfbuzz : rendu des PDF par WeasyPrint
#  - polices : accents corrects dans les PDF
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gdal-bin \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
      fonts-dejavu-core fonts-liberation2 \
      tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -f

# Utilisateur sans privilèges. UID 1000 = deploy sur ld1, pour que les
# fichiers écrits dans les volumes (photos, PDF) lui appartiennent.
RUN groupadd --gid 1000 lmapp \
 && useradd --uid 1000 --gid lmapp --home-dir /app --shell /usr/sbin/nologin lmapp

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --root-user-action=ignore -r /tmp/requirements.txt

COPY --chown=lmapp:lmapp src/ /app/

# Fichiers statiques rassemblés à la construction. Les valeurs ci-dessous
# servent seulement à cette commande : les vraies viennent du .env au démarrage.
RUN DJANGO_SECRET_KEY=construction-seulement DJANGO_ALLOWED_HOSTS=localhost \
    POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x \
    python manage.py collectstatic --noinput \
 && mkdir -p /app/media && chown -R lmapp:lmapp /app/staticfiles /app/media

USER lmapp

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--forwarded-allow-ips", "*"]

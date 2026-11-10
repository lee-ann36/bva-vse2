# Build: installeer de Python-pakketten in een aparte laag
FROM python:3.14-slim-bookworm AS builder

RUN apt-get update --yes --quiet && apt-get install --yes --quiet --no-install-recommends \
    build-essential \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libwebp-dev \
 && rm -rf /var/lib/apt/lists/* \
 && python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt


# Runtime: kleine image met alleen wat nodig is
FROM python:3.14-slim-bookworm AS runtime

RUN apt-get update --yes --quiet && apt-get install --yes --quiet --no-install-recommends \
    libjpeg62-turbo \
    libwebp7 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd wagtail

EXPOSE 8000
ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DJANGO_SETTINGS_MODULE=bvesite.settings.production \
    DATA_DIR=/data \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
RUN mkdir -p /data/media && chown -R wagtail:wagtail /app /data
COPY --chown=wagtail:wagtail . .
USER wagtail

# Statische bestanden verzamelen (SECRET_KEY is hier alleen een tijdelijke dummy)
RUN SECRET_KEY=alleen-voor-build ALLOWED_HOSTS=localhost python manage.py collectstatic --noinput --clear

# Bij elke start: database bijwerken, dan de webserver.
# 1 worker met threads, zodat de inlog-blokkade (in het geheugen) voor alle verzoeken geldt.
CMD set -xe; mkdir -p "$DATA_DIR/media"; python manage.py migrate --noinput; \
    exec gunicorn bvesite.wsgi:application --bind "0.0.0.0:$PORT" --workers 1 --threads 8 --timeout 60 \
    --access-logfile -

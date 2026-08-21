# Why multi-stage:
#   The build stage needs compilers/build tools for some Python packages.
#   Shipping those in the final image bloats it and widens the attack surface
#   for no runtime benefit. The final stage copies only the installed
#   packages + app code, not the build toolchain.

FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# app/preprocessing/text_helpers.py and email_preprocessor.py import
# nltk.corpus.stopwords at module load time -- the corpus is data, not
# part of the nltk package, and must be fetched separately or the app
# crashes on startup with a LookupError. Downloaded to a fixed path here
# (not $HOME, which differs between the builder's root user and the
# runtime image's appuser) and copied into one of NLTK's default search
# paths in the runtime stage below.
RUN python -m nltk.downloader -d /build/nltk_data stopwords


FROM python:3.11-slim AS runtime

# Why a non-root user:
#   Running as root inside a container means a container-escape vulnerability
#   hands the attacker root on the host's container runtime. Non-root is a
#   near-zero-cost mitigation.
#
# Force UID 1000 to cleanly map permissions across build environments.
RUN useradd --create-home --uid 1000 --shell /bin/bash appuser

WORKDIR /app

# Ensure target directories exist and use raw numeric UIDs (1000:1000) 
# to guarantee Docker's layer system doesn't hit text translation mismatches.
RUN mkdir -p /home/appuser/.local && chown -R 1000:1000 /home/appuser
COPY --from=builder --chown=1000:1000 /root/.local /home/appuser/.local

COPY --from=builder /build/nltk_data /usr/local/share/nltk_data
COPY ./app ./app

# alembic.ini and alembic/ are needed to run migrations from inside the
# container (`alembic upgrade head`). The image previously shipped the
# alembic package itself but never these two -- `docker compose exec api
# alembic upgrade head` (see README) and any Kubernetes migration Job would
# fail with "FileNotFoundError: alembic.ini" despite the binary being present.
COPY ./alembic.ini ./alembic.ini
COPY ./alembic ./alembic

ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN chown -R 1000:1000 /app
USER appuser

EXPOSE 8000

# Why a HEALTHCHECK at the image level:
#   Lets `docker ps` and orchestrators see container health without any
#   external monitoring wired up yet — a cheap first line of defense.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

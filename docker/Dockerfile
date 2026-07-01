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


FROM python:3.11-slim AS runtime

# Why a non-root user:
#   Running as root inside a container means a container-escape vulnerability
#   hands the attacker root on the host's container runtime. Non-root is a
#   near-zero-cost mitigation.
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /root/.local /home/appuser/.local
COPY ./app ./app

ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Why a HEALTHCHECK at the image level:
#   Lets `docker ps` and orchestrators see container health without any
#   external monitoring wired up yet — a cheap first line of defense.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

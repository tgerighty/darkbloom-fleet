FROM python:3.12-slim

# openssh-client: this service pulls its own data over SSH from the managed
# host (daemon state + earnings ledger). No key material is baked in — see
# docker-compose.yml, which mounts one at deploy time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fleet/ ./fleet/

USER appuser
ENV HOME=/home/appuser

EXPOSE 8080
CMD ["python", "-m", "fleet.main"]

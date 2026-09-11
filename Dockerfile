FROM python:3.12-slim

# openssh-client: this service pulls its own data over SSH from the managed
# hosts (daemon state + earnings ledger). No key material is baked in: the
# key arrives as a mounted file (docker-compose.yml) or a Swarm secret
# (deploy/stack.yml).
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fleet/ ./fleet/

USER appuser
ENV HOME=/home/appuser

EXPOSE 8080
CMD ["python", "-m", "fleet.main"]

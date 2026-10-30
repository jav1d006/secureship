# ---- tools stage: everything that needs curl / pip downloads; none of it ships in the final image
FROM python:3.12-slim AS tools
ARG GITLEAKS_VERSION=8.28.0
ARG GITLEAKS_SHA256=a65b5253807a68ac0cafa4414031fd740aeb55f54fb7e55f386acb52e6a840eb
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tar \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
       -o /tmp/gitleaks.tar.gz \
    && echo "${GITLEAKS_SHA256}  /tmp/gitleaks.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks
# Semgrep rules are fetched at build time (refreshed on every rebuild) so scans run fully offline.
RUN mkdir -p /opt/semgrep-rules \
    && curl -fsSL https://semgrep.dev/c/p/default -o /opt/semgrep-rules/default.yml \
    && curl -fsSL https://semgrep.dev/c/p/owasp-top-ten -o /opt/semgrep-rules/owasp-top-ten.yml
# Heavy Python tools live in their own virtualenvs so their dependencies never clash with the API's.
COPY requirements-semgrep.txt requirements-checkov.txt ./
RUN python -m venv /opt/semgrep && /opt/semgrep/bin/pip install --no-cache-dir -r requirements-semgrep.txt \
    && python -m venv /opt/checkov && /opt/checkov/bin/pip install --no-cache-dir -r requirements-checkov.txt
COPY --from=aquasec/trivy:0.58.0 /usr/local/bin/trivy /usr/local/bin/trivy
RUN trivy image --download-db-only --cache-dir /opt/trivy-cache \
    && chmod -R a+rX /opt

# ---- runtime stage
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /srv
RUN apt-get update \
    && apt-get install -y --no-install-recommends shellcheck \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY --from=tools /usr/local/bin/gitleaks /usr/local/bin/trivy /usr/local/bin/
COPY --from=tools /opt /opt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
 && mkdir /data && chown 10001:10001 /data
USER 10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

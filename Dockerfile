FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps + kubectl (match container arch)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
      amd64)  karch="amd64" ;; \
      arm64)  karch="arm64" ;; \
      *) echo "Unsupported architecture: ${arch}" >&2; exit 1 ;; \
    esac; \
    ver="$(curl -fsSL https://dl.k8s.io/release/stable.txt)"; \
    curl -fsSL "https://dl.k8s.io/release/${ver}/bin/linux/${karch}/kubectl" -o /usr/local/bin/kubectl; \
    chmod +x /usr/local/bin/kubectl; \
    kubectl version --client=true

# Copy project files needed for packaging
COPY pyproject.toml README.md /app/
COPY api /app/api

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

COPY . /app

EXPOSE 8000

CMD ["python", "api/manage.py", "runserver", "0.0.0.0:8000"]

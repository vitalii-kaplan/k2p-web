FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps + Docker CLI (no k8s needed)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
      > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && command -v docker >/dev/null 2>&1 \
    && rm -rf /var/lib/apt/lists/*

# Copy project files needed for packaging
COPY pyproject.toml README.md /app/
COPY api /app/api

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

COPY . /app

EXPOSE 8000

CMD ["python", "api/manage.py", "runserver", "0.0.0.0:8000"]

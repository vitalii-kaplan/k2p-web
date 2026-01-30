FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy project files needed for packaging
COPY pyproject.toml README.md /app/
COPY api /app/api

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

COPY . /app

EXPOSE 8000

CMD ["python", "api/manage.py", "runserver", "0.0.0.0:8000"]

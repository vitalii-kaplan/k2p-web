k2p-web/
  README.md
  LICENSE
  .gitignore
  .editorconfig
  .env.example

  pyproject.toml
  poetry.lock                     # optional at start (or omit until you lock deps)
  Makefile

  api/
    manage.py
    k2pweb/
      __init__.py
      asgi.py
      wsgi.py
      urls.py
      settings.py                  # Django settings (env-based)

    apps/
      core/
        __init__.py
        admin.py
        apps.py
        models.py
        health.py                  # /healthz
      jobs/
        __init__.py
        admin.py
        apps.py
        models.py                  # Job model, status, storage keys, error fields
        serializers.py
        views.py                   # POST /api/jobs, GET /api/jobs/{id}, GET result
        urls.py
        runner.py                  # Docker runner (calls knime2py image)
      authz/
        __init__.py
        rate_limit.py              # IP hash + token bucket (placeholder)

    templates/
      ui/
        index.html                 # one-page UI (placeholder)

    static/
      ui/
        app.js                     # folder select → manifest → zip → upload → poll
        styles.css                 # optional

    tests/
      test_jobs_api.py
      test_zip_validator.py
      test_worker_logs.py

  deploy/
    nginx/
      nginx.conf                   # reverse proxy + auth

  scripts/
    migrate.sh
    superuser.sh

  .github/
    workflows/
      ci.yml                       # lint + tests
      build-api-image.yml
      build-runner-image.yml
      deploy-dev.yml               # optional

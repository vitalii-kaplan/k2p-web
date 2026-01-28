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
      settings/
        __init__.py
        base.py
        local.py
        prod.py
      logging.py                   # structured logging config (placeholder)

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
        services/
          __init__.py
          storage.py               # MinIO/S3 client wrapper
          zip_validate.py          # server-side ZIP validator (strict)
          k8s.py                   # create/read Jobs in cluster
          runner_contract.py       # constants: image, args, output names, caps
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
      test_k8s_job_spec.py

  runner/
    Dockerfile                     # builds a runner image (FROM knime2py image)
    runner.py                      # download input, run k2p, upload result
    requirements.txt               # minimal (requests / boto3) if needed

  deploy/
    k8s/
      base/
        namespace.yaml
        configmap-api.yaml
        secret-api.example.yaml    # template only, no real secrets
        postgres.yaml              # for dev clusters; prod likely managed DB
        minio.yaml                 # for dev clusters; prod likely real S3
        api-deployment.yaml
        api-service.yaml
        api-ingress.yaml
        api-serviceaccount.yaml
        api-rbac.yaml              # permissions to create Jobs
        networkpolicy-api.yaml
        networkpolicy-runner.yaml
      jobs/
        runner-job-template.yaml   # a Job manifest template (placeholders)
      overlays/
        dev/
          kustomization.yaml
          patches.yaml
        prod/
          kustomization.yaml
          patches.yaml

  scripts/
    kind-create.sh                 # local k8s
    kind-load-images.sh            # load api/runner images into kind
    migrate.sh
    superuser.sh

  .github/
    workflows/
      ci.yml                       # lint + tests
      build-api-image.yml
      build-runner-image.yml
      deploy-dev.yml               # optional

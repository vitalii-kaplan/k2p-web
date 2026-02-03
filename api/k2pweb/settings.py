from __future__ import annotations

import os
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent  # .../api
REPO_ROOT = Path(os.environ.get("REPO_ROOT", str(API_DIR.parent))).resolve()

# Optional .env loading for local dev
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

BASE_DIR = API_DIR


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    v = os.environ.get(name)
    if v is None:
        return default or []
    return [x.strip() for x in v.split(",") if x.strip()]


def resolve_under_repo(p: str) -> Path:
    path = Path(p)
    return (REPO_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


# -----------------------------------------------------------------------------
# Core settings
# -----------------------------------------------------------------------------

IS_PYTEST = "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules

# Prefer DJANGO_DEBUG; accept DEBUG for backwards compatibility
DEBUG = env_bool("DJANGO_DEBUG", env_bool("DEBUG", False)) or IS_PYTEST

# Prefer DJANGO_SECRET_KEY; accept SECRET_KEY for backwards compatibility
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("SECRET_KEY") or ""
if not SECRET_KEY:
    if IS_PYTEST or DEBUG:
        SECRET_KEY = "dev-secret-key"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY (or SECRET_KEY) must be set in production.")

# Prefer DJANGO_ALLOWED_HOSTS; accept ALLOWED_HOSTS for backwards compatibility
ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    env_list("ALLOWED_HOSTS", ["127.0.0.1", "localhost"] if DEBUG else []),
)

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", [])

ROOT_URLCONF = "k2pweb.urls"
WSGI_APPLICATION = "k2pweb.wsgi.application"

INSTALLED_APPS = [
    "django_prometheus",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.jobs",
]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "rest_framework.schemas.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "k2pweb.middleware.ApiCsrfExemptMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "k2p.api": {"handlers": ["console"], "level": "INFO"},
        "k2p.worker": {"handlers": ["console"], "level": "INFO"},
    },
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------

DB_ENGINE = os.environ.get("DB_ENGINE", "sqlite").strip().lower()
if IS_PYTEST:
    # Keep tests self-contained and avoid relying on external DB hosts from .env.
    DB_ENGINE = "sqlite"

if DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "k2pweb"),
            "USER": os.environ.get("DB_USER", "k2pweb"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    sqlite_path = resolve_under_repo(os.environ.get("SQLITE_PATH", "var/db.sqlite3"))
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(sqlite_path),
            # Reduce "database is locked" errors under concurrent access.
            "OPTIONS": {"timeout": 30},
        }
    }

# -----------------------------------------------------------------------------
# Static / storage
# -----------------------------------------------------------------------------

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

# If you don't use MEDIA at all, you can remove these.
# Keep them under repo root, not under api/.
MEDIA_URL = "/media/"
MEDIA_ROOT = resolve_under_repo(os.environ.get("MEDIA_ROOT", "var/media"))
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

JOB_STORAGE_ROOT = resolve_under_repo(os.environ.get("JOB_STORAGE_ROOT", "var/jobs"))
RESULT_STORAGE_ROOT = resolve_under_repo(os.environ.get("RESULT_STORAGE_ROOT", "var/results"))
JOB_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
RESULT_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": str(JOB_STORAGE_ROOT)},
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# -----------------------------------------------------------------------------
# Worker / K8s
# -----------------------------------------------------------------------------

K8S_NAMESPACE = os.environ.get("K8S_NAMESPACE", "k2p")
K2P_IMAGE = os.environ.get("K2P_IMAGE", "ghcr.io/vitalii-kaplan/knime2py:main")
MAX_QUEUED_JOBS = int(os.environ.get("MAX_QUEUED_JOBS", "50"))

# Expose as strings too (some code may expect str)
JOB_STORAGE_ROOT_STR = str(JOB_STORAGE_ROOT)
RESULT_STORAGE_ROOT_STR = str(RESULT_STORAGE_ROOT)
REPO_ROOT_STR = str(REPO_ROOT)

# -----------------------------------------------------------------------------
# i18n / tz / misc
# -----------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

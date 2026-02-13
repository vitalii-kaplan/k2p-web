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


def env_str(name: str, default: str | None = None) -> str:
    v = os.environ.get(name)
    if v is None:
        return default if default is not None else ""
    return v


def env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


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
# Expose /readyz only in debug or when explicitly enabled.
EXPOSE_READYZ = env_bool("EXPOSE_READYZ", False)
# Expose /api/schema/ only in debug or when explicitly enabled.
EXPOSE_SCHEMA = env_bool("EXPOSE_SCHEMA", False)

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
_repo_static = REPO_ROOT / "static"
if _repo_static.exists() and _repo_static not in STATICFILES_DIRS:
    STATICFILES_DIRS.append(_repo_static)
STATIC_ROOT = str(resolve_under_repo(os.environ.get("STATIC_ROOT", "var/static")))

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
MAX_QUEUED_JOBS = int(os.environ.get("MAX_QUEUED_JOBS", "50"))

# Runner configuration (local Docker runner)
JOB_RUNNER_BACKEND = env_str("JOB_RUNNER_BACKEND", "docker")
K2P_IMAGE = env_str("K2P_IMAGE", "ghcr.io/vitalii-kaplan/knime2py:main")
K2P_TIMEOUT_SECS = env_int("K2P_TIMEOUT_SECS", 300)
K2P_CPU = env_str("K2P_CPU", "1.0")
K2P_MEMORY = env_str("K2P_MEMORY", "1g")
K2P_PIDS_LIMIT = env_str("K2P_PIDS_LIMIT", "256")
K2P_COMMAND = env_str("K2P_COMMAND", "")
K2P_ARGS_TEMPLATE = env_str("K2P_ARGS_TEMPLATE", "")
DOCKER_BIN = env_str("DOCKER_BIN", "docker")
HOST_REPO_ROOT = env_str("HOST_REPO_ROOT", "")
HOST_JOB_STORAGE_ROOT = env_str("HOST_JOB_STORAGE_ROOT", "")
HOST_RESULT_STORAGE_ROOT = env_str("HOST_RESULT_STORAGE_ROOT", "")

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

# -----------------------------------------------------------------------------
# Security (controlled via env; enable in production compose)
# -----------------------------------------------------------------------------

SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)

# Django matches these regexes against request.path.lstrip("/")
# i.e. "healthz", not "/healthz"
_raw_exempt = env_list("SECURE_REDIRECT_EXEMPT", [])

def _sanitize_exempt_pattern(p: str) -> str:
    p = p.strip()
    if p.startswith("^/"):
        # common mistake: "^/healthz$" -> "^healthz$"
        p = "^" + p[2:]
    elif p.startswith("/"):
        # common mistake: "/healthz" -> "healthz"
        p = p[1:]
    return p

SECURE_REDIRECT_EXEMPT = [_sanitize_exempt_pattern(p) for p in _raw_exempt if p.strip()]

SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)

if env_bool("USE_X_FORWARDED_PROTO", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

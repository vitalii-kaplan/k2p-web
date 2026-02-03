from django.apps import AppConfig


class JobsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.jobs"

    def ready(self) -> None:
        from .metrics_api import register_jobs_db_metrics_collector

        register_jobs_db_metrics_collector()

from django.db import migrations, models


def copy_job_status(apps, schema_editor):
    JobSettingsMeta = apps.get_model("jobs", "JobSettingsMeta")
    for meta in JobSettingsMeta.objects.select_related("job").all():
        status = ""
        try:
            status = meta.job.status
        except Exception:
            status = "QUEUED"
        if not status:
            status = "QUEUED"
        meta.job_status = status
        meta.save(update_fields=["job_status"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0004_reset_jobsettingsmeta"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobsettingsmeta",
            name="job_status",
            field=models.CharField(
                choices=[
                    ("QUEUED", "Queued"),
                    ("RUNNING", "Running"),
                    ("SUCCEEDED", "Succeeded"),
                    ("FAILED", "Failed"),
                ],
                default="QUEUED",
                max_length=16,
            ),
        ),
        migrations.RunPython(copy_job_status, noop_reverse),
        migrations.RemoveField(
            model_name="jobsettingsmeta",
            name="job",
        ),
    ]

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0003_jobsettingsmeta"),
    ]

    operations = [
        migrations.DeleteModel(name="JobSettingsMeta"),
        migrations.CreateModel(
            name="JobSettingsMeta",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("file_name", models.CharField(max_length=512)),
                ("factory", models.CharField(blank=True, max_length=512, null=True)),
                ("node_name", models.CharField(blank=True, max_length=255, null=True)),
                ("name", models.CharField(blank=True, max_length=255, null=True)),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="settings_meta",
                        to="jobs.job",
                    ),
                ),
            ],
        ),
    ]

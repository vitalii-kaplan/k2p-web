import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0005_jobsettingsmeta_job_status"),
    ]

    operations = [
        migrations.RenameField(
            model_name="job",
            old_name="id",
            new_name="uuid",
        ),
        migrations.AlterField(
            model_name="job",
            name="uuid",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True),
        ),
        migrations.AddField(
            model_name="job",
            name="id",
            field=models.BigAutoField(primary_key=True, serialize=False),
        ),
    ]

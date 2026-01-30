from django.contrib import admin

from .models import Job, JobSettingsMeta


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "created_at", "started_at", "finished_at")
    list_filter = ("status",)
    search_fields = ("id", "k8s_job_name", "original_filename")


@admin.register(JobSettingsMeta)
class JobSettingsMetaAdmin(admin.ModelAdmin):
    list_display = ("id", "job", "file_name", "factory", "node_name", "name", "created_at")
    list_filter = ("created_at",)
    search_fields = ("file_name", "factory", "node_name", "name", "job__id")

# Register your models here.

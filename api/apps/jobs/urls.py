from django.urls import path
from .views import JobsCreateView, JobDetailView, JobLogsView, JobResultZipView

urlpatterns = [
    path("jobs", JobsCreateView.as_view(), name="jobs-create"),
    path("jobs/<uuid:job_id>", JobDetailView.as_view(), name="jobs-detail"),
    path("jobs/<uuid:job_id>/logs", JobLogsView.as_view(), name="jobs-logs"),
    path("jobs/<uuid:job_id>/result.zip", JobResultZipView.as_view(), name="jobs-result-zip"),
]

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Job
from .serializers import JobCreateSerializer, JobSerializer


class JobsCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        ser = JobCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response(
                {"error": {"code": "invalid_request", "message": "Invalid input.", "details": ser.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job = ser.save()
        return Response(JobSerializer(job).data, status=status.HTTP_201_CREATED)


class JobDetailView(APIView):
    def get(self, request, job_id):
        job = get_object_or_404(Job, id=job_id)
        return Response(JobSerializer(job).data, status=status.HTTP_200_OK)


class JobResultZipView(APIView):
    """
    Download job results as a ZIP archive.

    GET /api/jobs/<uuid>/result.zip
    """

    def get(self, request, job_id):
        job = get_object_or_404(Job, id=job_id)

        if job.status != Job.Status.SUCCEEDED:
            return Response(
                {
                    "error": {
                        "code": "job_not_ready",
                        "message": "Job is not finished yet.",
                        "details": {"status": job.status},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Resolve results directory (prefer result_key if stored; else default layout)
        if getattr(job, "result_key", ""):
            results_dir = Path(settings.RESULT_STORAGE_ROOT) / job.result_key
        else:
            results_dir = Path(settings.RESULT_STORAGE_ROOT) / f"jobs/{job.id}"

        results_dir = results_dir.resolve()
        root = Path(settings.RESULT_STORAGE_ROOT).resolve()

        # Safety: ensure results_dir stays under RESULT_STORAGE_ROOT
        if results_dir != root and root not in results_dir.parents:
            return Response(
                {"error": {"code": "general_failure", "message": "Invalid results path."}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not results_dir.exists() or not results_dir.is_dir():
            return Response(
                {"error": {"code": "missing_results", "message": "Results directory does not exist."}},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Build ZIP in a spooled temp file (spills to disk if large)
        tmp = tempfile.SpooledTemporaryFile(max_size=50 * 1024 * 1024, mode="w+b")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in results_dir.rglob("*"):
                if p.is_file():
                    arc = p.relative_to(results_dir).as_posix()
                    zf.write(p, arcname=arc)

        tmp.seek(0)

        filename = f"{job.id}.zip"
        return FileResponse(tmp, as_attachment=True, filename=filename, content_type="application/zip")

from __future__ import annotations

import csv
import io
import re
from typing import Any

from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


READ_ONLY_PREFIX = re.compile(r"^\s*(select|with|show)\b", re.IGNORECASE)
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|alter|drop|truncate|create|replace|grant|revoke|comment|vacuum|analyze)\b",
    re.IGNORECASE,
)
ADMIN_TABLES = re.compile(r"\b(django_|auth_|admin_|contenttypes_|sessions_)", re.IGNORECASE)


@staff_member_required
def sql_console(request: HttpRequest) -> HttpResponse:
    if not request.user.is_superuser:
        return HttpResponse(status=403)

    query = ""
    error = ""
    columns: list[str] = []
    rows: list[list[Any]] = []

    if request.method == "POST":
        query = (request.POST.get("query") or "").strip()
        if not query:
            error = "Query is required."
        elif not READ_ONLY_PREFIX.match(query) or FORBIDDEN.search(query):
            error = "Only read-only SELECT/CTE queries are allowed."
        elif ADMIN_TABLES.search(query):
            error = "Admin/auth/system tables are not allowed in this console."
        else:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(query)
                    columns = [c[0] for c in cursor.description or []]
                    rows = [list(r) for r in cursor.fetchall()]
            except Exception as exc:  # noqa: BLE001
                error = str(exc)

        if "download" in request.POST and not error:
            return _csv_response(query, columns, rows)

    return render(
        request,
        "admin/sql_console.html",
        {
            "query": query,
            "error": error,
            "columns": columns,
            "rows": rows,
        },
    )


def _csv_response(query: str, columns: list[str], rows: list[list[Any]]) -> HttpResponse:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    writer.writerows(rows)
    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = "attachment; filename=sql_export.csv"
    return resp

from __future__ import annotations


class ApiCsrfExemptMiddleware:
    """
    Disable CSRF checks for /api/* endpoints while keeping CSRF for admin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/"):
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)

from django.shortcuts import redirect
from django.views.decorators.http import require_GET

@require_GET
def api_root_redirect(request):
    """
    Redirect from /api/ to /api/docs/ for better user experience.
    This ensures users landing on the API root are directed to the documentation.
    """
    return redirect('/api/docs/')

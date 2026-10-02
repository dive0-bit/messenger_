from django.conf import settings
from django.http import HttpResponse, HttpResponseNotFound


def frontend(request, path=''):
    """
    Send the web page for every url that is not an API / admin / media url.
    The javascript reads the address in the browser (for example
    /reset-password/<uid>/<token>) and shows the right form, so the server always
    answers with the same index.html.
    """
    index_file = settings.FRONTEND_DIST / 'index.html'

    if not index_file.exists():
        return HttpResponseNotFound(
            'Web page files not found (backend/ui/index.html).'
        )

    return HttpResponse(index_file.read_text(encoding='utf-8'), content_type='text/html')

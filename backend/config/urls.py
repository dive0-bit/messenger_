from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('chats.urls')),

    # Uploaded profile pictures. Django serves them itself, which is fine for a small
    # project (a big project would use cloud storage such as S3).
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),

    # Everything else is the web page. This line must stay LAST.
    re_path(r'^(?!api/|admin/|static/|media/|ws/|favicon\.ico).*$', views.frontend),
]

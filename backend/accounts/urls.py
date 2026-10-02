from django.urls import path

from . import views

# All these urls start with /api/auth/ (see config/urls.py)
urlpatterns = [
    path('me/', views.current_user),
    path('register/', views.register_user),
    path('login/', views.login_user),
    path('logout/', views.logout_user),
    path('profile/', views.update_profile),
    path('password-reset/', views.password_reset_request),
    path('password-reset-confirm/', views.password_reset_confirm),
]

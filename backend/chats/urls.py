from django.urls import path

from . import views

# All these urls start with /api/ (see config/urls.py)
urlpatterns = [
    path('conversations/', views.conversation_list),
    path('conversations/add/', views.add_conversation),
    path('conversations/<int:conversation_id>/', views.conversation_delete),
    path('conversations/<int:conversation_id>/messages/', views.conversation_messages),
]

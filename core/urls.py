from django.urls import path
from . import views
from . import profile_views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('api/profiles/<str:handle>/analytics/', profile_views.public_analytics, name='profile_analytics_api'),
    path('api/profiles/<str:handle>/weaknesses/', profile_views.public_analytics, {'section': 'weaknesses'}),
    path('api/profiles/<str:handle>/practice/', profile_views.public_analytics, {'section': 'practice'}),
    path('api/extension/auth/start/', profile_views.connection_start),
    path('api/extension/auth/exchange/', profile_views.connection_exchange),
    path('api/extension/auth/refresh/', profile_views.connection_refresh),
    path('api/extension/auth/status/', profile_views.connection_status),
    path('api/extension/auth/revoke/', profile_views.connection_revoke),
    path('api/extension/notes/', profile_views.extension_notes),
    path('api/extension/notes/<int:note_id>/', profile_views.extension_notes),
    path('api/extension/improvement-plan/', profile_views.extension_plan),
    path('api/notes/', profile_views.website_notes_api),
    path('api/notes/<int:note_id>/', profile_views.website_notes_api),
    path('api/improvement-plan/', profile_views.website_plan, name='improvement_plan_api'),
    path('notes/', profile_views.notes_page, name='notes'),
    path('extension/authorize/<uuid:request_id>/', profile_views.authorize, name='extension_authorize'),
    path('extension/connections/', profile_views.connections_page, name='extension_connections'),
    path('register/', views.register_view, name='register'),
    path('profile/update/', views.update_profile_view, name='update_profile'),
    path('logout/', views.logout_view, name='logout'),
    
    # New Split Architecture
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    
    path('ai-review/', views.ai_code_review_view, name='ai_review'),
    # Preserve old bookmarks while retiring the separate website tool.
    path('weak-spot/', views.retired_weak_spot, name='weak_spot'),
]

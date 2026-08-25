from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('register/', views.register_view, name='register'),
    path('profile/update/', views.update_profile_view, name='update_profile'),
    path('logout/', views.logout_view, name='logout'),
    
    # New Split Architecture
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    
    # The 3 Tools
    path('ai-review/', views.ai_code_review_view, name='ai_review'),
    path('compare/', views.compare_view, name='compare'),
    path('weak-spot/', views.weak_spot_view, name='weak_spot'),
]
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

class CustomUserAdmin(UserAdmin):
    # 1. This adds the handle as a column on the main list of all users
    list_display = ('username', 'email', 'codeforces_handle', 'is_staff')
    
    # 2. This adds a new section on the actual edit page so you can change it
    fieldsets = UserAdmin.fieldsets + (
        ('Algolytics Profile Data', {
            'fields': ('codeforces_handle',),
        }),
    )

# Register the model with these new custom admin settings
admin.site.register(CustomUser, CustomUserAdmin)
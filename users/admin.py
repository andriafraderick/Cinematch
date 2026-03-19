from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from users.models import User, UserProfile


class UserAdmin(BaseUserAdmin):
    # Override list_display to use our fields
    list_display = ['email', 'username', 'full_name', 'is_staff', 'is_active', 'date_joined']
    list_filter = ['is_staff', 'is_active', 'is_onboarded']
    search_fields = ['email', 'username', 'full_name']
    ordering = ['-date_joined']

    # Override fieldsets to remove first_name/last_name
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('username', 'full_name', 'avatar')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_onboarded', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'last_seen')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )


admin.site.register(User, UserAdmin)
admin.site.register(UserProfile)
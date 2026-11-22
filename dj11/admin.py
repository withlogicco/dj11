from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext as _

from dj11.models import User


@admin.register(User)
class DjUserAdmin(UserAdmin):
    model = User
    list_display = (
        "email",
        "created_at",
        "email_verified_at",
        "is_staff",
        "is_active",
        "is_superuser",
    )
    list_filter = (
        "email_verified_at",
        "is_active",
        "is_staff",
        "is_superuser",
    )
    fieldsets = (
        (None, {"fields": ("email", "password", "email_verified_at")}),
        (
            _("Personal info"),
            {"fields": ("first_name", "last_name")},
        ),
        ("Permissions", {"fields": ("is_staff", "is_active", "is_superuser")}),
        (
            "Group Permissions",
            {
                "fields": (
                    "groups",
                    "user_permissions",
                )
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_active",
                    "is_superuser",
                ),
            },
        ),
    )
    search_fields = ("email",)
    ordering = ("-created_at",)

"""
============================================================
CineMatch - API Permissions (api/permissions.py)
============================================================

Custom DRF permission classes that control WHO can do WHAT.

DRF Permission Flow:
  Request arrives
    → Authentication (who are you? → JWT token → User)
      → Permission check (are you allowed? → permission classes)
        → View logic runs (if allowed)
        → 403 Forbidden (if not allowed)

BUILT-IN DRF PERMISSIONS (used directly in views):
  AllowAny              → Anyone (no auth needed)
  IsAuthenticated       → Must be logged in
  IsAuthenticatedOrReadOnly → Read = anyone, Write = auth required
  IsAdminUser           → Must be is_staff=True

CUSTOM PERMISSIONS (defined here):
  IsOwnerOrReadOnly     → Read = anyone, Write = only the owner
  IsOnboarded           → Must have completed onboarding
============================================================
"""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOwnerOrReadOnly(BasePermission):
    """
    Custom permission to only allow owners of an object to edit/delete it.

    - GET, HEAD, OPTIONS (safe methods) → anyone can read
    - POST, PUT, PATCH, DELETE → only the object's owner

    Usage:
        class RatingViewSet(ModelViewSet):
            permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]

    The view must set `obj.user` as the ownership field.
    If the model uses a different field, override `has_object_permission`.
    """

    def has_permission(self, request, view):
        # Safe methods (GET) are always allowed
        if request.method in SAFE_METHODS:
            return True
        # Write methods require authentication
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # Safe methods always allowed (read)
        if request.method in SAFE_METHODS:
            return True
        # Write: only the owner
        # Checks obj.user (works for Rating, WatchlistItem, WatchEvent)
        return obj.user == request.user


class IsOnboarded(BasePermission):
    """
    Allows access only to users who have completed onboarding
    (selected genre preferences).

    Used on recommendation endpoints — recs are meaningless before
    the user tells us what they like.

    Returns 403 with a helpful message directing to onboarding.
    """
    message = (
        "Please complete your genre preferences first. "
        "POST to /api/v1/auth/onboarding/ with your preferred genres."
    )

    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_onboarded
        )


class IsSelfOrAdmin(BasePermission):
    """
    Object-level permission: users can only edit their own profile.
    Admins (is_staff) can edit any profile.
    """

    def has_object_permission(self, request, view, obj):
        # obj here is a User instance
        if request.user.is_staff:
            return True
        return obj == request.user
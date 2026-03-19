"""
============================================================
CineMatch - Email Authentication Backend (users/backends.py)
============================================================

Django's default authentication backend only accepts
the USERNAME_FIELD for login. Since our USERNAME_FIELD
is 'email', Django would look for a user by email.

However, we explicitly define this backend for clarity
and to ensure authenticate(username=email, password=...) works
correctly from both:
  - Our LoginSerializer (uses authenticate())
  - Django Admin (uses its own form)
  - DRF SessionAuthentication (browser-based)

HOW DJANGO AUTH BACKENDS WORK:
  authenticate(request, username='...', password='...')
    → iterates through AUTHENTICATION_BACKENDS in settings
      → calls backend.authenticate() on each
        → first non-None result wins
        → None = try next backend
        → raise PermissionDenied = stop immediately

SETTINGS CONNECTION:
  settings.py → AUTHENTICATION_BACKENDS = ['users.backends.EmailAuthBackend', ...]
============================================================
"""

from django.contrib.auth import get_user_model


class EmailAuthBackend:
    """
    Authenticate users using their email address + password.

    Django's authenticate() calls this with:
      username=<email>  (confusingly named 'username' by Django convention)
      password=<password>

    We look up the user by email, check the password hash,
    and return the user object if valid.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Try to authenticate with email + password.

        Args:
            username: The email address (Django uses 'username' param name by convention)
            password: The plain-text password (we compare against hash)

        Returns:
            User instance if valid, None otherwise
        """
        if not username or not password:
            return None

        User = get_user_model()

        try:
            # Look up user by email (case-insensitive)
            user = User.objects.get(email__iexact=username.strip())
        except User.DoesNotExist:
            # Run the hasher anyway to prevent timing attacks
            # (don't leak whether email exists via response time)
            User().set_password(password)
            return None

        # check_password() compares plain text against stored hash
        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None

    def user_can_authenticate(self, user):
        """
        Only allow active users to log in.
        Inactive users (is_active=False) are rejected.
        """
        is_active = getattr(user, 'is_active', None)
        return is_active or is_active is None

    def get_user(self, user_id):
        """
        Called by Django's auth middleware to load the user from session.
        Must return the User or None (never raise exceptions).
        """
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
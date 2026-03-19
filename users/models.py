"""
============================================================
CineMatch - User Models (users/models.py)
============================================================

This module defines the USER DATA LAYER — what we store
about each person using CineMatch.

WHY CUSTOM USER MODEL?
  Django's default User only has username, email, password.
  We need genre preferences, avatar, watch stats, etc.
  Best practice: define custom user BEFORE first migration.

MODEL HIERARCHY:
  AbstractBaseUser          ← Django base (password, last_login)
    └── User                ← Our main user (+ custom fields)
          └── UserProfile   ← Extended preferences (genre prefs,
                              streaming services, etc.)

HOW IT CONNECTS TO OTHER MODELS:
  User ─── has many ──► Rating          (interactions/models.py)
  User ─── has many ──► WatchlistItem   (interactions/models.py)
  User ─── has many ──► Recommendation  (recommendations/models.py)
  User ─── has one  ──► UserProfile     (this file)
============================================================
"""

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# ============================================================
# CUSTOM USER MANAGER
# ============================================================
class UserManager(BaseUserManager):
    """
    Custom manager for our User model.
    Django requires this when using AbstractBaseUser.

    Provides:
      User.objects.create_user(email, password)
      User.objects.create_superuser(email, password)
    """

    def create_user(self, email, password=None, **extra_fields):
        """
        Create a standard user.
        Email is normalized (lowercased domain) before saving.
        """
        if not email:
            raise ValueError('Email address is required')

        email = self.normalize_email(email)  # foo@GMAIL.COM → foo@gmail.com
        extra_fields.setdefault('is_active', True)

        user = self.model(email=email, **extra_fields)
        user.set_password(password)  # Hashes the password (never store plain text!)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """
        Create an admin superuser (for Django admin panel access).
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if not extra_fields.get('is_staff'):
            raise ValueError('Superuser must have is_staff=True.')
        if not extra_fields.get('is_superuser'):
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


# ============================================================
# USER MODEL
# ============================================================
class User(AbstractBaseUser, PermissionsMixin):
    """
    CineMatch's primary User model.

    KEY DESIGN DECISIONS:
    - Email as username (more user-friendly than arbitrary usernames)
    - is_onboarded: tracks if user has completed genre preference setup
    - genre_preferences: stored as ManyToMany on UserProfile instead
      (keeps this model lean)

    DATABASE TABLE: users_user
    """

    # --- Core Identity ---
    email = models.EmailField(
        _('email address'),
        unique=True,
        help_text="Used as the login identifier"
    )
    username = models.CharField(
        max_length=50,
        unique=True,
        help_text="Display name shown to other users and in recommendations"
    )
    full_name = models.CharField(max_length=100, blank=True)
    avatar = models.ImageField(
        upload_to='avatars/',
        null=True,
        blank=True,
        help_text="Profile picture (stored in media/avatars/)"
    )

    # --- Account Status ---
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False,
        help_text="Can access Django admin panel"
    )
    is_onboarded = models.BooleanField(
        default=False,
        help_text="Has the user completed the initial genre preference setup?"
    )

    # --- Timestamps ---
    date_joined = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(null=True, blank=True)

    # --- Auth Configuration ---
    # Tell Django to use email instead of username for authentication
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']   # Required when creating superuser via CLI

    # Attach our custom manager
    objects = UserManager()

    class Meta:
        db_table = 'users_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-date_joined']

    def __str__(self):
        return f"{self.username} ({self.email})"

    def get_full_name(self):
        return self.full_name or self.username

    @property
    def avatar_url(self):
        """Returns avatar URL or a default placeholder."""
        if self.avatar:
            return self.avatar.url
        # Gravatar-style default using username initial
        return f"https://ui-avatars.com/api/?name={self.username}&background=E50914&color=fff&size=128"

    @property
    def total_ratings(self):
        """How many movies this user has rated. Used to determine CF eligibility."""
        return self.ratings.count()

    @property
    def can_use_collaborative_filtering(self):
        """
        Returns True if the user has enough ratings for collaborative filtering.
        Below this threshold, we fall back to content-based + popularity.
        See: recommendations/engine.py
        """
        from django.conf import settings
        min_ratings = settings.RECOMMENDATION_SETTINGS['MIN_RATINGS_FOR_CF']
        return self.total_ratings >= min_ratings


# ============================================================
# USER PROFILE (Extended Preferences)
# ============================================================
class UserProfile(models.Model):
    """
    Extended user data — preferences, stats, streaming services.

    WHY SEPARATE FROM User?
    - Keeps the User model clean and fast to load
    - Profile data is loaded lazily (only when needed)
    - Easier to extend without touching the auth model

    Connected to User via OneToOneField.
    Access with: user.profile.preferred_genres

    DATABASE TABLE: users_userprofile
    """

    # --- One-to-one link back to User ---
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,       # If user deleted, delete profile too
        related_name='profile',          # Access as user.profile
    )

    # --- Genre Preferences ---
    # These are set during onboarding and used as content-based features.
    # ManyToMany to Genre (defined in movies/models.py).
    # We use a string reference 'movies.Genre' to avoid circular imports.
    preferred_genres = models.ManyToManyField(
        'movies.Genre',
        blank=True,
        related_name='interested_users',
        help_text="Genres selected during onboarding or updated in settings"
    )

    # --- Streaming Service Preferences ---
    # Used to filter where-to-watch links on movie detail pages.
    # Stored as JSON list: ["Netflix", "Prime Video", "Disney+"]
    streaming_services = models.JSONField(
        default=list,
        blank=True,
        help_text="User's active streaming subscriptions for filtering watch links"
    )

    # --- Recommendation Preferences ---
    preferred_language = models.CharField(
        max_length=10,
        default='en',
        help_text="ISO language code: en, hi, fr, etc."
    )
    include_adult_content = models.BooleanField(
        default=False,
        help_text="Show R-rated / adult content in recommendations"
    )

    # --- User Stats (denormalized for fast dashboard queries) ---
    # These are updated via Django signals (see interactions/signals.py)
    total_movies_watched = models.PositiveIntegerField(default=0)
    total_hours_watched = models.FloatField(default=0.0)
    avg_rating_given = models.FloatField(
        null=True,
        blank=True,
        help_text="Rolling average of all ratings given by this user"
    )

    # --- Timestamps ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users_userprofile'
        verbose_name = 'User Profile'

    def __str__(self):
        return f"Profile: {self.user.username}"

    def get_genre_names(self):
        """Returns list of preferred genre names for display."""
        return list(self.preferred_genres.values_list('name', flat=True))
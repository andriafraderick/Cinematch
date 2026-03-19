"""
============================================================
CineMatch - Interaction Models (interactions/models.py)
============================================================

This module captures ALL user behavior — the raw data that
feeds the ML recommendation engine.

NVIDIA's recommendation system guide highlights that
"implicit feedback" (views, clicks) and "explicit feedback"
(ratings) are both critical for accurate recommendations.

MODEL OVERVIEW:
  Rating         ← Explicit: 1-10 star rating given to a movie
  WatchlistItem  ← Explicit: "I want to watch this"
  ViewHistory    ← Implicit: user viewed movie detail page
  WatchEvent     ← Implicit: user watched the movie (marked as watched)

ML USAGE:
  Rating.score   → fills the User-Item matrix for Collaborative Filtering
  WatchlistItem  → boosts content similarity scores
  ViewHistory    → click-through signal for implicit CF
  WatchEvent     → strongest positive signal in the model

SIGNALS:
  After each save() here, Django signals (interactions/signals.py)
  trigger recommendation recalculation if threshold is crossed.
============================================================
"""

from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


# ============================================================
# RATING
# ============================================================
class Rating(models.Model):
    """
    An explicit 1-10 rating given by a user to a movie.

    This is the PRIMARY DATA SOURCE for Collaborative Filtering.
    The ML engine builds a sparse User × Movie matrix from these ratings.

    Constraint: One rating per user per movie (unique_together).
    If user re-rates, we UPDATE (not insert) via upsert logic in the view.

    DATABASE TABLE: interactions_rating
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ratings',        # Access as user.ratings.all()
    )
    movie = models.ForeignKey(
        'movies.Movie',
        on_delete=models.CASCADE,
        related_name='ratings',        # Access as movie.ratings.all()
    )
    score = models.FloatField(
        validators=[MinValueValidator(1.0), MaxValueValidator(10.0)],
        help_text="Rating from 1.0 to 10.0 (supports half-stars)"
    )
    review = models.TextField(
        blank=True,
        help_text="Optional written review"
    )

    # --- Metadata ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'interactions_rating'
        unique_together = ['user', 'movie']    # One rating per user per movie
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'movie']),
            models.Index(fields=['movie', 'score']),
        ]

    def __str__(self):
        return f"{self.user.username} → {self.movie.title}: {self.score}/10"

    @classmethod
    def upsert(cls, user, movie, score, review=''):
        """
        Create or update a rating.
        Called by the API view to handle re-ratings cleanly.
        Returns (rating_instance, was_created).
        """
        rating, created = cls.objects.update_or_create(
            user=user,
            movie=movie,
            defaults={'score': score, 'review': review}
        )
        return rating, created


# ============================================================
# WATCHLIST ITEM
# ============================================================
class WatchlistItem(models.Model):
    """
    A movie saved to a user's "Want to Watch" list.

    ML Significance:
    - Acts as a POSITIVE IMPLICIT signal (stronger than view, weaker than rating)
    - Used in hybrid scoring: watchlisted movies get content-similarity boost
    - Director/genre of watchlisted movies influences future recs

    DATABASE TABLE: interactions_watchlistitem
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='watchlist',
    )
    movie = models.ForeignKey(
        'movies.Movie',
        on_delete=models.CASCADE,
        related_name='watchlisted_by',
    )
    added_at = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional personal note about why saved"
    )

    class Meta:
        db_table = 'interactions_watchlistitem'
        unique_together = ['user', 'movie']
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.user.username} → Watchlist: {self.movie.title}"


# ============================================================
# WATCH EVENT (Marked as Watched)
# ============================================================
class WatchEvent(models.Model):
    """
    Recorded when a user marks a movie as "Watched".

    This is the STRONGEST positive feedback signal:
    - User explicitly said "I watched this"
    - Drives "Because you watched X..." recommendations
    - Updates UserProfile.total_movies_watched via signal

    ML Significance:
    - Treated as implicit rating of ~7.0 if no explicit rating exists
    - Used to prevent recommending already-watched movies (unless user opts in)

    DATABASE TABLE: interactions_watchevent
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='watch_events',
    )
    movie = models.ForeignKey(
        'movies.Movie',
        on_delete=models.CASCADE,
        related_name='watch_events',
    )
    watched_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(
        max_length=50,
        blank=True,
        help_text="Where they watched it: Netflix, Prime, Theatre, etc."
    )
    rewatched = models.BooleanField(
        default=False,
        help_text="True if user has watched this before (additional signal)"
    )

    class Meta:
        db_table = 'interactions_watchevent'
        ordering = ['-watched_at']
        # Allow multiple watch events per user/movie (rewatches)

    def __str__(self):
        return f"{self.user.username} watched {self.movie.title}"


# ============================================================
# VIEW HISTORY (Page Views)
# ============================================================
class ViewHistory(models.Model):
    """
    Implicit signal: user clicked on a movie detail page.

    This is the WEAKEST signal but highest volume:
    - Just viewing shows interest
    - Multiple views = stronger interest
    - Viewing → not rating = mild negative signal

    Used for:
    - "Continue browsing" carousel on home page
    - Implicit feature in hybrid model

    DATABASE TABLE: interactions_viewhistory
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='view_history',
    )
    movie = models.ForeignKey(
        'movies.Movie',
        on_delete=models.CASCADE,
        related_name='views',
    )
    viewed_at = models.DateTimeField(auto_now_add=True)
    view_count = models.PositiveIntegerField(
        default=1,
        help_text="Incremented on repeat views instead of creating new records"
    )

    class Meta:
        db_table = 'interactions_viewhistory'
        unique_together = ['user', 'movie']   # One record per user/movie, count increments
        ordering = ['-viewed_at']

    def __str__(self):
        return f"{self.user.username} viewed {self.movie.title} ({self.view_count}x)"

    @classmethod
    def record_view(cls, user, movie):
        """
        Upsert a view: create if first time, increment count if repeat.
        Called from movie detail view.
        """
        obj, created = cls.objects.get_or_create(
            user=user,
            movie=movie,
        )
        if not created:
            # Atomic increment to avoid race conditions
            cls.objects.filter(pk=obj.pk).update(
                view_count=models.F('view_count') + 1,
                viewed_at=models.functions.Now()
            )
        return obj
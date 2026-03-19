"""
============================================================
CineMatch - Recommendation Models (recommendations/models.py)
============================================================

This module stores the OUTPUT of the ML recommendation engine.

WHY STORE RECOMMENDATIONS IN THE DATABASE?
  Option A (compute on request): Every page load runs ML → SLOW
  Option B (pre-compute + cache): ML runs in background, results
    stored in DB → FAST page loads

We use Option B: The ML engine (recommendations/engine.py) runs
after each user interaction (via Django signals) and stores
results here. The view simply reads from this table.

MODEL OVERVIEW:
  Recommendation        ← One recommended movie for a user
  RecommendationBatch   ← Metadata about a full recs run
  SimilarMovie          ← "Movies like X" (not user-personalized)

HOW RECS ARE GENERATED:
  1. User rates/watches a movie
  2. Signal fires → recommendations/tasks.py:generate_recommendations()
  3. Engine runs hybrid CF + Content-Based algorithm
  4. Results written to Recommendation table
  5. Next page load reads from Recommendation table (fast)

See: recommendations/engine.py for the ML implementation
============================================================
"""

from django.db import models
from django.conf import settings


# ============================================================
# RECOMMENDATION BATCH
# ============================================================
class RecommendationBatch(models.Model):
    """
    Metadata about a full recommendation run for a user.

    Tracks WHEN recs were generated and WHICH algorithm was used.
    This helps with:
    - Debugging why a user got certain recommendations
    - A/B testing different algorithm weights
    - Cache invalidation (check if batch is too old)

    DATABASE TABLE: recommendations_recommendationbatch
    """

    ALGORITHM_CHOICES = [
        ('hybrid', 'Hybrid (CF + Content-Based)'),       # Primary algorithm
        ('content', 'Content-Based Only'),                # Used when CF data sparse
        ('collaborative', 'Collaborative Filtering Only'),
        ('popularity', 'Popularity-Based'),               # Cold start: new users
        ('genre', 'Genre-Based'),                         # Onboarding only
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='recommendation_batches',
    )
    algorithm_used = models.CharField(
        max_length=20,
        choices=ALGORITHM_CHOICES,
        default='hybrid',
        help_text="Which ML algorithm generated this batch"
    )
    num_recommendations = models.PositiveIntegerField(default=0)

    # --- Algorithm Performance Metrics (for debugging/analysis) ---
    cf_weight_used = models.FloatField(
        null=True,
        blank=True,
        help_text="Actual collaborative filtering weight used (0-1)"
    )
    content_weight_used = models.FloatField(
        null=True,
        blank=True,
        help_text="Actual content-based weight used (0-1)"
    )
    ratings_available = models.IntegerField(
        default=0,
        help_text="How many ratings the user had at generation time"
    )

    # --- Timestamps ---
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="After this datetime, recs should be regenerated"
    )

    class Meta:
        db_table = 'recommendations_batch'
        ordering = ['-generated_at']
        get_latest_by = 'generated_at'

    def __str__(self):
        return f"Batch for {self.user.username} [{self.algorithm_used}] @ {self.generated_at:%Y-%m-%d %H:%M}"

    @property
    def is_stale(self):
        """Returns True if this batch needs to be regenerated."""
        from django.utils import timezone
        if self.expires_at and timezone.now() > self.expires_at:
            return True
        return False


# ============================================================
# RECOMMENDATION
# ============================================================
class Recommendation(models.Model):
    """
    A single movie recommendation for a specific user.

    Each record = "We think [user] would like [movie]"
    with a score and reason explaining WHY.

    DATABASE TABLE: recommendations_recommendation
    """

    REASON_CHOICES = [
        ('watched_similar', 'Because you watched similar movies'),
        ('genre_match', 'Matches your preferred genres'),
        ('director_fan', 'You like this director'),
        ('actor_fan', 'Features your favorite actors'),
        ('users_like_you', 'Users like you enjoyed this'),
        ('trending', 'Trending now'),
        ('highly_rated', 'Critically acclaimed'),
        ('hidden_gem', 'Hidden gem you might have missed'),
    ]

    # --- Core Relationship ---
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='recommendations',
    )
    movie = models.ForeignKey(
        'movies.Movie',
        on_delete=models.CASCADE,
        related_name='recommended_to',
    )
    batch = models.ForeignKey(
        RecommendationBatch,
        on_delete=models.CASCADE,
        related_name='recommendations',
        null=True,
        blank=True,
    )

    # --- Scoring ---
    score = models.FloatField(
        help_text="Recommendation confidence score (0-1, higher = more confident)"
    )
    rank = models.PositiveIntegerField(
        default=0,
        help_text="Position in user's recommendation list (1 = top pick)"
    )

    # --- Explainability ---
    # What drove this recommendation?
    reason_code = models.CharField(
        max_length=30,
        choices=REASON_CHOICES,
        default='watched_similar',
        help_text="Primary reason this was recommended (for UI display)"
    )
    reason_text = models.CharField(
        max_length=200,
        blank=True,
        help_text="Human-readable explanation: 'Because you rated Inception 9/10'"
    )
    # Reference movie that drove this recommendation (if applicable)
    source_movie = models.ForeignKey(
        'movies.Movie',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sourced_recommendations',
        help_text="The movie that triggered this recommendation"
    )

    # --- Engagement Tracking ---
    # Did the user actually like this recommendation?
    was_clicked = models.BooleanField(
        default=False,
        help_text="User clicked on this recommendation"
    )
    was_rated = models.BooleanField(
        default=False,
        help_text="User later rated this movie"
    )
    was_added_to_watchlist = models.BooleanField(
        default=False,
        help_text="User added this to watchlist"
    )

    # --- Timestamps ---
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recommendations_recommendation'
        unique_together = ['user', 'movie', 'batch']
        ordering = ['rank']
        indexes = [
            models.Index(fields=['user', 'rank']),
            models.Index(fields=['user', 'score']),
        ]

    def __str__(self):
        return f"Rec #{self.rank}: {self.movie.title} for {self.user.username} (score: {self.score:.3f})"


# ============================================================
# SIMILAR MOVIE
# ============================================================
class SimilarMovie(models.Model):
    """
    Pre-computed movie-to-movie similarity.

    "If you liked [movie_a], you might like [movie_b]"

    This is CONTENT-BASED similarity (not user-personalized).
    Calculated using cosine similarity of content vectors.

    Shown on:
    - Movie detail page ("More Like This" section)
    - "Because you watched X..." carousels

    Refreshed by management command: python manage.py compute_similarities

    DATABASE TABLE: recommendations_similarmovie
    """
    movie = models.ForeignKey(
        'movies.Movie',
        on_delete=models.CASCADE,
        related_name='similar_to',
    )
    similar_movie = models.ForeignKey(
        'movies.Movie',
        on_delete=models.CASCADE,
        related_name='similar_from',
    )
    similarity_score = models.FloatField(
        help_text="Cosine similarity score (0-1)"
    )

    # What makes them similar?
    shared_genres = models.JSONField(
        default=list,
        blank=True,
        help_text="Genre names shared between the two movies"
    )
    shared_cast = models.JSONField(
        default=list,
        blank=True,
        help_text="Actor names shared between the two movies"
    )
    same_director = models.BooleanField(default=False)

    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'recommendations_similarmovie'
        unique_together = ['movie', 'similar_movie']
        ordering = ['-similarity_score']

    def __str__(self):
        return f"{self.movie.title} ≈ {self.similar_movie.title} ({self.similarity_score:.3f})"
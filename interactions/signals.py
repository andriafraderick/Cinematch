"""
============================================================
CineMatch - Interactions Signals (interactions/signals.py)
============================================================

These signals fire AFTER a user rates, watches, or bookmarks.
They trigger the recommendation engine to recalculate.

SIGNAL FLOW:
  Rating.post_save
    → on_rating_saved()
      → calls tasks.trigger_recommendation_update(user_id)
        → throttle check (every N ratings)
          → HybridEngine.generate_for_user(user)
            → writes Recommendation records to DB

  WatchEvent.post_save
    → on_watch_event_saved()
      → update UserProfile.total_movies_watched
      → also triggers recommendation update (watch = strong signal)

CONNECTION TO TASKS:
  signals.py detects the event (what happened)
  tasks.py decides IF/WHEN to recalculate (throttle logic)
  engine.py does the actual ML computation
============================================================
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Rating, WatchEvent
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Rating)
def on_rating_saved(sender, instance, created, **kwargs):
    """
    Called every time a Rating is saved (new or updated).

    Passes to tasks.trigger_recommendation_update() which:
    - Checks if enough new ratings have accumulated
    - Determines the right algorithm (CF vs content vs hybrid)
    - Calls HybridEngine to regenerate recommendations
    """
    user = instance.user

    logger.info(
        f"Rating {'created' if created else 'updated'} for "
        f"{user.username} → movie ID {instance.movie_id} "
        f"(score: {instance.score})"
    )

    # Delegate to tasks.py for throttling + engine call
    # Import here (not at top) to avoid circular imports at module load time
    try:
        from recommendations.tasks import trigger_recommendation_update
        trigger_recommendation_update(user_id=user.id)
    except Exception as e:
        # Never let recommendation errors break the rating save
        logger.error(f"Failed to trigger rec update after rating: {e}", exc_info=True)


@receiver(post_save, sender=WatchEvent)
def on_watch_event_saved(sender, instance, created, **kwargs):
    """
    Called when user marks a movie as watched.

    Two things happen:
    1. Update UserProfile stats (watch count, hours watched)
    2. Trigger recommendation recalculation (watch = strong positive signal)
    """
    if created:
        user = instance.user

        # --- Update profile stats ---
        try:
            profile = user.profile
            profile.total_movies_watched = user.watch_events.count()

            # Approximate hours watched (runtime in minutes → hours)
            runtime = instance.movie.runtime or 0
            profile.total_hours_watched += runtime / 60.0
            profile.save(update_fields=['total_movies_watched', 'total_hours_watched'])

            logger.info(
                f"{user.username} watch count updated to "
                f"{profile.total_movies_watched} movies"
            )
        except Exception as e:
            logger.error(f"Error updating watch stats for {user.username}: {e}")

        # --- Trigger recommendation update ---
        # A watched movie is a strong implicit positive signal —
        # treat it similarly to a high rating for rec purposes
        try:
            from recommendations.tasks import trigger_recommendation_update
            trigger_recommendation_update(user_id=user.id)
        except Exception as e:
            logger.error(f"Failed to trigger rec update after watch event: {e}", exc_info=True)
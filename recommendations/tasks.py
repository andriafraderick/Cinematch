# -*- coding: utf-8 -*-
"""
============================================================
CineMatch - Recommendation Tasks (recommendations/tasks.py)
============================================================

This module provides the TASK FUNCTIONS that are called by
Django signals in interactions/signals.py.

ARCHITECTURE:
  User rates a movie
    → interactions/signals.py: on_rating_saved()
      → calls tasks.py: trigger_recommendation_update(user_id)
        → checks if update is needed (throttle)
          → calls HybridEngine.generate_for_user(user)
            → writes results to Recommendation table

WHY A SEPARATE TASKS MODULE?
  Separation of concerns:
  - signals.py: detects the event (rating saved)
  - tasks.py: decides IF and WHEN to act
  - engine.py: does the actual ML work

  Also: tasks.py is where you'd add Celery integration
  for async background processing in production.
  Currently runs SYNCHRONOUSLY (in the same request cycle).

THROTTLING:
  Recommendations are expensive to compute.
  We don't recalculate after EVERY single rating.
  Only recalculate after every N interactions (configurable in settings).

  Example:
    RECALC_AFTER_N_INTERACTIONS = 3
    Rating 1: no recalc
    Rating 2: no recalc
    Rating 3: RECALC → fresh recommendations
    Rating 4: no recalc
    ...
============================================================
"""

import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def trigger_recommendation_update(user_id, algorithm=None):
    """
    Entry point called by Django signals after a user interaction.

    Decides whether to recalculate recommendations based on:
    1. Throttle check: has enough new interactions accumulated?
    2. Cold start check: is this the user's first few ratings?

    Args:
        user_id: database User.id
        algorithm: force specific algorithm (optional, for testing)
    """
    try:
        from users.models import User
        user = User.objects.get(id=user_id)
    except Exception as e:
        logger.error(f"Could not load user {user_id} for recommendation update: {e}")
        return

    # --- Throttle Check ---
    # Don't recalculate on every single rating to avoid performance issues
    recalc_threshold = settings.RECOMMENDATION_SETTINGS['RECALC_AFTER_N_INTERACTIONS']
    total_ratings = user.total_ratings

    # Always recalc on first rating, at CF threshold, and every N ratings after
    min_cf = settings.RECOMMENDATION_SETTINGS['MIN_RATINGS_FOR_CF']
    force_recalc_at = {1, min_cf}   # Always recalc at these milestones

    should_recalc = (
        total_ratings in force_recalc_at or
        (total_ratings > 0 and total_ratings % recalc_threshold == 0)
    )

    if not should_recalc:
        logger.debug(
            f"Skipping rec update for {user.username} "
            f"(ratings={total_ratings}, threshold={recalc_threshold})"
        )
        return

    logger.info(f"Triggering recommendation update for {user.username} (ratings={total_ratings})")

    # --- Call the engine ---
    generate_recommendations_for_user(user, force_algorithm=algorithm)


def generate_recommendations_for_user(user, force_algorithm=None):
    """
    Actually generate and save recommendations for a user.

    Wraps HybridEngine.generate_for_user() with error handling
    so recommendation failures don't crash the user's request.

    Args:
        user: User model instance
        force_algorithm: override algorithm selection

    Returns:
        RecommendationBatch if successful, None on error
    """
    try:
        from recommendations.engine import HybridEngine
        engine = HybridEngine.get_instance()
        batch = engine.generate_for_user(user, force_algorithm=force_algorithm)
        logger.info(f"Recommendations updated for {user.username}")
        return batch
    except Exception as e:
        # CRITICAL: Never let recommendation errors surface to users
        # Log the error but let the request continue normally
        logger.error(
            f"Failed to generate recommendations for user {user.username}: {e}",
            exc_info=True  # Include full traceback in logs
        )
        return None


def warm_up_engine():
    """
    Pre-warm the recommendation engine.

    Called by:
    - management command: python manage.py warm_engine
    - Server startup (if added to AppConfig.ready())

    This fits both the TF-IDF and SVD models so the
    first user to request recommendations doesn't wait.
    """
    try:
        from recommendations.engine import HybridEngine
        engine = HybridEngine.get_instance()
        engine.warm_up()
        logger.info("Recommendation engine warmed up successfully")
        return True
    except Exception as e:
        logger.error(f"Engine warm-up failed: {e}", exc_info=True)
        return False


def regenerate_all_recommendations():
    """
    Regenerate recommendations for ALL active users.

    Called by management command: python manage.py regen_all_recs
    Use this after:
    - Adding many new movies
    - Significantly changing algorithm weights
    - Major rating data imports

    WARNING: This is slow for large user bases.
             In production, run as a background job during off-peak hours.
    """
    from users.models import User
    from recommendations.engine import HybridEngine

    logger.info("Starting full recommendation regeneration for all users...")

    engine = HybridEngine.get_instance()
    engine.ensure_ready()

    users = User.objects.filter(
        is_active=True
    ).prefetch_related('ratings')

    success_count = 0
    error_count = 0

    for user in users:
        try:
            if user.total_ratings == 0:
                # Skip users with no ratings - they get popularity-based anyway
                continue
            engine.generate_for_user(user)
            success_count += 1
            logger.debug(f"Regenerated recs for {user.username}")
        except Exception as e:
            error_count += 1
            logger.error(f"Failed to regenerate for {user.username}: {e}")

    logger.info(
        f"Full regeneration complete. "
        f"Success: {success_count}, Errors: {error_count}"
    )
    return success_count, error_count
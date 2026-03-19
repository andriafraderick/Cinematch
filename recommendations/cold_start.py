"""
============================================================
CineMatch - Cold Start Recommender
(recommendations/cold_start.py)
============================================================

WHAT IS THE COLD START PROBLEM?
  A brand new user has no ratings, no watch history.
  CF and content-based both need user history to work.
  What do we recommend to them?

OUR COLD START STRATEGY (3 stages):
  Stage 1 — No data at all (0 ratings, no genre prefs):
    → Show globally popular + highly-rated movies
    → "What's popular on CineMatch right now"

  Stage 2 — Genre preferences set (from onboarding):
    → Filter popular movies by their preferred genres
    → "Top picks in Action & Sci-Fi for you"

  Stage 3 — A few ratings (1-4):
    → Content-based on their rated movies only
    → Transitioning toward full hybrid engine

WHEN IS THIS CALLED?
  HybridEngine._get_algorithm_weights() returns 'popularity'
  or 'genre' for new users, which routes to this module.

CONNECTION:
  HybridEngine.generate_for_user()
    → sees algorithm = 'popularity' or 'genre'
      → calls ColdStartRecommender.get_recommendations(user)
============================================================
"""

import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class ColdStartRecommender:
    """
    Handles recommendation for users with insufficient interaction data.
    Uses TMDB popularity scores and user-selected genre preferences.
    """

    def get_recommendations(self, user, num_recs=20):
        """
        Generate cold-start recommendations for a new user.

        Pipeline:
          1. Check if user has genre preferences (set during onboarding)
          2. If yes: filter popular movies by those genres
          3. Apply TMDB-weighted scoring (popularity + rating + recency)
          4. Return ranked list

        Returns:
            list of dicts: [{movie_id, score, rank, reason_code, reason_text}]
        """
        from movies.models import Movie

        # Get user's preferred genres from onboarding
        preferred_genre_ids = []
        try:
            preferred_genre_ids = list(
                user.profile.preferred_genres.values_list('id', flat=True)
            )
        except Exception:
            pass

        # Build base queryset
        qs = Movie.objects.filter(
            status='Released',
            adult=False,
            vote_count__gte=100,    # Only movies with enough votes for reliable scoring
        )

        # Apply genre filter if user has preferences
        if preferred_genre_ids:
            qs = qs.filter(genres__id__in=preferred_genre_ids).distinct()
            reason_code = 'genre_match'
            reason_text_template = "Top pick in your preferred genres"
        else:
            reason_code = 'trending'
            reason_text_template = "Popular on CineMatch"

        # TMDB Weighted Score formula (inspired by IMDB's formula):
        # WS = (v / (v + m)) × R + (m / (v + m)) × C
        # Where:
        #   v = vote count for the movie
        #   m = minimum votes required (100)
        #   R = average rating for the movie
        #   C = global average rating
        # Then combine with popularity for final score.

        movies = list(qs.prefetch_related('genres').order_by('-popularity')[:num_recs * 3])

        if not movies:
            # Fallback: all popular movies regardless of genre
            movies = list(Movie.objects.filter(
                status='Released',
                adult=False,
                vote_count__gte=100
            ).order_by('-popularity')[:num_recs])
            reason_code = 'trending'
            reason_text_template = "Trending on CineMatch"

        # Calculate weighted scores
        scored = []
        global_avg = 6.5  # TMDB global average is roughly 6.5/10
        min_votes = 100

        for movie in movies:
            v = movie.vote_count or 0
            R = movie.vote_average or 0
            C = global_avg
            m = min_votes

            # Bayesian average (IMDB formula)
            bayesian_rating = (v / (v + m)) * R + (m / (v + m)) * C

            # Normalize popularity (log scale to prevent outliers dominating)
            import math
            pop_score = math.log1p(movie.popularity) / math.log1p(10000)  # normalize to ~0-1

            # Final score: 60% quality + 40% popularity
            final_score = 0.6 * (bayesian_rating / 10.0) + 0.4 * pop_score

            scored.append({
                'movie': movie,
                'score': final_score,
            })

        # Sort by score
        scored.sort(key=lambda x: x['score'], reverse=True)

        # Build recommendation dicts
        recommendations = []
        for rank, item in enumerate(scored[:num_recs], start=1):
            movie = item['movie']
            genres = [g.name for g in movie.genres.all()]

            # Personalize reason text when we know genre
            if preferred_genre_ids and genres:
                reason_text = f"Top {genres[0]} pick for you"
            else:
                reason_text = reason_text_template

            recommendations.append({
                'movie_id': movie.id,
                'score': item['score'],
                'rank': rank,
                'reason_code': reason_code,
                'reason_text': reason_text,
                'source_movie_id': None,
            })

        logger.info(
            f"Cold start: generated {len(recommendations)} recs for "
            f"{user.username} (genre_prefs={bool(preferred_genre_ids)})"
        )
        return recommendations
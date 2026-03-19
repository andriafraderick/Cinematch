"""
============================================================
CineMatch - Hybrid Recommendation Engine
(recommendations/engine.py)
============================================================

WHAT IS HYBRID FILTERING?
  The best recommendation systems (Netflix, Spotify, YouTube)
  combine MULTIPLE algorithms. Neither content-based NOR
  collaborative filtering alone is optimal:

  Content-Based Problems:
  - "Filter bubble": only recommends what user already knows
  - Can't discover genuinely new taste areas
  - Ignores wisdom of the crowd

  Collaborative Filtering Problems:
  - Cold start: needs ratings data to work
  - Popularity bias: tends to recommend blockbusters
  - "Gray sheep" problem: niche users get poor recs

  Hybrid Solution:
  - Use CF when user has enough data (≥5 ratings)
  - Use content when data is sparse
  - Blend both with dynamic weights

NVIDIA'S RECOMMENDATION GUIDE:
  "Modern recommender systems use ensemble methods that
   combine collaborative filtering's user-behavior insight
   with content-based filtering's item-feature knowledge.
   The blend ratio adapts based on data availability."

HYBRID SCORING FORMULA:
  hybrid_score = (cf_weight × cf_score) + (content_weight × content_score)

  Dynamic weights based on rating count:
  0-4 ratings:   cf=0.0, content=1.0  (pure content)
  5-9 ratings:   cf=0.2, content=0.8  (mostly content)
  10-19 ratings: cf=0.4, content=0.6  (balanced lean content)
  20-49 ratings: cf=0.6, content=0.4  (balanced lean CF)
  50+ ratings:   cf=0.8, content=0.2  (mostly CF)

POST-PROCESSING PIPELINE:
  1. Filter out already-watched movies (user preference)
  2. Filter adult content if user opted out
  3. Apply diversity boost (avoid 10 Nolan films in a row)
  4. Generate human-readable explanation for each rec
  5. Rank and truncate to NUM_RECOMMENDATIONS

CONNECTIONS:
  HybridEngine uses:
    ContentEngine (recommendations/content_engine.py)
    CollaborativeEngine (recommendations/collaborative_engine.py)
  HybridEngine is called by:
    recommendations/tasks.py → generate_for_user()
  HybridEngine writes to:
    Recommendation, RecommendationBatch (recommendations/models.py)
============================================================
"""

import logging
from collections import defaultdict
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

# Import our two sub-engines
from recommendations.content_engine import ContentEngine
from recommendations.collaborative_engine import CollaborativeEngine


class HybridEngine:
    """
    The main recommendation engine orchestrator.

    Combines ContentEngine and CollaborativeEngine into a
    single pipeline that generates personalized recommendations
    for any user.

    This is a SINGLETON-STYLE class (one instance shared across requests).
    State (fitted models) persists in memory between calls.
    Use HybridEngine.get_instance() to get the shared instance.
    """

    # Singleton instance
    _instance = None

    @classmethod
    def get_instance(cls):
        """
        Get or create the shared HybridEngine instance.

        Lazy initialization: engine is fitted on first use,
        then reused for subsequent recommendations.

        In production, this would be pre-warmed at server startup
        via a management command or celery beat task.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Force re-fitting of the engine (call after new movies/ratings added)."""
        cls._instance = None

    def __init__(self):
        self.content_engine = ContentEngine()
        self.cf_engine = CollaborativeEngine(n_factors=50)
        self.is_ready = False
        self._settings = settings.RECOMMENDATION_SETTINGS

    def warm_up(self):
        """
        Fit both sub-engines. Call this at server startup or
        via management command before serving recommendations.

        Takes 5-60 seconds depending on catalog size.
        """
        logger.info("Warming up HybridEngine...")

        # Fit content engine (TF-IDF on movie features)
        self.content_engine.fit()

        # Fit collaborative engine (SVD on rating matrix)
        self.cf_engine.fit()

        self.is_ready = True
        logger.info("HybridEngine ready")
        return self

    def ensure_ready(self):
        """Auto-warm if not fitted. Safe to call from views."""
        if not self.is_ready:
            self.warm_up()

    # ----------------------------------------------------------
    # CORE: GENERATE RECOMMENDATIONS FOR A USER
    # ----------------------------------------------------------
    def generate_for_user(self, user, num_recs=None, force_algorithm=None):
        """
        Main entry point: generate and SAVE recommendations for a user.

        FULL PIPELINE:
          1. Determine algorithm based on user's rating count
          2. Get candidate movies (exclude already watched)
          3. Score candidates with content + CF engines
          4. Blend scores with dynamic weights
          5. Apply post-processing (diversity, filtering)
          6. Generate explanations for each recommendation
          7. Save to Recommendation + RecommendationBatch tables

        Args:
            user: User model instance
            num_recs: override default NUM_RECOMMENDATIONS
            force_algorithm: force 'hybrid', 'content', 'popularity', or 'genre'

        Returns:
            RecommendationBatch instance (with linked Recommendation records)
        """
        self.ensure_ready()

        num_recs = num_recs or self._settings['NUM_RECOMMENDATIONS']

        # --- Step 1: Determine algorithm ---
        algorithm, cf_weight, content_weight = self._get_algorithm_weights(user, force_algorithm)
        logger.info(
            f"Generating recs for {user.username} | algorithm={algorithm} | "
            f"cf={cf_weight:.2f} content={content_weight:.2f}"
        )

        # --- Step 1b: Cold start routing ---
        # New users (no ratings, or only genre prefs) go directly to
        # the cold start engine which uses popularity + Bayesian scoring.
        if algorithm in ('popularity', 'genre'):
            logger.info(f"Routing {user.username} to cold start engine (algorithm={algorithm})")
            from recommendations.cold_start import ColdStartRecommender
            cold_recs = ColdStartRecommender().get_recommendations(user, num_recs)
            return self._save_to_database(user, cold_recs, algorithm, 0.0, 0.0)

        # --- Step 2: Get candidate movies ---
        candidate_ids = self._get_candidate_movie_ids(user)
        if not candidate_ids:
            logger.warning(f"No candidate movies for {user.username}")
            return None

        logger.info(f"Scoring {len(candidate_ids)} candidate movies...")

        # --- Step 3: Score candidates ---
        cf_scores = {}
        content_scores = {}

        if cf_weight > 0 and self.cf_engine.is_fitted:
            cf_scores = self.cf_engine.predict_ratings(user, candidate_ids)

        if content_weight > 0 and self.content_engine.is_fitted:
            content_scores = self.content_engine.score_movies_for_user(user, candidate_ids)

        # --- Step 4: Blend scores ---
        hybrid_scores = self._blend_scores(
            candidate_ids, cf_scores, content_scores,
            cf_weight, content_weight
        )

        # --- Step 5: Post-process ---
        final_scores = self._post_process(hybrid_scores, user, num_recs * 2)

        # --- Step 6: Generate explanations ---
        recommendations = self._generate_recommendations_with_reasons(
            user, final_scores, num_recs
        )

        # --- Step 7: Save to database ---
        batch = self._save_to_database(
            user, recommendations, algorithm,
            cf_weight, content_weight
        )

        logger.info(f"Generated {len(recommendations)} recommendations for {user.username}")
        return batch

    # ----------------------------------------------------------
    # ALGORITHM WEIGHT DETERMINATION
    # ----------------------------------------------------------
    def _get_algorithm_weights(self, user, force_algorithm=None):
        """
        Dynamically determine CF vs content weights based on
        how many ratings the user has provided.

        More ratings = more reliable CF = higher CF weight.

        Returns:
            tuple: (algorithm_name, cf_weight, content_weight)
        """
        if force_algorithm:
            weights = {
                'hybrid': (0.5, 0.5),
                'content': (0.0, 1.0),
                'collaborative': (1.0, 0.0),
                'popularity': (0.0, 0.0),  # Both 0 → uses popularity fallback
                'genre': (0.0, 0.0),
            }
            cf_w, c_w = weights.get(force_algorithm, (0.4, 0.6))
            return force_algorithm, cf_w, c_w

        total_ratings = user.total_ratings

        # Dynamic weight schedule (from settings as base, adjusted by data)
        base_cf = self._settings['COLLABORATIVE_WEIGHT']
        base_content = self._settings['CONTENT_WEIGHT']
        min_cf = self._settings['MIN_RATINGS_FOR_CF']

        if total_ratings == 0:
            # Brand new user: no ratings at all
            # Use genre preferences if set, otherwise popularity
            if hasattr(user, 'profile') and user.profile.preferred_genres.exists():
                return 'genre', 0.0, 1.0
            return 'popularity', 0.0, 0.0

        elif total_ratings < min_cf:
            # Some data but not enough for reliable CF
            # Linear interpolation: more ratings → more CF weight
            cf_w = (total_ratings / min_cf) * 0.2  # Max 0.2 before threshold
            return 'content', cf_w, 1.0 - cf_w

        elif total_ratings < 20:
            # Enough for CF but still lean on content
            return 'hybrid', 0.3, 0.7

        elif total_ratings < 50:
            # Good balance
            return 'hybrid', base_cf, base_content

        else:
            # Power user: trust CF more
            return 'hybrid', min(base_cf + 0.2, 0.8), max(base_content - 0.2, 0.2)

    # ----------------------------------------------------------
    # CANDIDATE SELECTION
    # ----------------------------------------------------------
    def _get_candidate_movie_ids(self, user):
        """
        Get all movies eligible for recommendation.

        Excludes:
        - Movies the user has already watched
        - Movies the user has already rated
        - Adult content (if user opted out)
        - Movies not yet released

        Returns:
            list of movie DB IDs
        """
        from movies.models import Movie
        from interactions.models import Rating, WatchEvent

        # Get IDs of movies to exclude (already seen/rated)
        rated_ids = set(
            Rating.objects.filter(user=user).values_list('movie_id', flat=True)
        )
        watched_ids = set(
            WatchEvent.objects.filter(user=user).values_list('movie_id', flat=True)
        )
        exclude_ids = rated_ids | watched_ids

        # Build candidate queryset
        qs = Movie.objects.filter(status='Released')

        # Filter adult content based on user preference
        try:
            if not user.profile.include_adult_content:
                qs = qs.filter(adult=False)
        except Exception:
            qs = qs.filter(adult=False)

        # Exclude already seen
        if exclude_ids:
            qs = qs.exclude(id__in=exclude_ids)

        return list(qs.values_list('id', flat=True))

    # ----------------------------------------------------------
    # SCORE BLENDING
    # ----------------------------------------------------------
    def _blend_scores(self, candidate_ids, cf_scores, content_scores,
                      cf_weight, content_weight):
        """
        Merge CF and content scores into a single hybrid score.

        For movies missing from one scorer (e.g., new movie not in
        CF matrix), we use only the available score.

        Formula:
            if both available:
                hybrid = cf_weight × cf + content_weight × content
            if only CF:
                hybrid = cf_score × 0.8  (slight penalty for no content data)
            if only content:
                hybrid = content_score × 0.8

        Returns:
            dict: {movie_id: hybrid_score (0-1)}
        """
        hybrid = {}

        for movie_id in candidate_ids:
            cf_s = cf_scores.get(movie_id)
            c_s = content_scores.get(movie_id)

            if cf_s is not None and c_s is not None:
                # Both available: weighted blend
                score = (cf_weight * cf_s) + (content_weight * c_s)
            elif cf_s is not None:
                score = cf_s * 0.8
            elif c_s is not None:
                score = c_s * 0.8
            else:
                # Neither engine scored this movie → use popularity
                score = 0.1  # Small baseline so it can still appear

            hybrid[movie_id] = score

        return hybrid

    # ----------------------------------------------------------
    # POST-PROCESSING PIPELINE
    # ----------------------------------------------------------
    def _post_process(self, scores, user, limit):
        """
        Apply filters and diversity adjustments to raw scores.

        1. Genre diversity: prevent recommending 10 films of same genre
        2. Era diversity: mix old classics with new releases
        3. Popularity floor: occasionally surface hidden gems

        Returns:
            dict of top {movie_id: score}, limited to `limit` entries
        """
        from movies.models import Movie

        if not scores:
            return {}

        # Sort by score descending
        sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # Fetch genre data for top candidates (for diversity check)
        top_candidate_ids = [mid for mid, _ in sorted_items[:limit * 3]]
        genre_map = defaultdict(list)  # {movie_id: [genre_names]}

        movies_with_genres = Movie.objects.filter(
            id__in=top_candidate_ids
        ).prefetch_related('genres')

        for movie in movies_with_genres:
            genre_map[movie.id] = [g.name for g in movie.genres.all()]

        # Diversity-aware selection
        selected = {}
        genre_counts = defaultdict(int)
        MAX_PER_GENRE = 4  # Don't recommend more than 4 films of same genre

        for movie_id, score in sorted_items:
            if len(selected) >= limit:
                break

            movie_genres = genre_map.get(movie_id, [])

            # Check genre diversity constraint
            over_represented = any(
                genre_counts[g] >= MAX_PER_GENRE
                for g in movie_genres
            )

            if over_represented:
                # Still include but with reduced score (diversity penalty)
                score *= 0.7

            selected[movie_id] = score

            # Update genre counts
            for genre in movie_genres:
                genre_counts[genre] += 1

        return selected

    # ----------------------------------------------------------
    # EXPLANATION GENERATION
    # ----------------------------------------------------------
    def _generate_recommendations_with_reasons(self, user, scores, num_recs):
        """
        Convert raw scores into Recommendation dicts with human-readable reasons.

        Reason logic:
        - If user rated director ≥ 8: "Because you love [Director]"
        - If genres match preferences: "Matches your [Genre] taste"
        - If similar user liked it: "Users like you loved this"
        - If highly rated globally: "Critically acclaimed"
        - Default: "Because you watched [Movie]"

        Returns:
            list of dicts: [{movie_id, score, rank, reason_code, reason_text, source_movie_id}]
        """
        from movies.models import Movie, MovieCrew
        from interactions.models import Rating

        # Get user's highly rated directors (for director-based reasons)
        high_rated = Rating.objects.filter(
            user=user, score__gte=8.0
        ).select_related('movie')

        liked_directors = set()
        liked_genres = set()
        for rating in high_rated:
            directors = MovieCrew.objects.filter(
                movie=rating.movie, job='Director'
            ).values_list('person__name', flat=True)
            liked_directors.update(directors)
            liked_genres.update(rating.movie.genres.values_list('name', flat=True))

        # User's preferred genres from profile
        try:
            profile_genres = set(user.profile.get_genre_names())
            liked_genres.update(profile_genres)
        except Exception:
            pass

        # Sort by score and take top num_recs
        sorted_recs = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:num_recs]

        recommendations = []
        for rank, (movie_id, score) in enumerate(sorted_recs, start=1):
            try:
                movie = Movie.objects.prefetch_related('genres').get(id=movie_id)
            except Movie.DoesNotExist:
                continue

            movie_genres = set(movie.genres.values_list('name', flat=True))
            movie_directors = set(
                MovieCrew.objects.filter(
                    movie=movie, job='Director'
                ).values_list('person__name', flat=True)
            )

            # Determine best reason for this recommendation
            reason_code, reason_text, source_movie_id = self._pick_reason(
                user, movie, movie_genres, movie_directors,
                liked_directors, liked_genres, score
            )

            recommendations.append({
                'movie_id': movie_id,
                'score': score,
                'rank': rank,
                'reason_code': reason_code,
                'reason_text': reason_text,
                'source_movie_id': source_movie_id,
            })

        return recommendations

    def _pick_reason(self, user, movie, movie_genres, movie_directors,
                     liked_directors, liked_genres, score):
        """
        Pick the most relevant reason for a recommendation.
        Returns: (reason_code, reason_text, source_movie_id)
        """
        from interactions.models import Rating

        # Reason 1: Director match
        matching_directors = movie_directors & liked_directors
        if matching_directors:
            director_name = list(matching_directors)[0]
            return (
                'director_fan',
                f"Because you enjoy {director_name}'s films",
                None
            )

        # Reason 2: Genre match with preference
        matching_genres = movie_genres & liked_genres
        if matching_genres:
            genre_name = list(matching_genres)[0]
            return (
                'genre_match',
                f"Matches your taste for {genre_name}",
                None
            )

        # Reason 3: Source from a movie they loved
        try:
            from recommendations.models import SimilarMovie
            top_rating = Rating.objects.filter(
                user=user, score__gte=8.0
            ).order_by('-score').first()

            if top_rating:
                is_similar = SimilarMovie.objects.filter(
                    movie=top_rating.movie,
                    similar_movie=movie
                ).exists()
                if is_similar:
                    return (
                        'watched_similar',
                        f"Because you loved {top_rating.movie.title}",
                        top_rating.movie_id
                    )
        except Exception:
            pass

        # Reason 4: Highly rated globally
        if movie.vote_average >= 8.0 and movie.vote_count >= 1000:
            return (
                'highly_rated',
                f"Critically acclaimed · {movie.vote_average:.1f}/10 on TMDB",
                None
            )

        # Reason 5: Trending
        if movie.popularity >= 100:
            return (
                'trending',
                "Trending right now",
                None
            )

        # Default
        return (
            'users_like_you',
            "Recommended based on your taste profile",
            None
        )

    # ----------------------------------------------------------
    # DATABASE WRITE
    # ----------------------------------------------------------
    def _save_to_database(self, user, recommendations, algorithm,
                          cf_weight, content_weight):
        """
        Write recommendation results to PostgreSQL.

        Creates:
          1. RecommendationBatch (metadata about this run)
          2. Recommendation (one per movie) linked to the batch

        Old recommendations for this user are deleted first to
        keep the table clean (only latest batch matters for UI).

        Returns:
            RecommendationBatch instance
        """
        from recommendations.models import Recommendation, RecommendationBatch
        from django.db import transaction

        with transaction.atomic():
            # Delete old recommendations for this user
            Recommendation.objects.filter(user=user).delete()
            RecommendationBatch.objects.filter(user=user).delete()

            # Calculate expiry time from settings
            cache_ttl = self._settings['CACHE_TTL_SECONDS']
            expires_at = timezone.now() + timedelta(seconds=cache_ttl)

            # Create the batch record
            batch = RecommendationBatch.objects.create(
                user=user,
                algorithm_used=algorithm,
                num_recommendations=len(recommendations),
                cf_weight_used=cf_weight if cf_weight > 0 else None,
                content_weight_used=content_weight if content_weight > 0 else None,
                ratings_available=user.total_ratings,
                expires_at=expires_at,
            )

            # Bulk-create all Recommendation records
            rec_objects = [
                Recommendation(
                    user=user,
                    movie_id=rec['movie_id'],
                    batch=batch,
                    score=rec['score'],
                    rank=rec['rank'],
                    reason_code=rec['reason_code'],
                    reason_text=rec['reason_text'],
                    source_movie_id=rec.get('source_movie_id'),
                )
                for rec in recommendations
            ]
            Recommendation.objects.bulk_create(rec_objects)

        logger.info(
            f"Saved batch {batch.id} for {user.username}: "
            f"{len(recommendations)} recs, algorithm={algorithm}"
        )
        return batch

    # ----------------------------------------------------------
    # UTILITY: Get current recs for a user (for views)
    # ----------------------------------------------------------
    def get_recommendations_for_user(self, user, regenerate_if_stale=True):
        """
        Get a user's current recommendations from the database.

        If recs are stale (expired) or missing, regenerates them first.
        This is what views/API endpoints call.

        Returns:
            QuerySet of Recommendation objects with movie data
        """
        from recommendations.models import Recommendation, RecommendationBatch

        # Check if we have a fresh batch
        try:
            latest_batch = RecommendationBatch.objects.filter(user=user).latest()
            if regenerate_if_stale and latest_batch.is_stale:
                logger.info(f"Stale recommendations for {user.username} — regenerating")
                self.generate_for_user(user)
        except RecommendationBatch.DoesNotExist:
            # No recommendations yet → generate now
            logger.info(f"No recommendations for {user.username} — generating first batch")
            self.generate_for_user(user)

        # Return fresh recommendations with related movie data
        return Recommendation.objects.filter(user=user).select_related(
            'movie',
            'source_movie'
        ).prefetch_related(
            'movie__genres',
            'movie__streaming_links'
        ).order_by('rank')

    def get_trending_movies(self, limit=20):
        """
        Get globally trending movies (not personalized).
        Used for the home page hero and unauthenticated users.
        """
        from movies.models import Movie
        return Movie.objects.filter(
            status='Released',
            adult=False,
            vote_count__gte=100
        ).order_by('-popularity')[:limit]

    def get_top_rated_movies(self, limit=20):
        """Get highest-rated movies for the 'Acclaimed' section."""
        from movies.models import Movie
        return Movie.objects.filter(
            status='Released',
            adult=False,
            vote_count__gte=500,
            vote_average__gte=7.5
        ).order_by('-vote_average')[:limit]
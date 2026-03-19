"""
============================================================
CineMatch - Content-Based Filtering Engine
(recommendations/content_engine.py)
============================================================

WHAT IS CONTENT-BASED FILTERING?
  "Because you liked Inception (Sci-Fi, Christopher Nolan,
   mind-bending, heist) → recommend Interstellar (Sci-Fi,
   Christopher Nolan, space, time)"

  It compares MOVIE FEATURES to find similar movies.
  It does NOT need other users' data — works from Day 1.

HOW IT WORKS (Step by Step):
  1. BUILD FEATURE SOUP
     For each movie, combine:
       genres + director name + top cast + keywords
     into a single text string called a "soup".
     Example: "action thriller christopher_nolan cillian_murphy
               heist time_travel psychological"

  2. TF-IDF VECTORIZATION
     TF-IDF (Term Frequency-Inverse Document Frequency) converts
     each soup string into a numerical vector.
     - "action" appearing in 500/1000 movies → low weight (common)
     - "christopher_nolan" in 10/1000 movies → high weight (rare, distinctive)

  3. COSINE SIMILARITY
     Measure the angle between two movie vectors.
     Score = 1.0 → identical movies
     Score = 0.0 → completely different movies

  4. STORE RESULTS
     Top 20 similar movies per movie → SimilarMovie table
     Also store content_vector on Movie for user-level scoring

NVIDIA'S RECOMMENDATION GUIDE NOTES:
  Content-based filtering is strongest when:
  - User data is sparse (new users)
  - Long-tail content needs exposure
  - Real-time "more like this" is needed

CONNECTIONS:
  ContentEngine.build_feature_matrix()
    → reads Movie, Genre, Person, MovieCast, MovieCrew
  ContentEngine.compute_all_similarities()
    → writes SimilarMovie table
  ContentEngine.get_similar_movies(movie_id)
    → reads SimilarMovie table (fast, pre-computed)
  ContentEngine.score_movies_for_user(user)
    → used by HybridEngine (recommendations/engine.py)
============================================================
"""

import numpy as np
import pandas as pd
import logging
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity, linear_kernel
from django.db import transaction
from django.conf import settings

logger = logging.getLogger(__name__)


class ContentEngine:
    """
    Content-Based Filtering engine for CineMatch.

    Builds TF-IDF vectors from movie metadata and computes
    cosine similarity between all movie pairs.

    Usage:
        engine = ContentEngine()
        engine.fit()                           # Build vectors from DB
        similar = engine.get_similar(movie_id) # Get similar movie IDs
        scores = engine.score_for_user(user)   # Score all movies for a user
    """

    def __init__(self):
        # TF-IDF vectorizer — converts text soups to feature vectors
        # max_features=5000: cap vocabulary size for performance
        # ngram_range=(1,2): include single words AND pairs ("science fiction")
        # min_df=2: ignore terms appearing in fewer than 2 movies (too rare)
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 2),
            min_df=2,
            stop_words='english',
            analyzer='word',
        )

        # Internal state — set after fit() is called
        self.tfidf_matrix = None        # Shape: (n_movies, n_features)
        self.movie_ids = []             # List of DB movie IDs (index matches matrix rows)
        self.movie_id_to_idx = {}       # Dict: movie_id → row index in matrix
        self.is_fitted = False

    # ----------------------------------------------------------
    # STEP 1: BUILD FEATURE SOUPS
    # ----------------------------------------------------------
    def _build_feature_soup(self, movie_data):
        """
        Combine all movie metadata into a single text 'soup' string.

        The soup is what TF-IDF will vectorize.
        We repeat important features (genre, director) to give them
        more weight in the final vector.

        Args:
            movie_data: dict with keys: genres, director, cast, keywords,
                        original_language, release_decade

        Returns:
            str: the soup string

        Example output:
            "action action thriller thriller christopher_nolan
             christopher_nolan leonardo_dicaprio joseph_gordon_levitt
             heist dream subconscious time"
        """
        parts = []

        # --- Genres (repeated 3x for higher weight) ---
        for genre in movie_data.get('genres', []):
            # Replace spaces with underscores so "Science Fiction" → "science_fiction"
            clean = genre.lower().replace(' ', '_').replace('-', '_')
            parts.extend([clean] * 3)  # 3x weight

        # --- Director (repeated 3x — director style is strong signal) ---
        for director in movie_data.get('directors', []):
            clean = director.lower().replace(' ', '_')
            parts.extend([clean] * 3)

        # --- Top Cast (repeated 2x) ---
        for actor in movie_data.get('cast', [])[:5]:  # Top 5 actors only
            clean = actor.lower().replace(' ', '_')
            parts.extend([clean] * 2)

        # --- Keywords (1x — topic signals) ---
        for keyword in movie_data.get('keywords', []):
            clean = keyword.lower().replace(' ', '_')
            parts.append(clean)

        # --- Language (1x) ---
        lang = movie_data.get('original_language', 'en')
        parts.append(f"lang_{lang}")

        # --- Release Decade (1x — era preference) ---
        year = movie_data.get('release_year')
        if year:
            decade = (year // 10) * 10
            parts.append(f"decade_{decade}s")

        return ' '.join(parts)

    def _load_movie_data(self):
        """
        Load all movie features from the database into a DataFrame.

        Optimized with select_related and prefetch_related to avoid
        N+1 query problems (fetching cast/genres one movie at a time).

        Returns:
            pd.DataFrame with columns: movie_id, soup
        """
        # Import here to avoid circular imports at module level
        from movies.models import Movie

        logger.info("Loading movie features from database...")

        # Efficient query: get everything in 3 DB calls (not 1 per movie)
        movies = Movie.objects.prefetch_related(
            'genres',
            'cast',          # Through MovieCast
            'crew',          # Through MovieCrew
        ).filter(
            status='Released'   # Only released movies
        ).values(
            'id',
            'title',
            'original_language',
            'release_year',
            'keywords',
            'vote_average',
            'popularity',
        )

        rows = []
        for movie in movies:
            movie_id = movie['id']

            # Get genres for this movie
            genres = list(
                Movie.objects.get(id=movie_id).genres.values_list('name', flat=True)
            )

            # Get directors
            from movies.models import MovieCrew
            directors = list(
                MovieCrew.objects.filter(
                    movie_id=movie_id,
                    job='Director'
                ).values_list('person__name', flat=True)
            )

            # Get top cast
            from movies.models import MovieCast
            cast = list(
                MovieCast.objects.filter(
                    movie_id=movie_id
                ).order_by('order').values_list('person__name', flat=True)[:5]
            )

            # Build the soup string
            soup = self._build_feature_soup({
                'genres': genres,
                'directors': directors,
                'cast': cast,
                'keywords': movie.get('keywords', []),
                'original_language': movie.get('original_language', 'en'),
                'release_year': movie.get('release_year'),
            })

            rows.append({
                'movie_id': movie_id,
                'soup': soup,
                'vote_average': movie.get('vote_average', 0),
                'popularity': movie.get('popularity', 0),
            })

        logger.info(f"Loaded {len(rows)} movies for content engine")
        return pd.DataFrame(rows)

    # ----------------------------------------------------------
    # STEP 2: FIT THE VECTORIZER
    # ----------------------------------------------------------
    def fit(self, movie_df=None):
        """
        Build the TF-IDF matrix from movie feature soups.

        This is the "training" step for content-based filtering.
        Should be called:
        - On first deployment
        - When new movies are added (via management command)
        - NOT on every user request (too slow)

        Args:
            movie_df: optional DataFrame (for testing). If None, loads from DB.

        After fit():
            self.tfidf_matrix → (n_movies × n_features) sparse matrix
            self.movie_ids    → list of movie DB IDs (index = row in matrix)
            self.is_fitted    → True
        """
        if movie_df is None:
            movie_df = self._load_movie_data()

        if movie_df.empty:
            logger.warning("No movies found — content engine not fitted")
            return self

        # Store the ordered list of movie IDs (critical for index mapping)
        self.movie_ids = movie_df['movie_id'].tolist()
        self.movie_id_to_idx = {mid: idx for idx, mid in enumerate(self.movie_ids)}

        # Fit TF-IDF on all soups and transform to matrix
        # tfidf_matrix[i] = feature vector for movie at index i
        logger.info(f"Fitting TF-IDF on {len(self.movie_ids)} movies...")
        soups = movie_df['soup'].fillna('').tolist()
        self.tfidf_matrix = self.vectorizer.fit_transform(soups)

        # Store popularity scores for use in scoring
        self.popularity_scores = dict(zip(
            movie_df['movie_id'].tolist(),
            movie_df['popularity'].tolist()
        ))
        self.vote_scores = dict(zip(
            movie_df['movie_id'].tolist(),
            movie_df['vote_average'].tolist()
        ))

        self.is_fitted = True
        logger.info(
            f"Content engine fitted. Matrix shape: {self.tfidf_matrix.shape}. "
            f"Vocabulary size: {len(self.vectorizer.vocabulary_)}"
        )
        return self

    # ----------------------------------------------------------
    # STEP 3: COMPUTE SIMILARITIES
    # ----------------------------------------------------------
    def get_similar_movie_ids(self, movie_id, top_n=20):
        """
        Find the top_n most similar movies to a given movie.

        Uses cosine similarity between TF-IDF vectors.

        Args:
            movie_id: database Movie.id
            top_n: how many similar movies to return

        Returns:
            List of (movie_id, similarity_score) tuples, sorted by score desc
            Example: [(42, 0.87), (107, 0.81), (55, 0.79), ...]
        """
        if not self.is_fitted:
            raise RuntimeError("ContentEngine must be fitted before use. Call fit() first.")

        if movie_id not in self.movie_id_to_idx:
            logger.warning(f"Movie ID {movie_id} not found in content engine index")
            return []

        idx = self.movie_id_to_idx[movie_id]

        # Compute cosine similarity between this movie and ALL others
        # linear_kernel is faster than cosine_similarity for TF-IDF
        # (equivalent because TF-IDF vectors are L2-normalized)
        movie_vector = self.tfidf_matrix[idx]           # Shape: (1, n_features)
        sim_scores = linear_kernel(movie_vector, self.tfidf_matrix).flatten()
        # sim_scores[i] = similarity between movie and movie at index i

        # Sort by score descending, exclude the movie itself (score = 1.0)
        ranked_indices = np.argsort(sim_scores)[::-1]

        results = []
        for i in ranked_indices:
            if i == idx:
                continue  # Skip the movie itself
            if len(results) >= top_n:
                break
            results.append((self.movie_ids[i], float(sim_scores[i])))

        return results

    def compute_all_similarities(self, top_n=20, batch_size=100):
        """
        Pre-compute and store top-N similar movies for ALL movies in DB.

        This is called by:
          python manage.py compute_similarities

        Writes results to the SimilarMovie table.
        Runs in batches to avoid memory issues with large catalogs.

        Args:
            top_n: similar movies to store per movie
            batch_size: movies to process per DB write batch
        """
        if not self.is_fitted:
            raise RuntimeError("Call fit() before compute_all_similarities()")

        from recommendations.models import SimilarMovie
        from movies.models import Movie, MovieCrew

        logger.info(f"Computing similarities for {len(self.movie_ids)} movies...")

        # Compute full similarity matrix in chunks to manage memory
        # Full matrix for 10,000 movies = 10,000 × 10,000 = 100M floats ≈ 800MB
        # We process in batches instead
        total = len(self.movie_ids)
        created_count = 0

        with transaction.atomic():
            # Clear existing similarity data
            SimilarMovie.objects.all().delete()
            logger.info("Cleared existing similarity data")

            batch_records = []

            for i, movie_id in enumerate(self.movie_ids):
                similar = self.get_similar_movie_ids(movie_id, top_n=top_n)

                # Fetch metadata for explainability fields (shared genres, cast, director)
                movie_obj = Movie.objects.prefetch_related('genres', 'cast').get(id=movie_id)
                movie_genres = set(movie_obj.genres.values_list('name', flat=True))
                movie_cast = set(movie_obj.cast.values_list('name', flat=True))
                movie_directors = set(
                    MovieCrew.objects.filter(movie_id=movie_id, job='Director')
                    .values_list('person__name', flat=True)
                )

                for sim_movie_id, score in similar:
                    if score < 0.01:
                        continue  # Skip near-zero similarities

                    # Fetch similar movie metadata
                    try:
                        sim_obj = Movie.objects.prefetch_related('genres', 'cast').get(id=sim_movie_id)
                    except Movie.DoesNotExist:
                        continue

                    sim_genres = set(sim_obj.genres.values_list('name', flat=True))
                    sim_cast = set(sim_obj.cast.values_list('name', flat=True))
                    sim_directors = set(
                        MovieCrew.objects.filter(movie_id=sim_movie_id, job='Director')
                        .values_list('person__name', flat=True)
                    )

                    batch_records.append(SimilarMovie(
                        movie_id=movie_id,
                        similar_movie_id=sim_movie_id,
                        similarity_score=score,
                        shared_genres=list(movie_genres & sim_genres),
                        shared_cast=list(movie_cast & sim_cast),
                        same_director=bool(movie_directors & sim_directors),
                    ))

                # Write to DB in batches
                if len(batch_records) >= batch_size * top_n:
                    SimilarMovie.objects.bulk_create(batch_records, ignore_conflicts=True)
                    created_count += len(batch_records)
                    batch_records = []
                    logger.info(f"  Progress: {i + 1}/{total} movies processed")

            # Write remaining records
            if batch_records:
                SimilarMovie.objects.bulk_create(batch_records, ignore_conflicts=True)
                created_count += len(batch_records)

        logger.info(f"Similarity computation complete. {created_count} SimilarMovie records created.")

    # ----------------------------------------------------------
    # STEP 4: SCORE MOVIES FOR A USER
    # ----------------------------------------------------------
    def score_movies_for_user(self, user, candidate_movie_ids=None):
        """
        Score all candidate movies for a user based on content similarity
        to their liked movies (high-rated + watched).

        This is the CONTENT-BASED part of the hybrid recommendation.

        Algorithm:
          1. Get movies user rated ≥ 7/10 OR watched
          2. For each liked movie, get its TF-IDF vector
          3. Average all liked-movie vectors → user's "taste profile" vector
          4. Compute cosine similarity between taste profile and all candidates
          5. Return scores dict: {movie_id: content_score}

        Args:
            user: User model instance
            candidate_movie_ids: list of movie IDs to score (None = all movies)

        Returns:
            dict: {movie_id: float score (0-1)}
        """
        if not self.is_fitted:
            raise RuntimeError("Call fit() first")

        # --- Build user's "taste profile" from their liked movies ---
        liked_movie_ids = self._get_user_liked_movie_ids(user)

        if not liked_movie_ids:
            # No liked movies → fall back to popularity-based scoring
            logger.info(f"No liked movies for {user.username} — using popularity scores")
            return self._popularity_scores(candidate_movie_ids)

        # Get TF-IDF vectors for all liked movies
        liked_vectors = []
        for movie_id in liked_movie_ids:
            if movie_id in self.movie_id_to_idx:
                idx = self.movie_id_to_idx[movie_id]
                liked_vectors.append(self.tfidf_matrix[idx])

        if not liked_vectors:
            return self._popularity_scores(candidate_movie_ids)

        # Stack liked movie vectors and compute their mean
        # Mean vector = user's taste profile in feature space
        import scipy.sparse as sp
        if len(liked_vectors) > 1:
            stacked = sp.vstack(liked_vectors)
            taste_profile = stacked.mean(axis=0)  # Shape: (1, n_features)
        else:
            taste_profile = liked_vectors[0]

        # Compute similarity between taste profile and all candidate movies
        if candidate_movie_ids:
            # Score only specific candidates
            candidate_indices = [
                self.movie_id_to_idx[mid]
                for mid in candidate_movie_ids
                if mid in self.movie_id_to_idx
            ]
            if not candidate_indices:
                return {}
            candidate_matrix = self.tfidf_matrix[candidate_indices]
            sim_scores = linear_kernel(taste_profile, candidate_matrix).flatten()

            return {
                candidate_movie_ids[i]: float(sim_scores[i])
                for i in range(len(candidate_indices))
            }
        else:
            # Score all movies
            sim_scores = linear_kernel(taste_profile, self.tfidf_matrix).flatten()
            return {
                self.movie_ids[i]: float(sim_scores[i])
                for i in range(len(self.movie_ids))
            }

    def _get_user_liked_movie_ids(self, user):
        """
        Get IDs of movies the user has expressed positive interest in.

        Positive signals (strongest to weakest):
          1. Rated ≥ 7/10 (explicit positive)
          2. Watched (marked as watched)
          3. Watchlisted (intent to watch)
        """
        from interactions.models import Rating, WatchEvent, WatchlistItem

        liked_ids = set()

        # High ratings (≥ 7/10)
        high_ratings = Rating.objects.filter(
            user=user, score__gte=7.0
        ).values_list('movie_id', flat=True)
        liked_ids.update(high_ratings)

        # Watched movies (implicit positive)
        watched = WatchEvent.objects.filter(
            user=user
        ).values_list('movie_id', flat=True)
        liked_ids.update(watched)

        # Watchlisted (weaker signal, include if few others)
        if len(liked_ids) < 3:
            watchlisted = WatchlistItem.objects.filter(
                user=user
            ).values_list('movie_id', flat=True)
            liked_ids.update(watchlisted)

        return list(liked_ids)

    def _popularity_scores(self, candidate_movie_ids=None):
        """
        Fallback scoring based on TMDB popularity + vote_average.
        Used for cold-start (new users with no history).

        Returns normalized scores (0-1).
        """
        if not self.popularity_scores:
            return {}

        if candidate_movie_ids:
            raw = {
                mid: self.popularity_scores.get(mid, 0)
                for mid in candidate_movie_ids
            }
        else:
            raw = dict(self.popularity_scores)

        if not raw:
            return {}

        # Normalize to 0-1 range
        max_pop = max(raw.values()) or 1
        return {mid: score / max_pop for mid, score in raw.items()}

    # ----------------------------------------------------------
    # UTILITY: Get pre-computed similar movies (fast DB lookup)
    # ----------------------------------------------------------
    def get_similar_movies_from_db(self, movie_id, top_n=10, exclude_ids=None):
        """
        Fast lookup of pre-computed similar movies from SimilarMovie table.

        This is what the movie detail page "More Like This" section calls.
        Much faster than computing similarity on the fly.

        Args:
            movie_id: Movie DB ID
            top_n: how many to return
            exclude_ids: movie IDs to exclude (e.g., already watched)

        Returns:
            QuerySet of Movie objects
        """
        from recommendations.models import SimilarMovie
        from movies.models import Movie

        qs = SimilarMovie.objects.filter(
            movie_id=movie_id
        ).order_by('-similarity_score')

        if exclude_ids:
            qs = qs.exclude(similar_movie_id__in=exclude_ids)

        similar_ids = list(qs.values_list('similar_movie_id', flat=True)[:top_n])

        # Preserve ordering from similarity scores
        movies = Movie.objects.filter(id__in=similar_ids)
        movie_dict = {m.id: m for m in movies}
        return [movie_dict[mid] for mid in similar_ids if mid in movie_dict]
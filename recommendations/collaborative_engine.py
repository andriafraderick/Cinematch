# recommendations/collaborative_engine.py

import logging
import numpy as np

logger = logging.getLogger(__name__)


class CollaborativeEngine:
    """
    Collaborative Filtering via SVD matrix factorization.
    Stub — full implementation requires sufficient user ratings data.
    """

    def __init__(self, n_factors=50):
        self.n_factors = n_factors
        self.is_fitted = False
        self.user_factors = None
        self.item_factors = None
        self.user_index = {}
        self.movie_index = {}
        self.movie_ids = []

    def fit(self):
        """Build user-item matrix and run SVD decomposition."""
        try:
            from interactions.models import Rating
            ratings = Rating.objects.all().select_related('user', 'movie')
            if ratings.count() < 5:
                logger.info("Not enough ratings for CF. Need at least 5.")
                self.is_fitted = False
                return self
            self._build_and_fit(ratings)
        except Exception as e:
            logger.warning(f"CF fit failed: {e}")
            self.is_fitted = False
        return self

    def _build_and_fit(self, ratings):
        from sklearn.decomposition import TruncatedSVD
        import numpy as np

        user_ids = list(set(r.user_id for r in ratings))
        movie_ids = list(set(r.movie_id for r in ratings))

        self.user_index = {uid: i for i, uid in enumerate(user_ids)}
        self.movie_index = {mid: i for i, mid in enumerate(movie_ids)}
        self.movie_ids = movie_ids

        matrix = np.zeros((len(user_ids), len(movie_ids)))
        for r in ratings:
            u = self.user_index[r.user_id]
            m = self.movie_index[r.movie_id]
            matrix[u][m] = r.score

        # Normalize by subtracting user mean
        user_means = np.true_divide(
            matrix.sum(1), (matrix != 0).sum(1).clip(min=1)
        )
        for i in range(matrix.shape[0]):
            matrix[i][matrix[i] != 0] -= user_means[i]

        n_components = min(self.n_factors, len(user_ids) - 1, len(movie_ids) - 1)
        if n_components < 1:
            self.is_fitted = False
            return

        svd = TruncatedSVD(n_components=n_components, random_state=42)
        self.user_factors = svd.fit_transform(matrix)
        self.item_factors = svd.components_.T
        self.is_fitted = True
        logger.info(f"CF fitted: {len(user_ids)} users, {len(movie_ids)} movies")

    def predict_ratings(self, user):
        """Return predicted scores dict {movie_id: score} for a user."""
        if not self.is_fitted or user.id not in self.user_index:
            return {}
        try:
            u_idx = self.user_index[user.id]
            user_vec = self.user_factors[u_idx]
            scores = self.item_factors.dot(user_vec)
            # Normalize to 0-1
            min_s, max_s = scores.min(), scores.max()
            if max_s > min_s:
                scores = (scores - min_s) / (max_s - min_s)
            return {self.movie_ids[i]: float(scores[i]) for i in range(len(self.movie_ids))}
        except Exception as e:
            logger.warning(f"CF predict failed: {e}")
            return {}

    def get_similar_users(self, user, top_n=10):
        """Return list of similar user IDs."""
        if not self.is_fitted or user.id not in self.user_index:
            return []
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            u_idx = self.user_index[user.id]
            user_vec = self.user_factors[u_idx].reshape(1, -1)
            sims = cosine_similarity(user_vec, self.user_factors)[0]
            sims[u_idx] = -1
            top_indices = sims.argsort()[::-1][:top_n]
            reverse_index = {v: k for k, v in self.user_index.items()}
            return [reverse_index[i] for i in top_indices]
        except Exception as e:
            logger.warning(f"Similar users failed: {e}")
            return []

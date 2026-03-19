def get_recommendations_for_user(user, regenerate_if_stale=True):
    """
    Public API — get recommendations for a user.
    Returns a QuerySet of Recommendation objects.
    """
    from recommendations.engine import HybridEngine
    from recommendations.models import Recommendation

    try:
        engine = HybridEngine.get_instance()

        if regenerate_if_stale:
            batch = engine.get_recommendations_for_user(user)
        
        return Recommendation.objects.filter(
            user=user
        ).select_related('movie').prefetch_related(
            'movie__genres'
        ).order_by('rank')

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"get_recommendations_for_user failed: {e}")
        from recommendations.models import Recommendation
        return Recommendation.objects.none()


def get_similar_movies(movie, top_n=10):
    """
    Public API — get similar movies for a given movie.
    Returns a list of Movie objects.
    """
    from recommendations.models import SimilarMovie
    from movies.models import Movie

    try:
        similar_ids = SimilarMovie.objects.filter(
            movie=movie
        ).order_by('-similarity_score').values_list(
            'similar_movie_id', flat=True
        )[:top_n]

        movies = Movie.objects.filter(id__in=similar_ids)
        movie_dict = {m.id: m for m in movies}
        return [movie_dict[mid] for mid in similar_ids if mid in movie_dict]

    except Exception:
        return []


def trigger_recs_update(user):
    """
    Public API — force regeneration of recommendations for a user.
    """
    try:
        from recommendations.tasks import generate_recommendations_for_user
        return generate_recommendations_for_user(user)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"trigger_recs_update failed: {e}")
        return None
"""
============================================================
CineMatch - API Views (api/views.py)
============================================================

This is the CONTROLLER LAYER — where HTTP requests become
database operations and JSON responses.

ARCHITECTURE:
  URL Request
    → urls.py routes to a ViewSet
      → permission classes check auth
        → view logic runs
          → serializer validates/formats
            → response returned as JSON

VIEWSET OVERVIEW:
  ┌──────────────────────────────────────────────────┐
  │ AUTH                                              │
  │   AuthViewSet       /api/v1/auth/*               │
  │     register        POST  /auth/register/        │
  │     login           POST  /auth/login/           │
  │     logout          POST  /auth/logout/          │
  │     me              GET   /auth/me/              │
  │     profile         PUT   /auth/profile/         │
  │     onboarding      POST  /auth/onboarding/      │
  │     token_refresh   POST  /auth/token/refresh/   │
  ├──────────────────────────────────────────────────┤
  │ MOVIES                                            │
  │   MovieViewSet      /api/v1/movies/*             │
  │     list            GET   /movies/               │
  │     retrieve        GET   /movies/{id}/          │
  │     search          GET   /movies/?search=...    │
  │     trending        GET   /movies/trending/      │
  │     top_rated       GET   /movies/top_rated/     │
  │     by_genre        GET   /movies/genre/{slug}/  │
  │     similar         GET   /movies/{id}/similar/  │
  │     rate            POST  /movies/{id}/rate/     │
  │     record_view     POST  /movies/{id}/viewed/   │
  │   GenreViewSet      /api/v1/genres/*             │
  ├──────────────────────────────────────────────────┤
  │ INTERACTIONS                                      │
  │   WatchlistViewSet  /api/v1/watchlist/*          │
  │     list            GET   /watchlist/            │
  │     create          POST  /watchlist/            │
  │     destroy         DELETE /watchlist/{id}/      │
  │   WatchedViewSet    /api/v1/watched/*            │
  │     list            GET   /watched/              │
  │     create          POST  /watched/              │
  │   RatingViewSet     /api/v1/ratings/*            │
  │     list            GET   /ratings/              │
  ├──────────────────────────────────────────────────┤
  │ RECOMMENDATIONS                                   │
  │   RecommendationViewSet /api/v1/recommendations/ │
  │     list            GET   /recommendations/      │
  │     refresh         POST  /recommendations/refresh/│
  │   DashboardView     GET   /api/v1/dashboard/     │
  └──────────────────────────────────────────────────┘

DRF ViewSet Types Used:
  ViewSet       → Full CRUD control (manual action methods)
  ModelViewSet  → Auto-generates list/create/retrieve/update/destroy
  GenericAPIView → Single-purpose views

HOW JWT TOKENS WORK:
  1. POST /auth/login/ → returns access_token + refresh_token
  2. Client stores tokens (localStorage or HttpOnly cookie)
  3. Client sends: Authorization: Bearer <access_token>
  4. DRF JWTAuthentication decodes token → gets user
  5. Access token expires in 2 hours → use refresh token to get new one
============================================================
"""

import logging
from django.utils import timezone
from django.db.models import Avg, Count
from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from users.models import User, UserProfile
from movies.models import Genre, Movie, StreamingLink
from interactions.models import Rating, WatchlistItem, WatchEvent, ViewHistory
from recommendations.models import Recommendation, RecommendationBatch

from api.serializers import (
    RegisterSerializer, LoginSerializer, UserDetailSerializer,
    OnboardingSerializer, UpdateProfileSerializer,
    GenreSerializer, MovieListSerializer, MovieDetailSerializer,
    RatingSerializer, WatchlistSerializer, WatchEventSerializer,
    ViewHistorySerializer, RecommendationSerializer,
    SimilarMovieSerializer, DashboardSerializer,
)
from api.permissions import IsOwnerOrReadOnly, IsOnboarded, IsSelfOrAdmin
from api.pagination import (
    StandardPagination, SmallPagination, LargePagination,
    RecommendationPagination
)
from api.filters import MovieFilter

logger = logging.getLogger(__name__)


# ============================================================
# ── HELPER: Generate JWT tokens for a user ───────────────────
# ============================================================
def get_tokens_for_user(user):
    """
    Generate a JWT access + refresh token pair for a user.

    SimpleJWT tokens encode the user ID. They're stateless —
    no DB lookup needed to verify them (just signature check).

    Returns dict to be merged into API response:
      { "access": "eyJ...", "refresh": "eyJ..." }
    """
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


# ============================================================
# ── AUTH VIEWSET ──────────────────────────────────────────────
# ============================================================
class AuthViewSet(viewsets.ViewSet):
    """
    Authentication endpoints — register, login, profile management.

    All @action methods become sub-routes via the DRF router:
      router.register('auth', AuthViewSet, basename='auth')
      → /api/v1/auth/register/
      → /api/v1/auth/login/
      → /api/v1/auth/me/
      etc.
    """

    # ----------------------------------------------------------
    # REGISTER
    # ----------------------------------------------------------
    @action(
        detail=False,
        methods=['POST'],
        permission_classes=[AllowAny],
        url_path='register'
    )
    def register(self, request):
        """
        Create a new user account.

        POST /api/v1/auth/register/
        Body: { email, username, password, password_confirm, full_name? }

        Returns:
          201: { user data, access token, refresh token }
          400: { field errors }

        After registration:
        - User is created
        - UserProfile is auto-created via signal
        - JWT tokens are issued immediately (no need to log in separately)
        - User is directed to onboarding (is_onboarded=False)
        """
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create the user (signals auto-create UserProfile)
        user = serializer.save()

        # Issue JWT tokens immediately
        tokens = get_tokens_for_user(user)

        # Update last_seen
        user.last_seen = timezone.now()
        user.save(update_fields=['last_seen'])

        logger.info(f"New user registered: {user.username} ({user.email})")

        return Response({
            'message': 'Account created successfully! Please complete your preferences.',
            'user': UserDetailSerializer(user, context={'request': request}).data,
            **tokens,
        }, status=status.HTTP_201_CREATED)

    # ----------------------------------------------------------
    # LOGIN
    # ----------------------------------------------------------
    @action(
        detail=False,
        methods=['POST'],
        permission_classes=[AllowAny],
        url_path='login'
    )
    def login(self, request):
        """
        Authenticate and return JWT tokens.

        POST /api/v1/auth/login/
        Body: { email, password }

        Returns:
          200: { user data, access token, refresh token }
          400: { error message }

        The access token is valid for 2 hours.
        The refresh token is valid for 7 days.
        Use /auth/token/refresh/ to get a new access token.
        """
        serializer = LoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        tokens = get_tokens_for_user(user)

        # Track last activity
        user.last_seen = timezone.now()
        user.save(update_fields=['last_seen'])

        logger.info(f"User logged in: {user.username}")

        return Response({
            'message': f'Welcome back, {user.username}!',
            'user': UserDetailSerializer(user, context={'request': request}).data,
            **tokens,
        }, status=status.HTTP_200_OK)

    # ----------------------------------------------------------
    # LOGOUT
    # ----------------------------------------------------------
    @action(
        detail=False,
        methods=['POST'],
        permission_classes=[IsAuthenticated],
        url_path='logout'
    )
    def logout(self, request):
        """
        Invalidate the user's refresh token.

        POST /api/v1/auth/logout/
        Body: { "refresh": "<refresh_token>" }

        SimpleJWT blacklists the refresh token so it can't be
        used to generate new access tokens.

        Note: Access tokens remain valid until they expire (2h).
        The frontend should delete them from storage immediately.
        """
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass  # Token already invalid or expired — that's fine

        return Response({'message': 'Logged out successfully.'}, status=status.HTTP_200_OK)

    # ----------------------------------------------------------
    # CURRENT USER (ME)
    # ----------------------------------------------------------
    @action(
        detail=False,
        methods=['GET'],
        permission_classes=[IsAuthenticated],
        url_path='me'
    )
    def me(self, request):
        """
        Get the currently authenticated user's full profile.

        GET /api/v1/auth/me/
        Header: Authorization: Bearer <access_token>

        Returns full user data including profile preferences and stats.
        Used by the frontend to populate the profile page and nav bar.
        """
        serializer = UserDetailSerializer(request.user, context={'request': request})
        return Response(serializer.data)

    # ----------------------------------------------------------
    # UPDATE PROFILE
    # ----------------------------------------------------------
    @action(
        detail=False,
        methods=['PUT', 'PATCH'],
        permission_classes=[IsAuthenticated],
        url_path='profile'
    )
    def profile(self, request):
        """
        Update the current user's profile.

        PUT /api/v1/auth/profile/   → full update
        PATCH /api/v1/auth/profile/ → partial update

        Body: { username?, full_name?, avatar?, preferred_genres?, streaming_services? }

        After updating genres, recommendations are regenerated.
        """
        partial = request.method == 'PATCH'
        serializer = UpdateProfileSerializer(
            request.user,
            data=request.data,
            partial=partial,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # If genres changed, regenerate recommendations
        if 'preferred_genres' in request.data:
            try:
                from recommendations.tasks import generate_recommendations_for_user
                generate_recommendations_for_user(user)
            except Exception as e:
                logger.warning(f"Failed to regenerate recs after profile update: {e}")

        return Response(
            UserDetailSerializer(user, context={'request': request}).data,
            status=status.HTTP_200_OK
        )

    # ----------------------------------------------------------
    # ONBOARDING
    # ----------------------------------------------------------
    @action(
        detail=False,
        methods=['POST'],
        permission_classes=[IsAuthenticated],
        url_path='onboarding'
    )
    def onboarding(self, request):
        """
        Complete the onboarding step: set genre preferences.

        POST /api/v1/auth/onboarding/
        Body: { "genre_ids": [28, 12, 35], "streaming_services": ["Netflix"] }

        After this:
        1. UserProfile.preferred_genres is set
        2. UserProfile.streaming_services is set
        3. User.is_onboarded = True
        4. First recommendation batch is generated using cold start
        5. Response includes first recommendations

        This endpoint can be called again to update preferences.
        """
        serializer = OnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        genre_ids = serializer.validated_data['genre_ids']
        streaming_services = serializer.validated_data.get('streaming_services', [])

        # Update profile
        profile = user.profile
        profile.preferred_genres.set(genre_ids)
        profile.streaming_services = streaming_services
        profile.save()

        # Mark user as onboarded
        user.is_onboarded = True
        user.save(update_fields=['is_onboarded'])

        # Generate first recommendations (cold start with genre prefs)
        try:
            from recommendations.tasks import generate_recommendations_for_user
            generate_recommendations_for_user(user, force_algorithm='genre')
        except Exception as e:
            logger.warning(f"Failed to generate initial recs for {user.username}: {e}")

        logger.info(f"User {user.username} completed onboarding with {len(genre_ids)} genres")

        return Response({
            'message': "Welcome to CineMatch! Your recommendations are ready.",
            'is_onboarded': True,
            'genres_set': len(genre_ids),
        }, status=status.HTTP_200_OK)


# ============================================================
# ── MOVIE VIEWSET ─────────────────────────────────────────────
# ============================================================
class MovieViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Movie catalog — read-only (movies are managed via admin/sync_tmdb).

    ReadOnlyModelViewSet provides:
      GET /api/v1/movies/      → list()    (all movies, paginated)
      GET /api/v1/movies/{id}/ → retrieve() (single movie, full detail)

    Custom @actions extend this with:
      GET /api/v1/movies/trending/
      GET /api/v1/movies/top_rated/
      GET /api/v1/movies/{id}/similar/
      POST /api/v1/movies/{id}/rate/
      POST /api/v1/movies/{id}/viewed/

    QUERY PARAMS for list():
      ?search=inception      → title search
      ?genre=28              → filter by genre ID
      ?year_min=2010         → filter by year
      ?min_rating=7.5        → filter by TMDB rating
      ?ordering=popularity   → sort field
      ?page=2                → pagination
    """
    queryset = Movie.objects.filter(
        status='Released',
        adult=False,
    ).prefetch_related('genres').select_related()

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardPagination
    filterset_class = MovieFilter

    # DRF search backend: searches across these fields
    search_fields = ['title', 'original_title', 'overview', 'genres__name']

    # Ordering options: ?ordering=popularity or ?ordering=-vote_average
    ordering_fields = ['popularity', 'vote_average', 'release_year', 'title']
    ordering = ['-popularity']  # Default ordering

    def get_serializer_class(self):
        """
        Use compact serializer for lists, full serializer for detail.
        This keeps list responses fast (fewer fields, smaller payload).
        """
        if self.action == 'retrieve':
            return MovieDetailSerializer
        return MovieListSerializer

    def get_serializer_context(self):
        """
        Add user-specific data to serializer context.

        Pre-fetch user's ratings and watchlist as dicts (O(1) lookup)
        so the serializer doesn't do N+1 queries to check each movie.
        """
        context = super().get_serializer_context()
        user = self.request.user

        if user.is_authenticated:
            # Pre-fetch as dict: {movie_id: score}
            context['user_ratings'] = dict(
                Rating.objects.filter(user=user).values_list('movie_id', 'score')
            )
            # Pre-fetch as set: {movie_id, ...}
            context['user_watchlist'] = set(
                WatchlistItem.objects.filter(user=user).values_list('movie_id', flat=True)
            )

        return context

    def retrieve(self, request, *args, **kwargs):
        """
        Get full movie detail. Also records the view (implicit signal).
        """
        instance = self.get_object()

        # Record page view as implicit interest signal
        if request.user.is_authenticated:
            try:
                ViewHistory.record_view(user=request.user, movie=instance)
            except Exception as e:
                logger.warning(f"Could not record view: {e}")

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    # ----------------------------------------------------------
    # CUSTOM ACTIONS
    # ----------------------------------------------------------
    @action(detail=False, methods=['GET'], url_path='trending')
    def trending(self, request):
        """
        Get trending movies — sorted by TMDB popularity score.
        GET /api/v1/movies/trending/

        Used for the home page hero section and 'What's Hot' carousel.
        """
        from recommendations.engine import HybridEngine
        engine = HybridEngine.get_instance()
        movies = engine.get_trending_movies(limit=20)
        serializer = MovieListSerializer(
            movies, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=False, methods=['GET'], url_path='top-rated')
    def top_rated(self, request):
        """
        Get highest-rated movies (min 500 votes, ≥7.5 rating).
        GET /api/v1/movies/top-rated/
        """
        from recommendations.engine import HybridEngine
        engine = HybridEngine.get_instance()
        movies = engine.get_top_rated_movies(limit=20)
        serializer = MovieListSerializer(
            movies, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=False, methods=['GET'], url_path='genre/(?P<slug>[^/.]+)')
    def by_genre(self, request, slug=None):
        """
        Get movies filtered by genre slug.
        GET /api/v1/movies/genre/action/
        GET /api/v1/movies/genre/science-fiction/

        Used for genre browsing pages.
        """
        try:
            genre = Genre.objects.get(slug=slug)
        except Genre.DoesNotExist:
            return Response(
                {'error': f"Genre '{slug}' not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        movies = self.get_queryset().filter(genres=genre)
        page = self.paginate_queryset(movies)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(movies, many=True)
        return Response({
            'genre': GenreSerializer(genre).data,
            'results': serializer.data,
        })

    @action(detail=True, methods=['GET'], url_path='similar')
    def similar(self, request, pk=None):
        """
        Get movies similar to this one (pre-computed similarity).
        GET /api/v1/movies/42/similar/

        Used for "More Like This" section on movie detail page.
        Returns up to 10 similar movies with similarity scores.
        """
        movie = self.get_object()
        from recommendations.models import SimilarMovie
        similar_qs = SimilarMovie.objects.filter(
            movie=movie
        ).select_related('similar_movie').prefetch_related(
            'similar_movie__genres'
        ).order_by('-similarity_score')[:10]

        serializer = SimilarMovieSerializer(
            similar_qs, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True, methods=['POST'], permission_classes=[IsAuthenticated], url_path='rate')
    def rate(self, request, pk=None):
        """
        Rate a movie (create or update rating).
        POST /api/v1/movies/42/rate/
        Body: { "score": 8.5, "review": "Great film!" }

        UPSERT behaviour:
        - First time: creates a Rating record
        - Re-rate: updates the existing Rating record
        - Both trigger a recommendation recalculation (via signal)

        Returns:
          200 (updated) or 201 (created) with rating data.
        """
        movie = self.get_object()
        serializer = RatingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        rating, created = Rating.upsert(
            user=request.user,
            movie=movie,
            score=serializer.validated_data['score'],
            review=serializer.validated_data.get('review', '')
        )

        response_serializer = RatingSerializer(rating)
        return Response(
            {
                'message': 'Rating saved.',
                'created': created,
                'rating': response_serializer.data,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    @action(
        detail=True,
        methods=['DELETE'],
        permission_classes=[IsAuthenticated],
        url_path='rate'
    )
    def delete_rating(self, request, pk=None):
        """
        Remove a rating from a movie.
        DELETE /api/v1/movies/42/rate/
        """
        movie = self.get_object()
        deleted_count, _ = Rating.objects.filter(
            user=request.user, movie=movie
        ).delete()

        if deleted_count == 0:
            return Response(
                {'error': "No rating found for this movie."},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response({'message': 'Rating removed.'}, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=['POST'],
        permission_classes=[IsAuthenticatedOrReadOnly],
        url_path='viewed'
    )
    def record_view(self, request, pk=None):
        """
        Record that the user viewed this movie's detail page (implicit signal).
        POST /api/v1/movies/42/viewed/

        This is called automatically by the frontend when a movie
        detail page is opened. It's a lightweight implicit feedback signal.
        """
        movie = self.get_object()
        try:
            ViewHistory.record_view(user=request.user, movie=movie)
        except Exception as e:
            logger.warning(f"Failed to record view: {e}")

        return Response({'recorded': True}, status=status.HTTP_200_OK)


# ============================================================
# ── GENRE VIEWSET ─────────────────────────────────────────────
# ============================================================
class GenreViewSet(viewsets.ReadOnlyModelViewSet):
    """
    List all movie genres.
    GET /api/v1/genres/       → all genres
    GET /api/v1/genres/{id}/  → single genre + movie count

    Used by the onboarding page (genre selection checkboxes)
    and the genre filter on the browse page.
    """
    queryset = Genre.objects.all().order_by('name')
    serializer_class = GenreSerializer
    permission_classes = [AllowAny]   # Genres are public data
    pagination_class = None           # Return all genres (only ~20 total)


# ============================================================
# ── WATCHLIST VIEWSET ─────────────────────────────────────────
# ============================================================
class WatchlistViewSet(viewsets.ModelViewSet):
    """
    User's watchlist management.

    GET    /api/v1/watchlist/      → user's full watchlist
    POST   /api/v1/watchlist/      → add movie to watchlist
    DELETE /api/v1/watchlist/{id}/ → remove from watchlist

    Watchlist items are private — only the owner can see/modify them.
    """
    serializer_class = WatchlistSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    pagination_class = LargePagination

    def get_queryset(self):
        """
        CRITICAL: Always filter by current user.
        Without this, users could see each other's watchlists.
        """
        return WatchlistItem.objects.filter(
            user=self.request.user
        ).select_related('movie').prefetch_related('movie__genres').order_by('-added_at')

    def perform_create(self, serializer):
        """Auto-set the user from the JWT token before saving."""
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['DELETE'], url_path='movie/(?P<movie_id>[^/.]+)')
    def remove_by_movie(self, request, movie_id=None):
        """
        Remove from watchlist by movie ID (more convenient than needing watchlist item ID).
        DELETE /api/v1/watchlist/movie/42/
        """
        deleted_count, _ = WatchlistItem.objects.filter(
            user=request.user,
            movie_id=movie_id
        ).delete()

        if deleted_count == 0:
            return Response(
                {'error': "Movie not in watchlist."},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response({'message': 'Removed from watchlist.'}, status=status.HTTP_200_OK)


# ============================================================
# ── WATCHED VIEWSET ───────────────────────────────────────────
# ============================================================
class WatchedViewSet(viewsets.ModelViewSet):
    """
    Track movies the user has actually watched.

    GET  /api/v1/watched/      → viewing history
    POST /api/v1/watched/      → mark as watched
           Body: { "movie_id": 42, "source": "Netflix", "rewatched": false }

    Marking as watched:
    1. Creates WatchEvent record
    2. Signal updates UserProfile.total_movies_watched
    3. Signal triggers recommendation recalculation
    """
    serializer_class = WatchEventSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
    pagination_class = StandardPagination

    def get_queryset(self):
        return WatchEvent.objects.filter(
            user=self.request.user
        ).select_related('movie').prefetch_related('movie__genres').order_by('-watched_at')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    # Override allowed methods (no update/delete for watch history)
    http_method_names = ['get', 'post', 'head', 'options']


# ============================================================
# ── RATING VIEWSET ────────────────────────────────────────────
# ============================================================
class RatingViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of current user's ratings.
    (Create/Update/Delete ratings via /movies/{id}/rate/)

    GET /api/v1/ratings/      → all my ratings
    GET /api/v1/ratings/{id}/ → single rating

    Used on profile page "My Ratings" section.
    """
    serializer_class = RatingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    ordering = ['-created_at']

    def get_queryset(self):
        return Rating.objects.filter(
            user=self.request.user
        ).select_related('movie').order_by('-created_at')


# ============================================================
# ── RECOMMENDATION VIEWSET ────────────────────────────────────
# ============================================================
class RecommendationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Personalized movie recommendations for the current user.

    GET  /api/v1/recommendations/         → current recommendations
    POST /api/v1/recommendations/refresh/ → force regeneration

    FLOW:
      1. View checks if user has fresh recommendations in DB
      2. If stale/missing → generates new ones via HybridEngine
      3. Returns ranked list with reason explanations

    Requires onboarding completion (IsOnboarded permission).
    New users are redirected to /auth/onboarding/ first.
    """
    serializer_class = RecommendationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = RecommendationPagination

    def get_queryset(self):
        """
        Get or generate recommendations for the current user.

        Uses HybridEngine.get_recommendations_for_user() which:
        - Returns existing if fresh (within cache TTL)
        - Regenerates if stale
        """
        from recommendations import get_recommendations_for_user
        return get_recommendations_for_user(
            self.request.user,
            regenerate_if_stale=True
        )

    def list(self, request, *args, **kwargs):
        """
        Override list to include algorithm metadata in response.
        """
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
        else:
            serializer = self.get_serializer(queryset, many=True)
            response = Response(serializer.data)

        # Add algorithm info to response
        try:
            latest_batch = RecommendationBatch.objects.filter(
                user=request.user
            ).latest()
            if hasattr(response, 'data') and isinstance(response.data, dict):
                response.data['algorithm'] = latest_batch.algorithm_used
                response.data['generated_at'] = latest_batch.generated_at
                response.data['ratings_used'] = latest_batch.ratings_available
        except RecommendationBatch.DoesNotExist:
            pass

        return response

    @action(detail=False, methods=['POST'], url_path='refresh')
    def refresh(self, request):
        """
        Force-regenerate recommendations immediately.
        POST /api/v1/recommendations/refresh/

        Called when user:
        - Rates several movies quickly and wants fresh recs
        - Returns to app after long absence
        - Completes onboarding
        """
        try:
            from recommendations.tasks import generate_recommendations_for_user
            batch = generate_recommendations_for_user(request.user)
            return Response({
                'message': 'Recommendations refreshed.',
                'count': batch.num_recommendations if batch else 0,
                'algorithm': batch.algorithm_used if batch else None,
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Failed to refresh recs for {request.user.username}: {e}")
            return Response(
                {'error': 'Could not refresh recommendations. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['POST'], url_path='clicked')
    def mark_clicked(self, request, pk=None):
        """
        Record that user clicked on a recommendation.
        POST /api/v1/recommendations/42/clicked/

        Used to track recommendation quality:
        - click-through rate per algorithm
        - which reason codes work best
        """
        try:
            rec = Recommendation.objects.get(pk=pk, user=request.user)
            rec.was_clicked = True
            rec.save(update_fields=['was_clicked'])
            return Response({'recorded': True})
        except Recommendation.DoesNotExist:
            return Response({'error': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)


# ============================================================
# ── DASHBOARD VIEW ────────────────────────────────────────────
# ============================================================
class DashboardView(generics.GenericAPIView):
    """
    Aggregate dashboard data in a SINGLE API request.

    GET /api/v1/dashboard/

    Returns everything the dashboard page needs:
      - Current user info
      - Top 10 recommendations
      - Recent watch history (5 items)
      - Watchlist (10 items)
      - Stats (total watched, avg rating, hours)
      - Genre breakdown (how many movies per genre)
      - Algorithm info (which ML model is being used)

    WHY ONE ENDPOINT?
    Instead of 5 separate requests (recs, watchlist, history, stats, user),
    the dashboard makes ONE request. This is faster and avoids waterfalls.

    Called by the main dashboard page on load.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = DashboardSerializer

    def get(self, request):
        user = request.user

        # --- Recommendations (top 10 for dashboard widget) ---
        from recommendations import get_recommendations_for_user
        recommendations = list(get_recommendations_for_user(user)[:10])

        # --- Recent watches ---
        recent_watches = list(
            WatchEvent.objects.filter(user=user)
            .select_related('movie')
            .prefetch_related('movie__genres')
            .order_by('-watched_at')[:5]
        )

        # --- Watchlist preview ---
        watchlist = list(
            WatchlistItem.objects.filter(user=user)
            .select_related('movie')
            .prefetch_related('movie__genres')
            .order_by('-added_at')[:10]
        )

        # --- Stats ---
        rating_stats = Rating.objects.filter(user=user).aggregate(
            avg_score=Avg('score'),
            total_ratings=Count('id')
        )
        stats = {
            'total_ratings': rating_stats['total_ratings'],
            'avg_rating': round(rating_stats['avg_score'] or 0, 1),
            'total_watched': user.profile.total_movies_watched,
            'total_hours': round(user.profile.total_hours_watched, 1),
            'watchlist_count': WatchlistItem.objects.filter(user=user).count(),
            'cf_eligible': user.can_use_collaborative_filtering,
        }

        # --- Genre breakdown ---
        genre_breakdown = list(
            Rating.objects.filter(user=user)
            .values('movie__genres__name')
            .annotate(count=Count('id'), avg=Avg('score'))
            .filter(movie__genres__name__isnull=False)
            .order_by('-count')[:8]
        )

        # --- Algorithm info ---
        algorithm_info = {}
        try:
            batch = RecommendationBatch.objects.filter(user=user).latest()
            algorithm_info = {
                'algorithm': batch.algorithm_used,
                'generated_at': batch.generated_at,
                'num_recommendations': batch.num_recommendations,
                'ratings_used': batch.ratings_available,
            }
        except RecommendationBatch.DoesNotExist:
            algorithm_info = {'algorithm': 'none', 'ratings_used': 0}

        # --- Serialize all data ---
        context = {'request': request}
        data = {
            'user': UserDetailSerializer(user, context=context).data,
            'recommendations': RecommendationSerializer(
                recommendations, many=True, context=context
            ).data,
            'watchlist': WatchlistSerializer(
                watchlist, many=True, context=context
            ).data,
            'recent_watches': WatchEventSerializer(
                recent_watches, many=True, context=context
            ).data,
            'stats': stats,
            'genre_breakdown': genre_breakdown,
            'algorithm_info': algorithm_info,
        }

        return Response(data, status=status.HTTP_200_OK)
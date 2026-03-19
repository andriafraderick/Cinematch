"""
============================================================
CineMatch - API Serializers (api/serializers.py)
============================================================

Serializers are the TRANSLATION LAYER between Python objects
(Django models) and JSON (what the API sends/receives).

They do TWO things:
  1. SERIALIZATION   → Model instance → Python dict → JSON (for GET)
  2. DESERIALIZATION → JSON → validated Python dict → Model save (for POST/PUT)

SERIALIZER HIERARCHY:
  ┌─────────────────────────────────────────────┐
  │ AUTH                                         │
  │   RegisterSerializer                         │
  │   LoginSerializer                            │
  │   UserProfileSerializer                      │
  │   OnboardingSerializer                       │
  ├─────────────────────────────────────────────┤
  │ MOVIES                                       │
  │   GenreSerializer                            │
  │   PersonSerializer                           │
  │   StreamingLinkSerializer                    │
  │   MovieListSerializer      (compact, for lists)│
  │   MovieDetailSerializer    (full, for detail) │
  ├─────────────────────────────────────────────┤
  │ INTERACTIONS                                 │
  │   RatingSerializer                           │
  │   WatchlistSerializer                        │
  │   WatchEventSerializer                       │
  ├─────────────────────────────────────────────┤
  │ RECOMMENDATIONS                              │
  │   RecommendationSerializer                   │
  │   SimilarMovieSerializer                     │
  └─────────────────────────────────────────────┘

KEY DRF CONCEPTS USED HERE:
  ModelSerializer      → Auto-generates fields from model
  SerializerMethodField → Computed/custom field (read-only)
  nested serializers   → Embed related object data inline
  validate_*           → Field-level validation
  validate()           → Cross-field validation
  create() / update()  → Custom save logic

CONNECTION:
  Serializers are used by → api/views.py (ViewSets)
  ViewSets are routed by  → api/urls.py (Router)
  Router registers at     → core/urls.py (/api/v1/)
============================================================
"""

from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from users.models import User, UserProfile
from movies.models import Genre, Person, Movie, MovieCast, MovieCrew, StreamingLink
from interactions.models import Rating, WatchlistItem, WatchEvent, ViewHistory
from recommendations.models import Recommendation, SimilarMovie


# ============================================================
# ── AUTH SERIALIZERS ─────────────────────────────────────────
# ============================================================

class RegisterSerializer(serializers.ModelSerializer):
    """
    Handles new user registration.

    INPUT (POST /api/v1/auth/register/):
      {
        "email": "alex@example.com",
        "username": "alex_cinema",
        "password": "SecurePass123!",
        "password_confirm": "SecurePass123!",
        "full_name": "Alex Ray"   (optional)
      }

    OUTPUT: User data + JWT tokens on success.

    VALIDATION:
      - Email uniqueness checked by model unique constraint
      - Password strength via Django's built-in validators
      - Password match checked in validate()
    """
    # Extra field not on the model — used for confirmation only
    password = serializers.CharField(
        write_only=True,          # Never include in GET responses
        required=True,
        style={'input_type': 'password'},
        help_text="Minimum 8 chars, not too common"
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'full_name', 'password', 'password_confirm']
        extra_kwargs = {
            'full_name': {'required': False},
        }

    def validate_password(self, value):
        """Run Django's built-in password validators."""
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate(self, data):
        """Cross-field validation: passwords must match."""
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({
                'password_confirm': "Passwords do not match."
            })
        return data

    def create(self, validated_data):
        """
        Create user with hashed password.
        Remove password_confirm before passing to create_user().
        """
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        user = User.objects.create_user(password=password, **validated_data)
        return user


class LoginSerializer(serializers.Serializer):
    """
    Validates login credentials.

    INPUT (POST /api/v1/auth/login/):
      { "email": "alex@example.com", "password": "SecurePass123!" }

    OUTPUT: Validated user instance (tokens added by the view).

    NOTE: We use authenticate() from Django which:
    - Checks password hash (never compares plain text)
    - Respects is_active flag
    - Runs configured authentication backends
    """
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, data):
        email = data.get('email', '').lower().strip()
        password = data.get('password', '')

        if not email or not password:
            raise serializers.ValidationError("Email and password are required.")

        # Django's authenticate() handles password hashing comparison
        user = authenticate(
            request=self.context.get('request'),
            username=email,   # Our backend uses email as username
            password=password
        )

        if not user:
            raise serializers.ValidationError(
                "No account found with these credentials."
            )
        if not user.is_active:
            raise serializers.ValidationError(
                "This account has been deactivated."
            )

        # Attach validated user to data so the view can access it
        data['user'] = user
        return data


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializes UserProfile preferences.
    Nested inside UserDetailSerializer.
    """
    preferred_genres = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Genre.objects.all(),
        required=False,
    )
    preferred_genre_names = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            'preferred_genres',
            'preferred_genre_names',
            'streaming_services',
            'preferred_language',
            'include_adult_content',
            'total_movies_watched',
            'total_hours_watched',
            'avg_rating_given',
        ]
        read_only_fields = ['total_movies_watched', 'total_hours_watched', 'avg_rating_given']

    def get_preferred_genre_names(self, obj):
        """Returns genre names alongside IDs for display."""
        return obj.get_genre_names()


class UserDetailSerializer(serializers.ModelSerializer):
    """
    Full user data — used for profile page and /api/v1/auth/me/.

    Nests UserProfile inline so the frontend gets everything
    in one request.

    OUTPUT example:
      {
        "id": 1,
        "email": "alex@example.com",
        "username": "alex_cinema",
        "avatar_url": "https://...",
        "is_onboarded": true,
        "total_ratings": 42,
        "can_use_cf": true,
        "profile": {
          "preferred_genres": [28, 12],
          "streaming_services": ["Netflix", "Prime"],
          ...
        }
      }
    """
    profile = UserProfileSerializer(read_only=True)
    avatar_url = serializers.ReadOnlyField()
    total_ratings = serializers.ReadOnlyField()
    can_use_cf = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'username', 'full_name',
            'avatar_url', 'is_onboarded', 'date_joined',
            'total_ratings', 'can_use_cf', 'profile',
        ]
        read_only_fields = ['id', 'email', 'date_joined', 'is_onboarded']

    def get_can_use_cf(self, obj):
        """Shows whether user has enough ratings for collaborative filtering."""
        return obj.can_use_collaborative_filtering


class OnboardingSerializer(serializers.Serializer):
    """
    Handles the onboarding step: user selects preferred genres
    and streaming services.

    POST /api/v1/auth/onboarding/
      {
        "genre_ids": [28, 12, 35],
        "streaming_services": ["Netflix", "Prime Video"]
      }

    After this:
    - UserProfile.preferred_genres is set
    - User.is_onboarded = True
    - First recommendation batch is generated
    """
    genre_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        max_length=10,
        help_text="List of Genre IDs user prefers (1-10 genres)"
    )
    streaming_services = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        default=list,
        help_text="e.g. ['Netflix', 'Prime Video', 'Disney+']"
    )

    def validate_genre_ids(self, value):
        """Check that all provided genre IDs actually exist."""
        existing = set(Genre.objects.filter(id__in=value).values_list('id', flat=True))
        invalid = set(value) - existing
        if invalid:
            raise serializers.ValidationError(
                f"Invalid genre IDs: {list(invalid)}"
            )
        return value


class UpdateProfileSerializer(serializers.ModelSerializer):
    """
    Allows users to update their own profile fields.
    PUT /api/v1/auth/profile/
    """
    preferred_genres = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Genre.objects.all(),
        required=False,
        source='profile.preferred_genres'
    )
    streaming_services = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        source='profile.streaming_services'
    )

    class Meta:
        model = User
        fields = ['username', 'full_name', 'avatar', 'preferred_genres', 'streaming_services']
        extra_kwargs = {
            'username': {'required': False},
            'full_name': {'required': False},
            'avatar': {'required': False},
        }

    def update(self, instance, validated_data):
        # Extract nested profile data
        profile_data = validated_data.pop('profile', {})

        # Update User fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update UserProfile fields
        profile = instance.profile
        if 'preferred_genres' in profile_data:
            profile.preferred_genres.set(profile_data['preferred_genres'])
        if 'streaming_services' in profile_data:
            profile.streaming_services = profile_data['streaming_services']
            profile.save()

        return instance


# ============================================================
# ── MOVIE SERIALIZERS ────────────────────────────────────────
# ============================================================

class GenreSerializer(serializers.ModelSerializer):
    """
    Simple genre serializer — used inline in movie data.
    GET /api/v1/genres/
    """
    movie_count = serializers.SerializerMethodField()

    class Meta:
        model = Genre
        fields = ['id', 'name', 'slug', 'icon', 'movie_count']

    def get_movie_count(self, obj):
        return obj.movies.count()


class PersonSerializer(serializers.ModelSerializer):
    """Person (actor/director) — shown in movie detail cast section."""
    class Meta:
        model = Person
        fields = ['id', 'name', 'profile_image_url', 'birth_date']


class CastMemberSerializer(serializers.ModelSerializer):
    """
    Cast member WITH character name — uses the MovieCast through table.
    Nested inside MovieDetailSerializer.
    """
    person_id = serializers.IntegerField(source='person.id')
    name = serializers.CharField(source='person.name')
    profile_image_url = serializers.URLField(source='person.profile_image_url')

    class Meta:
        model = MovieCast
        fields = ['person_id', 'name', 'profile_image_url', 'character', 'order']


class CrewMemberSerializer(serializers.ModelSerializer):
    """Director and key crew — nested inside MovieDetailSerializer."""
    person_id = serializers.IntegerField(source='person.id')
    name = serializers.CharField(source='person.name')
    profile_image_url = serializers.URLField(source='person.profile_image_url')

    class Meta:
        model = MovieCrew
        fields = ['person_id', 'name', 'profile_image_url', 'job', 'department']


class StreamingLinkSerializer(serializers.ModelSerializer):
    """Where to watch the movie — shown on movie detail page."""
    class Meta:
        model = StreamingLink
        fields = ['id', 'provider', 'provider_name', 'link_type', 'url', 'region',
                  'price', 'provider_logo']


# class MovieListSerializer(serializers.ModelSerializer):
#     """
#     COMPACT movie serializer — used in lists, carousels, search results.
#     Only includes fields needed to render a movie card.

#     Returned by:
#       GET /api/v1/movies/         (movie list/search)
#       GET /api/v1/recommendations/ (user recommendations)
#       GET /api/v1/movies/trending/

#     Keeps payload small — no cast, no streaming links, no full overview.
#     """
#     genres = GenreSerializer(many=True, read_only=True)
#     poster_url = serializers.ReadOnlyField()
#     backdrop_url = serializers.ReadOnlyField()

#     # User-specific fields — only populated when request.user is authenticated
#     user_rating = serializers.SerializerMethodField()
#     in_watchlist = serializers.SerializerMethodField()

#     class Meta:
#         model = Movie
#         fields = [
#             'id', 'title', 'slug', 'release_year',
#             'vote_average', 'popularity', 'runtime',
#             'genres', 'original_language',
#             'poster_url', 'backdrop_url',
#             'user_rating', 'in_watchlist',
#         ]

#     def _get_user(self):
#         """Helper to safely get the request user."""
#         request = self.context.get('request')
#         if request and request.user and request.user.is_authenticated:
#             return request.user
#         return None

#     def get_user_rating(self, obj):
#         """
#         Returns the current user's rating for this movie, or None.
#         Avoids a DB query per movie by using pre-fetched data when available.
#         """
#         user = self._get_user()
#         if not user:
#             return None
#         # Check context cache first (set by viewset to avoid N+1)
#         ratings_cache = self.context.get('user_ratings', {})
#         if ratings_cache:
#             return ratings_cache.get(obj.id)
#         # Fallback: direct query
#         try:
#             return Rating.objects.get(user=user, movie=obj).score
#         except Rating.DoesNotExist:
#             return None

#     def get_in_watchlist(self, obj):
#         """Returns True if this movie is in the user's watchlist."""
#         user = self._get_user()
#         if not user:
#             return False
#         watchlist_cache = self.context.get('user_watchlist', set())
#         if watchlist_cache:
#             return obj.id in watchlist_cache
#         return WatchlistItem.objects.filter(user=user, movie=obj).exists()


class MovieListSerializer(serializers.ModelSerializer):
    genres = GenreSerializer(many=True, read_only=True)
    poster_url = serializers.SerializerMethodField()
    backdrop_url = serializers.SerializerMethodField()
    user_rating = serializers.SerializerMethodField()
    in_watchlist = serializers.SerializerMethodField()

    class Meta:
        model = Movie
        fields = [
            'id', 'title', 'slug', 'release_year',
            'vote_average', 'popularity', 'runtime',
            'genres', 'original_language',
            'poster_url', 'backdrop_url',
            'user_rating', 'in_watchlist',
        ]

    def get_poster_url(self, obj):
        return obj.poster_url

    def get_backdrop_url(self, obj):
        return obj.backdrop_url

    def get_user_rating(self, obj):
        user = self.context.get('request', None)
        if user and hasattr(user, 'user') and user.user.is_authenticated:
            ratings_cache = self.context.get('user_ratings', {})
            if ratings_cache:
                return ratings_cache.get(obj.id)
            try:
                from interactions.models import Rating
                return Rating.objects.get(user=user.user, movie=obj).score
            except:
                return None
        return None

    def get_in_watchlist(self, obj):
        request = self.context.get('request', None)
        if request and request.user.is_authenticated:
            watchlist_cache = self.context.get('user_watchlist', set())
            if watchlist_cache:
                return obj.id in watchlist_cache
            from interactions.models import WatchlistItem
            return WatchlistItem.objects.filter(user=request.user, movie=obj).exists()
        return False


class MovieDetailSerializer(MovieListSerializer):
    """
    FULL movie serializer — used on the movie detail page.
    Extends MovieListSerializer with cast, crew, streaming, full overview.

    Returned by:
      GET /api/v1/movies/{id}/
      GET /api/v1/movies/{slug}/

    Larger payload but only loaded when user opens a movie page.
    """
    # Cast & crew via through models
    cast_members = CastMemberSerializer(
        source='moviecast_set',
        many=True,
        read_only=True
    )
    crew_members = CrewMemberSerializer(
        source='moviecrew_set',
        many=True,
        read_only=True
    )
    streaming_links = StreamingLinkSerializer(many=True, read_only=True)

    # Derived fields
    director_names = serializers.SerializerMethodField()
    community_rating = serializers.SerializerMethodField()
    similar_movies = serializers.SerializerMethodField()

    class Meta(MovieListSerializer.Meta):
        fields = MovieListSerializer.Meta.fields + [
            'overview', 'tagline', 'original_title',
            'release_date', 'budget', 'revenue', 'status',
            'tmdb_id', 'imdb_id', 'keywords',
            'cast_members', 'crew_members', 'streaming_links',
            'director_names', 'community_rating', 'similar_movies',
        ]

    def get_director_names(self, obj):
        """Returns list of director names for quick display."""
        return list(
            MovieCrew.objects.filter(movie=obj, job='Director')
            .values_list('person__name', flat=True)
        )

    def get_community_rating(self, obj):
        """
        CineMatch users' average rating for this movie
        (distinct from TMDB's vote_average).
        """
        from django.db.models import Avg
        result = Rating.objects.filter(movie=obj).aggregate(avg=Avg('score'))
        avg = result.get('avg')
        count = Rating.objects.filter(movie=obj).count()
        return {
            'average': round(avg, 1) if avg else None,
            'count': count,
        }

    def get_similar_movies(self, obj):
        """
        Pre-computed similar movies for "More Like This" section.
        Returns compact movie data (not full detail) — 8 movies max.
        """
        from recommendations.models import SimilarMovie
        similar_ids = SimilarMovie.objects.filter(
            movie=obj
        ).order_by('-similarity_score').values_list('similar_movie_id', flat=True)[:8]

        similar_movies = Movie.objects.filter(id__in=similar_ids)
        # Preserve similarity score ordering
        movie_dict = {m.id: m for m in similar_movies}
        ordered = [movie_dict[mid] for mid in similar_ids if mid in movie_dict]

        return MovieListSerializer(ordered, many=True, context=self.context).data


# ============================================================
# ── INTERACTION SERIALIZERS ──────────────────────────────────
# ============================================================

class RatingSerializer(serializers.ModelSerializer):
    """
    Create/update a movie rating.

    POST /api/v1/movies/{movie_id}/rate/
      { "score": 8.5, "review": "Brilliant cinematography!" }

    The user is automatically set from the JWT token.
    Upserts (create or update) handled in the view.
    """
    movie_title = serializers.CharField(source='movie.title', read_only=True)
    movie_id = serializers.IntegerField(source='movie.id', read_only=True)

    class Meta:
        model = Rating
        fields = ['id', 'movie_id', 'movie_title', 'score', 'review', 'created_at', 'updated_at']
        read_only_fields = ['id', 'movie_id', 'movie_title', 'created_at', 'updated_at']

    def validate_score(self, value):
        """Ensure score is a valid half-star increment (1.0, 1.5, 2.0, ...)."""
        if value < 1.0 or value > 10.0:
            raise serializers.ValidationError("Score must be between 1.0 and 10.0")
        # Allow only 0.5 increments
        if (value * 2) != int(value * 2):
            raise serializers.ValidationError("Score must be in 0.5 increments (e.g., 7.5)")
        return value


class WatchlistSerializer(serializers.ModelSerializer):
    """
    Add/remove movie from watchlist.

    POST /api/v1/watchlist/    { "movie_id": 42 }
    DELETE /api/v1/watchlist/{id}/
    """
    movie = MovieListSerializer(read_only=True)
    movie_id = serializers.PrimaryKeyRelatedField(
        queryset=Movie.objects.all(),
        source='movie',
        write_only=True
    )

    class Meta:
        model = WatchlistItem
        fields = ['id', 'movie', 'movie_id', 'added_at', 'notes']
        read_only_fields = ['id', 'added_at']

    def validate(self, data):
        """Prevent duplicate watchlist entries."""
        user = self.context['request'].user
        movie = data.get('movie')
        if WatchlistItem.objects.filter(user=user, movie=movie).exists():
            raise serializers.ValidationError(
                "This movie is already in your watchlist."
            )
        return data

    def create(self, validated_data):
        """Auto-set user from JWT token."""
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class WatchEventSerializer(serializers.ModelSerializer):
    """
    Mark a movie as watched.

    POST /api/v1/watched/
      { "movie_id": 42, "source": "Netflix", "rewatched": false }
    """
    movie = MovieListSerializer(read_only=True)
    movie_id = serializers.PrimaryKeyRelatedField(
        queryset=Movie.objects.all(),
        source='movie',
        write_only=True
    )

    class Meta:
        model = WatchEvent
        fields = ['id', 'movie', 'movie_id', 'watched_at', 'source', 'rewatched']
        read_only_fields = ['id', 'watched_at']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class ViewHistorySerializer(serializers.ModelSerializer):
    """
    Record that a user viewed a movie's detail page (implicit signal).
    POST /api/v1/viewed/  { "movie_id": 42 }
    """
    movie_title = serializers.CharField(source='movie.title', read_only=True)
    movie_id = serializers.PrimaryKeyRelatedField(
        queryset=Movie.objects.all(),
        source='movie',
        write_only=True
    )

    class Meta:
        model = ViewHistory
        fields = ['movie_id', 'movie_title', 'viewed_at', 'view_count']
        read_only_fields = ['viewed_at', 'view_count']


# ============================================================
# ── RECOMMENDATION SERIALIZERS ───────────────────────────────
# ============================================================

class RecommendationSerializer(serializers.ModelSerializer):
    """
    A personalized movie recommendation for the current user.

    GET /api/v1/recommendations/

    Each recommendation includes:
    - Full movie data (compact)
    - Score (confidence, 0-1)
    - Rank (position in the list)
    - Reason (human-readable explanation)
    - Source movie (what triggered this rec)

    This is what the main dashboard/home page renders.
    """
    movie = MovieListSerializer(read_only=True)
    source_movie_title = serializers.CharField(
        source='source_movie.title',
        read_only=True,
        default=None
    )

    class Meta:
        model = Recommendation
        fields = [
            'id', 'rank', 'score',
            'movie',
            'reason_code', 'reason_text',
            'source_movie_title',
            'was_clicked', 'created_at',
        ]
        read_only_fields = fields


class SimilarMovieSerializer(serializers.ModelSerializer):
    """
    Similar movie pair — used in 'More Like This' section.
    GET /api/v1/movies/{id}/similar/
    """
    similar_movie = MovieListSerializer(read_only=True)

    class Meta:
        model = SimilarMovie
        fields = [
            'similar_movie',
            'similarity_score',
            'shared_genres',
            'shared_cast',
            'same_director',
        ]


class DashboardSerializer(serializers.Serializer):
    """
    Aggregated dashboard data — returned in ONE request.

    GET /api/v1/dashboard/

    Returns everything the dashboard page needs:
    - User's recommendations
    - Recently watched
    - Watchlist
    - Stats
    - Genre breakdown

    Using a single endpoint reduces frontend request count.
    """
    user = UserDetailSerializer()
    recommendations = RecommendationSerializer(many=True)
    watchlist = WatchlistSerializer(many=True)
    recent_watches = WatchEventSerializer(many=True)
    stats = serializers.DictField()
    genre_breakdown = serializers.ListField()
    algorithm_info = serializers.DictField()
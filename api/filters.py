"""
============================================================
CineMatch - API Filters (api/filters.py)
============================================================

Django Filter classes that enable rich query-string filtering
on API list endpoints.

USAGE (query string examples):
  GET /api/v1/movies/?genre=28
  GET /api/v1/movies/?year_min=2010&year_max=2023
  GET /api/v1/movies/?min_rating=7.5&language=en
  GET /api/v1/movies/?search=inception

DRF + django-filter integration:
  View declares → filter_class = MovieFilter
  User sends   → ?genre=28&year_min=2010
  django-filter → applies .filter(genres__id=28, release_year__gte=2010)
  Returns       → filtered QuerySet

CONNECTION:
  settings.py → DEFAULT_FILTER_BACKENDS includes DjangoFilterBackend
  views.py    → filterset_class = MovieFilter
  urls.py     → router includes these views
============================================================
"""

import django_filters
from movies.models import Movie, Genre


class MovieFilter(django_filters.FilterSet):
    """
    Rich filtering for the movie catalog.

    Enables frontend to build a proper filter UI with:
    - Genre checkboxes
    - Year range sliders
    - Rating filter
    - Language dropdown
    - Runtime range
    """

    # Genre filter: ?genre=28 (by ID) or ?genre_name=Action
    genre = django_filters.NumberFilter(
        field_name='genres__id',
        label='Genre ID'
    )
    genre_slug = django_filters.CharFilter(
        field_name='genres__slug',
        label='Genre slug (e.g., action)'
    )

    # Year range: ?year_min=2010&year_max=2023
    year_min = django_filters.NumberFilter(
        field_name='release_year',
        lookup_expr='gte',
        label='Release year minimum'
    )
    year_max = django_filters.NumberFilter(
        field_name='release_year',
        lookup_expr='lte',
        label='Release year maximum'
    )

    # Rating filter: ?min_rating=7.5
    min_rating = django_filters.NumberFilter(
        field_name='vote_average',
        lookup_expr='gte',
        label='Minimum TMDB rating'
    )

    # Runtime range: ?runtime_max=120 (under 2 hours)
    runtime_max = django_filters.NumberFilter(
        field_name='runtime',
        lookup_expr='lte',
        label='Maximum runtime (minutes)'
    )
    runtime_min = django_filters.NumberFilter(
        field_name='runtime',
        lookup_expr='gte',
        label='Minimum runtime (minutes)'
    )

    # Language: ?language=en
    language = django_filters.CharFilter(
        field_name='original_language',
        label='Original language (ISO code: en, hi, fr)'
    )

    # Adult content: ?adult=false (default hides adult content)
    adult = django_filters.BooleanFilter(
        field_name='adult',
        label='Include adult content'
    )

    class Meta:
        model = Movie
        fields = ['genre', 'genre_slug', 'year_min', 'year_max',
                  'min_rating', 'runtime_max', 'runtime_min', 'language', 'adult']
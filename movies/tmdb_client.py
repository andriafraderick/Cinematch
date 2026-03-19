"""
============================================================
CineMatch - TMDB API Client (movies/tmdb_client.py)
============================================================

This module handles ALL communication with The Movie Database API.
TMDB is the data source for:
  - Movie metadata (title, overview, genres, cast)
  - Poster and backdrop images
  - Watch providers (streaming availability)
  - Popular/trending movies

USAGE:
  client = TMDBClient()
  movies = client.get_popular_movies(page=1)
  details = client.get_movie_details(tmdb_id=550)
  providers = client.get_watch_providers(tmdb_id=550, region='IN')

MANAGEMENT COMMAND:
  python manage.py sync_tmdb --pages 20
  This calls TMDBClient and populates the Movie table.

API KEY:
  Set TMDB_API_KEY in your .env file.
  Free tier: 40 requests/10 seconds (plenty for sync).
  Sign up: https://www.themoviedb.org/settings/api
============================================================
"""

import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class TMDBClient:
    """
    Wrapper around the TMDB REST API v3.

    All methods return parsed Python dicts/lists.
    Error handling returns empty structures rather than raising
    so sync operations don't abort on one bad response.
    """

    def __init__(self):
        self.api_key = settings.TMDB_API_KEY
        self.base_url = settings.TMDB_BASE_URL
        self.session = requests.Session()
        # Set default params (api_key sent with every request)
        self.session.params = {'api_key': self.api_key}

    def _get(self, endpoint, params=None):
        """
        Internal helper: makes GET request to TMDB API.
        Returns parsed JSON or empty dict on failure.
        """
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"TMDB API HTTP error for {endpoint}: {e}")
        except requests.exceptions.ConnectionError:
            logger.error(f"TMDB API connection error for {endpoint}")
        except requests.exceptions.Timeout:
            logger.error(f"TMDB API timeout for {endpoint}")
        return {}

    # ----------------------------------------------------------
    # GENRES
    # ----------------------------------------------------------
    def get_genre_list(self):
        """
        Returns all TMDB movie genres.
        Used by: python manage.py sync_tmdb to populate Genre table.

        Returns:
          [{'id': 28, 'name': 'Action'}, ...]
        """
        data = self._get('/genre/movie/list')
        return data.get('genres', [])

    # ----------------------------------------------------------
    # POPULAR / TRENDING
    # ----------------------------------------------------------
    def get_popular_movies(self, page=1):
        """
        Returns popular movies (sorted by TMDB popularity score).

        Returns:
          {'results': [...], 'total_pages': 500, 'page': 1}
        """
        return self._get('/movie/popular', {'page': page})

    def get_trending_movies(self, time_window='week'):
        """
        Returns trending movies for today or this week.
        time_window: 'day' or 'week'
        """
        return self._get(f'/trending/movie/{time_window}')

    def get_top_rated_movies(self, page=1):
        """Returns highest-rated movies on TMDB."""
        return self._get('/movie/top_rated', {'page': page})

    # ----------------------------------------------------------
    # MOVIE DETAILS
    # ----------------------------------------------------------
    def get_movie_details(self, tmdb_id):
        """
        Returns full movie details including genres, cast, crew, keywords.
        Uses append_to_response to get everything in ONE API call.

        Returns dict with keys:
          id, title, overview, genres, release_date, runtime,
          vote_average, vote_count, popularity, poster_path,
          backdrop_path, keywords, credits, watch/providers
        """
        return self._get(
            f'/movie/{tmdb_id}',
            {
                'append_to_response': 'keywords,credits,watch/providers',
                'language': 'en-US',
            }
        )

    # ----------------------------------------------------------
    # STREAMING PROVIDERS
    # ----------------------------------------------------------
    def get_watch_providers(self, tmdb_id, region='IN'):
        """
        Returns streaming availability for a movie in a given region.

        TMDB Watch Providers API returns:
          - flatrate: subscription streaming (Netflix, Prime)
          - rent: rental options
          - buy: purchase options

        Args:
          tmdb_id: TMDB movie ID
          region: ISO 3166-1 alpha-2 country code (IN, US, GB)

        Returns:
          {'flatrate': [...], 'rent': [...], 'buy': [...]}
        """
        data = self._get(f'/movie/{tmdb_id}/watch/providers')
        results = data.get('results', {})
        return results.get(region, {})

    # ----------------------------------------------------------
    # DISCOVER (for filtered recommendations)
    # ----------------------------------------------------------
    def discover_movies(self, genre_ids=None, year=None, min_rating=6.0, page=1):
        """
        Discover movies by genre, year, rating — used for cold-start
        recommendations for new users with genre preferences.

        Args:
          genre_ids: list of TMDB genre IDs
          year: release year filter
          min_rating: minimum vote_average
          page: pagination
        """
        params = {
            'sort_by': 'popularity.desc',
            'vote_average.gte': min_rating,
            'vote_count.gte': 100,  # Only movies with enough votes
            'page': page,
        }
        if genre_ids:
            params['with_genres'] = ','.join(str(g) for g in genre_ids)
        if year:
            params['primary_release_year'] = year

        return self._get('/discover/movie', params)

    # ----------------------------------------------------------
    # SEARCH
    # ----------------------------------------------------------
    def search_movies(self, query, page=1):
        """
        Full-text search for movies on TMDB.
        Used by the search endpoint in the UI.
        """
        return self._get('/search/movie', {'query': query, 'page': page})

    def get_movie_recommendations(self, tmdb_id, page=1):
        """
        TMDB's own recommendation engine for a given movie.
        Used as a fallback/supplement to our own ML engine.
        """
        return self._get(f'/movie/{tmdb_id}/recommendations', {'page': page})
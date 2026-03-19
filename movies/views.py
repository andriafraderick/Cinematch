"""
============================================================
CineMatch - Movies Views (movies/views.py)
============================================================

Template-based views for movie browsing pages.
Data is also exposed via the JSON API (api/views.py).

URL → View → Template:
  /          → HomeView         → templates/movies/home.html
  /movies/{slug}/ → MovieDetailView → templates/movies/movie_detail.html
  /search/   → SearchView       → templates/movies/search.html
  /browse/   → BrowseView       → templates/movies/browse.html

The templates call the JavaScript API client which hits
/api/v1/ endpoints for dynamic content (recommendations,
ratings, watchlist status). The views just render the shell.
============================================================
"""

from django.shortcuts import render, get_object_or_404
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from movies.models import Movie, Genre
from interactions.models import ViewHistory
import logging

logger = logging.getLogger(__name__)


class HomeView(TemplateView):
    """
    Landing page / Home.
    GET /

    For authenticated users: shows personalized dashboard shell.
    For anonymous users: shows marketing landing page with trending movies.

    Heavy content (recommendations, trending) loaded via JS → API.
    """
    def get_template_names(self):
        if self.request.user.is_authenticated:
            return ['movies/home_auth.html']
        return ['movies/home.html']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass genre list for the genre filter bar
        context['genres'] = Genre.objects.all().order_by('name')

        # For non-auth home: show a few trending movies server-side
        if not self.request.user.is_authenticated:
            context['featured_movies'] = Movie.objects.filter(
                status='Released',
                adult=False,
                vote_count__gte=500,
            ).order_by('-popularity')[:6]

        return context


class MovieDetailView(TemplateView):
    """
    Movie detail page.
    GET /movies/{slug}/

    Renders the movie detail shell. Full data (cast, similar movies,
    streaming links, user rating) loaded via JS API calls.
    """
    template_name = 'movies/movie_detail.html'

    def get(self, request, slug):
        movie = get_object_or_404(Movie, slug=slug)

        # Record view (implicit ML signal) for authenticated users
        if request.user.is_authenticated:
            try:
                ViewHistory.record_view(user=request.user, movie=movie)
            except Exception as e:
                logger.warning(f"Could not record view for {slug}: {e}")

        context = {
            'movie': movie,
            'page_title': f"{movie.title} ({movie.release_year}) — CineMatch",
        }
        return render(request, self.template_name, context)


class BrowseView(TemplateView):
    """
    Browse all movies with filtering.
    GET /browse/?genre=action&year_min=2010
    Template loads movies via JS → /api/v1/movies/
    """
    template_name = 'movies/browse.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['genres'] = Genre.objects.all().order_by('name')
        context['current_genre'] = self.request.GET.get('genre', '')
        return context


class SearchView(TemplateView):
    """
    Search results page.
    GET /search/?q=inception
    Template calls JS → /api/v1/movies/?search=inception
    """
    template_name = 'movies/search.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '')
        return context
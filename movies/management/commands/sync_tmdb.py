"""
============================================================
CineMatch - TMDB Sync Management Command
(movies/management/commands/sync_tmdb.py)
============================================================

This management command populates the PostgreSQL database
with movie data from the TMDB API.

USAGE:
  # Sync 5 pages of popular movies (~100 movies)
  python manage.py sync_tmdb --pages 5

  # Sync genres first, then movies
  python manage.py sync_tmdb --genres-only

  # Sync specific movie by TMDB ID
  python manage.py sync_tmdb --movie-id 550

FLOW:
  1. Fetch genre list → populate Genre table
  2. Fetch popular/top-rated movies page by page
  3. For each movie: fetch full details (cast, crew, keywords)
  4. Save to Movie, Person, MovieCast, MovieCrew tables
  5. Fetch streaming providers → save StreamingLink records

This command is idempotent: safe to run multiple times.
Existing records are UPDATED, not duplicated (upsert logic).
============================================================
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from movies.models import Genre, Movie, Person, MovieCast, MovieCrew, StreamingLink
from movies.tmdb_client import TMDBClient
import logging
import time

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sync movie data from TMDB API into CineMatch database'

    def add_arguments(self, parser):
        """Define CLI arguments for this command."""
        parser.add_argument(
            '--pages',
            type=int,
            default=3,
            help='Number of pages of popular movies to sync (20 movies per page)'
        )
        parser.add_argument(
            '--genres-only',
            action='store_true',
            help='Only sync genres, skip movies'
        )
        parser.add_argument(
            '--movie-id',
            type=int,
            help='Sync a single movie by TMDB ID'
        )
        parser.add_argument(
            '--region',
            default='IN',
            help='Region for streaming providers (default: IN)'
        )
        parser.add_argument(
            '--no-providers',
            action='store_true',
            help='Skip streaming provider sync (faster)'
        )

    def handle(self, *args, **options):
        """Main entry point for the management command."""
        self.client = TMDBClient()
        self.region = options['region']
        self.sync_providers = not options['no_providers']

        self.stdout.write(self.style.SUCCESS('🎬 CineMatch TMDB Sync Starting...'))

        # Step 1: Always sync genres first
        self.sync_genres()

        if options['genres_only']:
            self.stdout.write(self.style.SUCCESS('✅ Genres synced. Done.'))
            return

        if options['movie_id']:
            # Sync single movie
            self.sync_single_movie(options['movie_id'])
        else:
            # Sync multiple pages of popular movies
            pages = options['pages']
            self.stdout.write(f'📽️  Syncing {pages} pages × 20 movies = ~{pages * 20} movies...')
            self.sync_popular_movies(pages)

        self.stdout.write(self.style.SUCCESS('✅ TMDB sync complete!'))

    # ----------------------------------------------------------
    # GENRE SYNC
    # ----------------------------------------------------------
    def sync_genres(self):
        """Fetch TMDB genres and create/update Genre records."""
        self.stdout.write('🏷️  Syncing genres...')
        genres = self.client.get_genre_list()

        created_count = 0
        for genre_data in genres:
            genre, created = Genre.objects.update_or_create(
                tmdb_id=genre_data['id'],
                defaults={'name': genre_data['name']}
            )
            if created:
                created_count += 1

        self.stdout.write(f'   ✓ {len(genres)} genres synced ({created_count} new)')

    # ----------------------------------------------------------
    # MOVIE SYNC
    # ----------------------------------------------------------
    def sync_popular_movies(self, pages):
        """Sync multiple pages of popular movies."""
        total_synced = 0

        for page in range(1, pages + 1):
            self.stdout.write(f'   Page {page}/{pages}...')
            data = self.client.get_popular_movies(page=page)
            movies = data.get('results', [])

            for movie_data in movies:
                try:
                    self.sync_single_movie(movie_data['id'])
                    total_synced += 1
                    # Respect TMDB rate limit: 40 req/10s
                    time.sleep(0.25)
                except Exception as e:
                    logger.error(f"Error syncing movie {movie_data.get('id')}: {e}")
                    self.stdout.write(
                        self.style.WARNING(f"   ⚠ Skipped movie {movie_data.get('title', '?')}: {e}")
                    )

        self.stdout.write(f'   ✓ {total_synced} movies synced total')

    def sync_single_movie(self, tmdb_id):
        """
        Fetch full details for one movie and save to database.

        This is the core sync function — called for each movie.
        Uses TMDB's append_to_response to get everything in one API call.
        """
        # Fetch complete movie data (one API call gets it all)
        data = self.client.get_movie_details(tmdb_id)

        if not data or 'id' not in data:
            raise CommandError(f"No data returned for TMDB ID {tmdb_id}")

        # --- Extract genre IDs from TMDB response ---
        genre_ids = [g['id'] for g in data.get('genres', [])]
        genres = Genre.objects.filter(tmdb_id__in=genre_ids)

        # --- Extract keywords ---
        keywords_data = data.get('keywords', {}).get('keywords', [])
        keyword_names = [k['name'] for k in keywords_data]

        # --- Parse release year ---
        release_date = data.get('release_date', '')
        release_year = int(release_date[:4]) if release_date else None

        # --- Create/Update Movie record ---
        movie, created = Movie.objects.update_or_create(
            tmdb_id=data['id'],
            defaults={
                'imdb_id': data.get('imdb_id', ''),
                'title': data.get('title', ''),
                'original_title': data.get('original_title', ''),
                'overview': data.get('overview', ''),
                'tagline': data.get('tagline', ''),
                'release_date': release_date or None,
                'release_year': release_year,
                'runtime': data.get('runtime'),
                'vote_average': data.get('vote_average', 0),
                'vote_count': data.get('vote_count', 0),
                'popularity': data.get('popularity', 0),
                'poster_path': data.get('poster_path', ''),
                'backdrop_path': data.get('backdrop_path', ''),
                'original_language': data.get('original_language', 'en'),
                'adult': data.get('adult', False),
                'status': data.get('status', 'Released'),
                'budget': data.get('budget') or None,
                'revenue': data.get('revenue') or None,
                'keywords': keyword_names,
                'last_synced': timezone.now(),
            }
        )

        # Set genres (M2M — must do after save)
        movie.genres.set(genres)

        # --- Sync Cast & Crew ---
        credits = data.get('credits', {})
        self._sync_cast(movie, credits.get('cast', []))
        self._sync_crew(movie, credits.get('crew', []))

        # --- Sync Streaming Providers ---
        if self.sync_providers:
            providers = self.client.get_watch_providers(tmdb_id, self.region)
            self._sync_providers(movie, providers)

        status = '✓ NEW' if created else '  updated'
        self.stdout.write(f'     {status}: {movie.title} ({release_year})')

        return movie

    # ----------------------------------------------------------
    # CAST & CREW HELPERS
    # ----------------------------------------------------------
    def _sync_cast(self, movie, cast_list):
        """
        Save top 10 cast members for a movie.
        Only top 10 to keep DB lean (full cast can be 100+ people).
        """
        # Clear existing cast for this movie
        MovieCast.objects.filter(movie=movie).delete()

        for i, cast_data in enumerate(cast_list[:10]):
            person, _ = Person.objects.get_or_create(
                tmdb_id=cast_data['id'],
                defaults={
                    'name': cast_data['name'],
                    'profile_image_url': (
                        f"https://image.tmdb.org/t/p/w185{cast_data['profile_path']}"
                        if cast_data.get('profile_path') else ''
                    ),
                }
            )
            MovieCast.objects.get_or_create(
                movie=movie,
                person=person,
                character=cast_data.get('character', ''),
                defaults={'order': i}
            )

    def _sync_crew(self, movie, crew_list):
        """Save director and key crew members."""
        MovieCrew.objects.filter(movie=movie).delete()

        # Only save key roles
        key_roles = {'Director', 'Screenplay', 'Story', 'Producer', 'Director of Photography'}

        for crew_data in crew_list:
            if crew_data.get('job') not in key_roles:
                continue

            person, _ = Person.objects.get_or_create(
                tmdb_id=crew_data['id'],
                defaults={'name': crew_data['name']}
            )
            MovieCrew.objects.get_or_create(
                movie=movie,
                person=person,
                job=crew_data['job'],
                defaults={'department': crew_data.get('department', '')}
            )

    # ----------------------------------------------------------
    # STREAMING PROVIDER HELPER
    # ----------------------------------------------------------
    def _sync_providers(self, movie, providers_data):
        """Save streaming availability links."""
        # Map TMDB provider names to our provider choices
        provider_map = {
            'Netflix': 'netflix',
            'Amazon Prime Video': 'prime',
            'Disney+ Hotstar': 'hotstar',
            'Disney Plus': 'disney',
            'Hulu': 'hulu',
            'Apple TV Plus': 'apple',
            'MUBI': 'mubi',
            'YouTube': 'youtube',
            'HBO Max': 'hbo',
        }

        type_map = {
            'flatrate': 'stream',
            'rent': 'rent',
            'buy': 'buy',
            'free': 'free',
        }

        # Clear existing links for this movie+region
        StreamingLink.objects.filter(movie=movie, region=self.region).delete()

        for link_type, provider_list in providers_data.items():
            if link_type not in type_map or not isinstance(provider_list, list):
                continue

            for provider_data in provider_list:
                name = provider_data.get('provider_name', '')
                StreamingLink.objects.create(
                    movie=movie,
                    provider=provider_map.get(name, 'other'),
                    provider_name=name,
                    link_type=type_map[link_type],
                    url=f"https://www.justwatch.com/in/movie/{movie.slug}",  # JustWatch link
                    region=self.region,
                    provider_logo=(
                        f"https://image.tmdb.org/t/p/original{provider_data.get('logo_path', '')}"
                        if provider_data.get('logo_path') else ''
                    ),
                )
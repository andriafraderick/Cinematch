"""
============================================================
CineMatch - Kaggle TMDB Dataset Importer
movies/management/commands/import_kaggle.py
============================================================

Imports movies and credits from Kaggle TMDB CSV files.

USAGE:
  python manage.py import_kaggle \\
      --movies path/to/tmdb_5000_movies.csv \\
      --credits path/to/tmdb_5000_credits.csv

OPTIONAL FLAGS:
  --limit 500        only import first N movies
  --min-votes 50     skip movies with fewer votes (default: 10)
  --clear            delete all existing movies before import

WHAT IT IMPORTS:
  - Genres           → movies.Genre
  - Movies           → movies.Movie
  - People           → movies.Person
  - Cast             → movies.MovieCast (through table)
  - Directors/Crew   → movies.MovieCrew (through table)
  - Keywords         → stored as JSON on Movie.keywords

KAGGLE DATASET:
  https://www.kaggle.com/datasets/tmdb/tmdb-movie-metadata
  Files: tmdb_5000_movies.csv + tmdb_5000_credits.csv
============================================================
"""

import json
import ast
import csv
import os
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.db import transaction


class Command(BaseCommand):
    help = 'Import movies from Kaggle TMDB CSV dataset'

    def add_arguments(self, parser):
        parser.add_argument(
            '--movies',
            type=str,
            default='tmdb_5000_movies.csv',
            help='Path to tmdb_5000_movies.csv (default: tmdb_5000_movies.csv)'
        )
        parser.add_argument(
            '--credits',
            type=str,
            default='tmdb_5000_credits.csv',
            help='Path to tmdb_5000_credits.csv (default: tmdb_5000_credits.csv)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum number of movies to import'
        )
        parser.add_argument(
            '--min-votes',
            type=int,
            default=10,
            help='Minimum vote count to import a movie (default: 10)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear all existing movies before importing'
        )

    def handle(self, *args, **options):
        movies_path = options['movies']
        credits_path = options['credits']
        limit = options['limit']
        min_votes = options['min_votes']
        clear = options['clear']

        # Validate files exist
        if not os.path.exists(movies_path):
            self.stderr.write(self.style.ERROR(
                f"Movies file not found: {movies_path}\n"
                f"Run from project root or provide full path with --movies"
            ))
            return

        if not os.path.exists(credits_path):
            self.stderr.write(self.style.ERROR(
                f"Credits file not found: {credits_path}\n"
                f"Run from project root or provide full path with --credits"
            ))
            return

        self.stdout.write(self.style.SUCCESS('Starting Kaggle TMDB import...'))
        self.stdout.write(f'  Movies file : {movies_path}')
        self.stdout.write(f'  Credits file: {credits_path}')
        if limit:
            self.stdout.write(f'  Limit       : {limit} movies')
        self.stdout.write(f'  Min votes   : {min_votes}')

        # Clear existing data if requested
        if clear:
            self._clear_data()

        # Step 1: Load credits into memory (keyed by movie_id)
        self.stdout.write('\n[1/4] Loading credits file...')
        credits_map = self._load_credits(credits_path)
        self.stdout.write(f'      Loaded credits for {len(credits_map)} movies')

        # Step 2: Parse and import movies
        self.stdout.write('\n[2/4] Importing movies and genres...')
        movies_data = self._load_movies(movies_path, credits_map, limit, min_votes)

        # Step 3: Import to database
        self.stdout.write('\n[3/4] Writing to database...')
        stats = self._import_to_db(movies_data)

        # Step 4: Summary
        self.stdout.write('\n[4/4] Done!\n')
        self.stdout.write(self.style.SUCCESS(
            f"  ✓ Movies imported : {stats['movies']}\n"
            f"  ✓ Genres created  : {stats['genres']}\n"
            f"  ✓ People created  : {stats['people']}\n"
            f"  ✓ Cast records    : {stats['cast']}\n"
            f"  ✓ Crew records    : {stats['crew']}\n"
            f"  ✗ Skipped         : {stats['skipped']}\n"
        ))
        self.stdout.write(
            'Next steps:\n'
            '  python manage.py compute_similarities\n'
            '  python manage.py warm_engine\n'
        )

    # ── HELPERS ──────────────────────────────────────────────

    def _clear_data(self):
        """Delete all existing movie data."""
        from movies.models import Movie, Genre, Person, MovieCast, MovieCrew
        self.stdout.write('Clearing existing data...')
        MovieCast.objects.all().delete()
        MovieCrew.objects.all().delete()
        Movie.objects.all().delete()
        Genre.objects.all().delete()
        Person.objects.all().delete()
        self.stdout.write(self.style.WARNING('Cleared all movie data.'))

    def _parse_json_field(self, value):
        """
        Safely parse a JSON/Python-literal string from CSV.
        Kaggle CSVs store lists as either JSON or Python literal strings.
        e.g. '[{"id": 28, "name": "Action"}]'
        """
        if not value or value == '[]' or value == 'nan':
            return []
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            try:
                return ast.literal_eval(value)
            except Exception:
                return []

    def _load_credits(self, credits_path):
        """
        Load credits CSV into memory as a dict: {movie_id: {cast, crew}}
        """
        credits_map = {}
        with open(credits_path, encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    # Credits file uses 'movie_id' or 'id'
                    movie_id = int(row.get('movie_id') or row.get('id') or 0)
                    if movie_id:
                        credits_map[movie_id] = {
                            'cast': self._parse_json_field(row.get('cast', '[]')),
                            'crew': self._parse_json_field(row.get('crew', '[]')),
                        }
                except (ValueError, KeyError):
                    continue
        return credits_map

    def _load_movies(self, movies_path, credits_map, limit, min_votes):
        """
        Parse movies CSV and merge with credits data.
        Returns list of dicts ready for DB import.
        """
        movies_data = []
        skipped = 0

        with open(movies_path, encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                if limit and len(movies_data) >= limit:
                    break

                try:
                    # Get movie ID (column name varies)
                    tmdb_id = int(
                        row.get('id') or
                        row.get('movie_id') or
                        row.get('tmdb_id') or 0
                    )
                    if not tmdb_id:
                        skipped += 1
                        continue

                    # Skip low-vote movies
                    vote_count = int(float(row.get('vote_count') or 0))
                    if vote_count < min_votes:
                        skipped += 1
                        continue

                    # Basic fields
                    title = (row.get('title') or row.get('original_title') or '').strip()
                    if not title:
                        skipped += 1
                        continue

                    vote_average = float(row.get('vote_average') or 0)
                    popularity = float(row.get('popularity') or 0)
                    overview = (row.get('overview') or '').strip()
                    tagline = (row.get('tagline') or '').strip()
                    original_title = (row.get('original_title') or title).strip()
                    original_language = (row.get('original_language') or 'en').strip()
                    runtime = None
                    try:
                        runtime = int(float(row.get('runtime') or 0)) or None
                    except (ValueError, TypeError):
                        pass

                    budget = None
                    revenue = None
                    try:
                        budget = int(float(row.get('budget') or 0)) or None
                        revenue = int(float(row.get('revenue') or 0)) or None
                    except (ValueError, TypeError):
                        pass

                    # Release date
                    release_date = None
                    release_year = None
                    date_str = (row.get('release_date') or '').strip()
                    if date_str:
                        for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%Y'):
                            try:
                                release_date = datetime.strptime(date_str, fmt).date()
                                release_year = release_date.year
                                break
                            except ValueError:
                                continue

                    # JSON fields
                    genres = self._parse_json_field(row.get('genres', '[]'))
                    keywords = self._parse_json_field(row.get('keywords', '[]'))
                    keyword_names = [k['name'] for k in keywords if 'name' in k]

                    # TMDB image paths (Kaggle dataset doesn't include these,
                    # but we store empty strings — can be backfilled via API)
                    poster_path = (row.get('poster_path') or '').strip()
                    backdrop_path = (row.get('backdrop_path') or '').strip()

                    # Credits
                    credits = credits_map.get(tmdb_id, {'cast': [], 'crew': []})

                    movies_data.append({
                        'tmdb_id': tmdb_id,
                        'title': title,
                        'original_title': original_title,
                        'overview': overview,
                        'tagline': tagline,
                        'original_language': original_language,
                        'release_date': release_date,
                        'release_year': release_year,
                        'runtime': runtime,
                        'vote_average': vote_average,
                        'vote_count': vote_count,
                        'popularity': popularity,
                        'budget': budget,
                        'revenue': revenue,
                        'poster_path': poster_path,
                        'backdrop_path': backdrop_path,
                        'genres': genres,
                        'keywords': keyword_names,
                        'cast': credits['cast'],
                        'crew': credits['crew'],
                    })

                    if (i + 1) % 500 == 0:
                        self.stdout.write(f'      Parsed {i + 1} rows...')

                except Exception as e:
                    self.stderr.write(f'Row {i} error: {e}')
                    skipped += 1
                    continue

        self.stdout.write(f'      Parsed {len(movies_data)} valid movies ({skipped} skipped)')
        return movies_data

    def _import_to_db(self, movies_data):
        """
        Write all parsed movie data to the database.
        Uses get_or_create to avoid duplicates on re-runs.
        """
        from movies.models import Genre, Person, Movie, MovieCast, MovieCrew

        stats = {
            'movies': 0, 'genres': 0, 'people': 0,
            'cast': 0, 'crew': 0, 'skipped': 0
        }

        # Pre-cache genres and people to avoid N+1 DB hits
        genre_cache = {}   # name → Genre instance
        person_cache = {}  # tmdb_id → Person instance

        total = len(movies_data)

        for i, data in enumerate(movies_data):
            try:
                with transaction.atomic():
                    # ── GENRES ────────────────────────────────────────
                    genre_objs = []
                    for g in data['genres']:
                        name = g.get('name', '').strip()
                        if not name:
                            continue
                        if name not in genre_cache:
                            obj, created = Genre.objects.get_or_create(
                                name=name,
                                defaults={'slug': slugify(name)}
                            )
                            genre_cache[name] = obj
                            if created:
                                stats['genres'] += 1
                        genre_objs.append(genre_cache[name])

                    # ── MOVIE ─────────────────────────────────────────
                    # Generate unique slug
                    base_slug = slugify(data['title'])
                    if data['release_year']:
                        base_slug = f"{base_slug}-{data['release_year']}"
                    slug = base_slug
                    counter = 1
                    while Movie.objects.filter(slug=slug).exclude(tmdb_id=data['tmdb_id']).exists():
                        slug = f"{base_slug}-{counter}"
                        counter += 1

                    movie, created = Movie.objects.update_or_create(
                        tmdb_id=data['tmdb_id'],
                        defaults={
                            'title': data['title'],
                            'original_title': data['original_title'],
                            'slug': slug,
                            'overview': data['overview'],
                            'tagline': data['tagline'],
                            'original_language': data['original_language'],
                            'release_date': data['release_date'],
                            'release_year': data['release_year'],
                            'runtime': data['runtime'],
                            'vote_average': data['vote_average'],
                            'vote_count': data['vote_count'],
                            'popularity': data['popularity'],
                            'budget': data['budget'],
                            'revenue': data['revenue'],
                            'poster_path': data['poster_path'],
                            'backdrop_path': data['backdrop_path'],
                            'keywords': data['keywords'],
                            'status': 'Released',
                            'adult': False,
                        }
                    )

                    # Set genres
                    movie.genres.set(genre_objs)
                    stats['movies'] += 1

                    # ── CAST ──────────────────────────────────────────
                    # Only import top 10 cast members
                    MovieCast.objects.filter(movie=movie).delete()
                    for cast_member in data['cast'][:10]:
                        pid = cast_member.get('id')
                        name = (cast_member.get('name') or '').strip()
                        if not pid or not name:
                            continue

                        if pid not in person_cache:
                            person, p_created = Person.objects.get_or_create(
                                tmdb_id=pid,
                                defaults={
                                    'name': name,
                                    'profile_image_url': self._tmdb_img(
                                        cast_member.get('profile_path')
                                    ),
                                }
                            )
                            person_cache[pid] = person
                            if p_created:
                                stats['people'] += 1
                        else:
                            person = person_cache[pid]

                        MovieCast.objects.get_or_create(
                            movie=movie,
                            person=person,
                            defaults={
                                'character': (cast_member.get('character') or '').strip(),
                                'order': cast_member.get('order', 0),
                            }
                        )
                        stats['cast'] += 1

                    # ── CREW ──────────────────────────────────────────
                    # Only import directors, writers, and DPs
                    IMPORTANT_JOBS = {'Director', 'Writer', 'Screenplay', 'Director of Photography'}
                    MovieCrew.objects.filter(movie=movie).delete()
                    for crew_member in data['crew']:
                        job = (crew_member.get('job') or '').strip()
                        if job not in IMPORTANT_JOBS:
                            continue

                        pid = crew_member.get('id')
                        name = (crew_member.get('name') or '').strip()
                        if not pid or not name:
                            continue

                        if pid not in person_cache:
                            person, p_created = Person.objects.get_or_create(
                                tmdb_id=pid,
                                defaults={
                                    'name': name,
                                    'profile_image_url': self._tmdb_img(
                                        crew_member.get('profile_path')
                                    ),
                                }
                            )
                            person_cache[pid] = person
                            if p_created:
                                stats['people'] += 1
                        else:
                            person = person_cache[pid]

                        MovieCrew.objects.get_or_create(
                            movie=movie,
                            person=person,
                            defaults={
                                'job': job,
                                'department': (crew_member.get('department') or '').strip(),
                            }
                        )
                        stats['crew'] += 1

            except Exception as e:
                self.stderr.write(f"Error importing '{data.get('title', '?')}': {e}")
                stats['skipped'] += 1
                continue

            # Progress update every 100 movies
            if (i + 1) % 100 == 0:
                self.stdout.write(
                    f"      {i + 1}/{total} movies imported "
                    f"({stats['genres']} genres, {stats['people']} people)"
                )

        return stats

    def _tmdb_img(self, path):
        """Convert TMDB image path to full URL."""
        if not path:
            return ''
        if path.startswith('http'):
            return path
        return f"https://image.tmdb.org/t/p/w185{path}"
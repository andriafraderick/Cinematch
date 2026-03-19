"""
============================================================
CineMatch - Compute Similarities Management Command
(recommendations/management/commands/compute_similarities.py)
============================================================

This command runs the content-based engine to:
  1. Build TF-IDF vectors for all movies
  2. Compute movie-to-movie cosine similarities
  3. Store top-20 similar movies per movie in SimilarMovie table
  4. Also writes content_vector to each Movie record (for user scoring)

WHEN TO RUN:
  - After initial TMDB sync (python manage.py sync_tmdb)
  - After adding new movies
  - Recommended: run weekly as a cron job

USAGE:
  python manage.py compute_similarities
  python manage.py compute_similarities --top-n 30
  python manage.py compute_similarities --update-vectors-only

TIME ESTIMATE:
  1,000 movies:  ~10 seconds
  5,000 movies:  ~2 minutes
  20,000 movies: ~20 minutes
============================================================
"""

from django.core.management.base import BaseCommand
import logging
import time

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Compute content-based similarity vectors and store in database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--top-n',
            type=int,
            default=20,
            help='Number of similar movies to store per movie (default: 20)'
        )
        parser.add_argument(
            '--update-vectors-only',
            action='store_true',
            help='Only update Movie.content_vector fields, skip similarity computation'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='DB write batch size (default: 100)'
        )

    def handle(self, *args, **options):
        from recommendations.content_engine import ContentEngine
        from movies.models import Movie
        import json

        start_time = time.time()
        self.stdout.write(self.style.SUCCESS('🤖 Building content feature matrix...'))

        # --- Step 1: Fit the content engine ---
        engine = ContentEngine()
        engine.fit()

        if not engine.is_fitted:
            self.stdout.write(self.style.ERROR(
                '❌ Could not fit engine. Make sure movies are synced first: '
                'python manage.py sync_tmdb'
            ))
            return

        movie_count = len(engine.movie_ids)
        self.stdout.write(f'   ✓ TF-IDF matrix built for {movie_count} movies')
        self.stdout.write(f'   ✓ Vocabulary size: {len(engine.vectorizer.vocabulary_)} terms')

        # --- Step 2: Save content vectors to Movie records ---
        self.stdout.write('💾 Saving content vectors to Movie records...')

        update_count = 0
        batch = []

        for movie_id in engine.movie_ids:
            idx = engine.movie_id_to_idx[movie_id]
            # Convert sparse row to dense list for JSON storage
            vector = engine.tfidf_matrix[idx].toarray()[0].tolist()

            batch.append({'id': movie_id, 'content_vector': vector})

            if len(batch) >= options['batch_size']:
                # Bulk update using a loop (Django ORM doesn't have bulk_update for JSON easily)
                for item in batch:
                    Movie.objects.filter(id=item['id']).update(
                        content_vector=item['content_vector']
                    )
                update_count += len(batch)
                batch = []
                self.stdout.write(f'   Progress: {update_count}/{movie_count} vectors saved')

        # Flush remaining
        for item in batch:
            Movie.objects.filter(id=item['id']).update(
                content_vector=item['content_vector']
            )
        update_count += len(batch)

        self.stdout.write(f'   ✓ {update_count} content vectors saved')

        if options['update_vectors_only']:
            elapsed = time.time() - start_time
            self.stdout.write(self.style.SUCCESS(f'✅ Done in {elapsed:.1f}s'))
            return

        # --- Step 3: Compute all pairwise similarities ---
        self.stdout.write(
            f'🔗 Computing top-{options["top_n"]} similarities for {movie_count} movies...'
        )
        self.stdout.write('   (This may take a few minutes for large catalogs)')

        engine.compute_all_similarities(
            top_n=options['top_n'],
            batch_size=options['batch_size']
        )

        elapsed = time.time() - start_time
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Complete!\n'
            f'   Movies processed: {movie_count}\n'
            f'   Similar movie records: up to {movie_count * options["top_n"]}\n'
            f'   Time: {elapsed:.1f}s\n\n'
            f'Next steps:\n'
            f'  python manage.py warm_engine    → Pre-load models into memory\n'
            f'  python manage.py regen_all_recs → Generate recs for all users'
        ))
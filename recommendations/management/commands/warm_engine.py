"""
============================================================
CineMatch - Warm Engine Management Command
(recommendations/management/commands/warm_engine.py)
============================================================

Pre-loads the recommendation engine (TF-IDF + SVD models)
into memory so the first user request is fast.

USAGE:
  python manage.py warm_engine

Run this after deploying or restarting the server.
============================================================
"""

from django.core.management.base import BaseCommand
import time


class Command(BaseCommand):
    help = 'Pre-warm the recommendation engine (loads ML models into memory)'

    def handle(self, *args, **options):
        self.stdout.write('🔥 Warming up recommendation engine...')
        start = time.time()

        from recommendations.tasks import warm_up_engine
        success = warm_up_engine()

        elapsed = time.time() - start

        if success:
            self.stdout.write(self.style.SUCCESS(
                f'✅ Engine ready in {elapsed:.2f}s\n'
                f'   Content engine (TF-IDF): ✓\n'
                f'   Collaborative engine (SVD): ✓\n'
                f'   Recommendations will now be served from memory.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                '❌ Engine warm-up failed. Check logs for details.\n'
                '   Make sure movies and ratings exist in the database.'
            ))
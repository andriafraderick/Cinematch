"""
============================================================
CineMatch - Regenerate All Recommendations Command
(recommendations/management/commands/regen_all_recs.py)
============================================================

Regenerates fresh recommendations for every active user.

USAGE:
  python manage.py regen_all_recs
  python manage.py regen_all_recs --min-ratings 3
  python manage.py regen_all_recs --user-id 42

Run after:
  - Adding new movies (sync_tmdb)
  - Recomputing similarities (compute_similarities)
  - Major algorithm weight changes (settings.py)
============================================================
"""

from django.core.management.base import BaseCommand
import time


class Command(BaseCommand):
    help = 'Regenerate recommendations for all active users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--min-ratings',
            type=int,
            default=1,
            help='Only regenerate for users with at least N ratings (default: 1)'
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Regenerate only for a specific user ID'
        )

    def handle(self, *args, **options):
        from recommendations.engine import HybridEngine
        from users.models import User

        self.stdout.write('🔄 Regenerating recommendations...')
        start = time.time()

        # Warm engine first
        engine = HybridEngine.get_instance()
        engine.ensure_ready()

        if options['user_id']:
            # Single user
            try:
                user = User.objects.get(id=options['user_id'])
                engine.generate_for_user(user)
                self.stdout.write(self.style.SUCCESS(
                    f'✅ Generated recommendations for {user.username}'
                ))
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'User ID {options["user_id"]} not found'))
            return

        # All users
        from recommendations.tasks import regenerate_all_recommendations
        success, errors = regenerate_all_recommendations()

        elapsed = time.time() - start
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Done in {elapsed:.1f}s\n'
            f'   Users updated: {success}\n'
            f'   Errors: {errors}'
        ))
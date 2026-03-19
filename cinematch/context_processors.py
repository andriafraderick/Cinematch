from django.conf import settings


def site_config(request):
    return {
        'SITE_NAME': getattr(settings, 'SITE_NAME', 'CineMatch'),
        'SITE_TAGLINE': getattr(settings, 'SITE_TAGLINE', 'Your AI-Powered Cinema Companion'),
        'DEBUG': settings.DEBUG,
        'TMDB_IMAGE_BASE': getattr(settings, 'TMDB_IMAGE_BASE', 'https://image.tmdb.org/t/p/w500'),
    }
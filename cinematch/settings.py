"""
============================================================
CineMatch - Django Settings
============================================================

This is the central configuration file for the entire project.
Django reads this file on startup to configure:
  - Database connection (PostgreSQL)
  - Installed apps (our custom apps + third party)
  - Authentication settings
  - Static/media file paths
  - REST framework configuration
  - ML model paths

FLOW:
  .env file → python-dotenv → this settings.py → Django runtime
============================================================
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta

# ------------------------------------------------------------
# BASE PATHS
# ------------------------------------------------------------
# Build paths inside the project like: BASE_DIR / 'subdir'.
# BASE_DIR points to the root 'cinematch/' folder.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
# This keeps secrets OUT of source code
load_dotenv(BASE_DIR / '.env')


# ------------------------------------------------------------
# SECURITY SETTINGS
# ------------------------------------------------------------
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-8r#y$04_8b&qs48)-c#er7au@18l65)!!_9m7b%8%_2(z#==eq')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')


# ------------------------------------------------------------
# INSTALLED APPS
# ------------------------------------------------------------
# Django discovers features based on what's listed here.
# Order matters: django apps first, then third-party, then our apps.
INSTALLED_APPS = [
    # --- Django Admin (jazzmin must be BEFORE django.contrib.admin) ---
            #'jazzmin',                          # Beautiful admin UI skin

    # --- Django Built-ins ---
    'django.contrib.admin',
    'django.contrib.auth',             # Authentication framework
    'django.contrib.contenttypes',     # Content type framework (used by auth)
    'django.contrib.sessions',         # Session management
    'django.contrib.messages',         # Flash messages
    'django.contrib.staticfiles',      # Static file serving

    # --- Third Party Libraries ---
    'rest_framework',                  # Django REST Framework - our API layer
    'rest_framework_simplejwt',        # JWT token authentication
    'corsheaders',                     # Allow frontend (JS) to call our API
    'django_filters',                  # Filtering support for API endpoints
    'django_extensions',               # Useful dev tools (shell_plus, etc.)

    # --- Our Custom Apps ---
    # Each app is a self-contained module with models, views, urls
    'users',                           # User profiles, auth, preferences
    'movies',                          # Movie catalog, genres, TMDB integration
    'interactions',                    # Ratings, watchlist, viewing history
    'recommendations',                 # ML engine, recommendation storage
    'api',                             # DRF serializers, viewsets, routers
]


# ------------------------------------------------------------
# MIDDLEWARE
# ------------------------------------------------------------
# Middleware processes every request/response as it passes through Django.
# Think of it as a chain of filters.
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',        # Must be first - handles CORS headers
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # Serve static files efficiently
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',   # CSRF protection on forms
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# ------------------------------------------------------------
# URL CONFIGURATION
# ------------------------------------------------------------
# The root URLconf - Django starts routing from here.
ROOT_URLCONF = 'cinematch.urls'



# ------------------------------------------------------------
# TEMPLATES
# ------------------------------------------------------------
# Django's template engine settings.
# Our HTML files live in templates/ directories inside each app,
# plus a top-level templates/ directory.
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],   # Global templates directory
        'APP_DIRS': True,                    # Also look in each app's templates/
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',  # Request object in templates
                'django.contrib.auth.context_processors.auth',  # User object in templates
                'django.contrib.messages.context_processors.messages',
                'cinematch.context_processors.site_config',          # Our custom global context
            ],
        },
    },
]

WSGI_APPLICATION = 'cinematch.wsgi.application'


# ------------------------------------------------------------
# DATABASE - PostgreSQL
# ------------------------------------------------------------
# All connection params come from .env for security.
# PostgreSQL is chosen over SQLite because:
#   - Better performance for complex ML queries
#   - Full-text search capabilities
#   - Better concurrent writes (ratings happening simultaneously)



# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': os.getenv('DB_NAME', 'cinematch_db'),
#         'USER': os.getenv('DB_USER', 'postgres'),
#         'PASSWORD': os.getenv('DB_PASSWORD', ''),
#         'HOST': os.getenv('DB_HOST', 'localhost'),
#         'PORT': os.getenv('DB_PORT', '5432'),
#         'OPTIONS': {
#             'connect_timeout': 10,
#         },
#     }
# }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# ------------------------------------------------------------
# AUTHENTICATION
# ------------------------------------------------------------
# We use Django's built-in User model extended with our UserProfile.
# AUTH_USER_MODEL points to our custom user (defined in users/models.py).
AUTH_USER_MODEL = 'users.User'

# Where Django redirects after login/logout
# LOGIN_URL = '/auth/login/'
# LOGIN_REDIRECT_URL = '/dashboard/'
# LOGOUT_REDIRECT_URL = '/'

LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/home/'
LOGOUT_REDIRECT_URL = '/'

# Password validation rules
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ------------------------------------------------------------
# REST FRAMEWORK CONFIGURATION
# ------------------------------------------------------------
# DRF controls how our API behaves globally.
# Individual views can override these per-endpoint.
REST_FRAMEWORK = {
    # Default auth: JWT tokens (stateless, good for APIs)
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',  # Fallback for browser
    ],
    # Default: require login to use API (can be overridden per view)
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    # Pagination - don't return all 10,000 movies at once
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    # Filtering
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    # Throttling - prevent API abuse
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
    },
}


# ------------------------------------------------------------
# JWT SETTINGS
# ------------------------------------------------------------
# SimpleJWT controls token lifetimes and behavior.
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),    # Short-lived access token
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),    # Longer-lived refresh token
    'ROTATE_REFRESH_TOKENS': True,                  # Issue new refresh token on use
    'BLACKLIST_AFTER_ROTATION': False,
    'AUTH_HEADER_TYPES': ('Bearer',),               # "Authorization: Bearer <token>"
}


# ------------------------------------------------------------
# CORS SETTINGS
# ------------------------------------------------------------
# Allow our frontend JavaScript to call the API.
# In production, replace with your actual domain.
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:8000",
]
CORS_ALLOW_CREDENTIALS = True


# ------------------------------------------------------------
# STATIC & MEDIA FILES
# ------------------------------------------------------------
# Static files: CSS, JS, images bundled with the app
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']        # Dev: look here for static files
STATIC_ROOT = BASE_DIR / 'staticfiles'           # Prod: collectstatic output directory

# Media files: user uploads (profile pictures, etc.)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# WhiteNoise: compress and cache static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# ------------------------------------------------------------
# INTERNATIONALIZATION
# ------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# ------------------------------------------------------------
# DEFAULT AUTO FIELD
# ------------------------------------------------------------
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ------------------------------------------------------------
# TMDB API CONFIGURATION
# ------------------------------------------------------------
# The Movie Database API - our source for movie data, posters, cast
# Sign up at: https://www.themoviedb.org/settings/api
TMDB_API_KEY = os.getenv('TMDB_API_KEY', '')
TMDB_BASE_URL = os.getenv('TMDB_BASE_URL', 'https://api.themoviedb.org/3')
TMDB_IMAGE_BASE = os.getenv('TMDB_IMAGE_BASE', 'https://image.tmdb.org/t/p/w500')


# ------------------------------------------------------------
# ML / RECOMMENDATION ENGINE SETTINGS
# ------------------------------------------------------------
# These control the hybrid recommendation algorithm behavior.
# See recommendations/engine.py for implementation.
RECOMMENDATION_SETTINGS = {
    # How many recommendations to generate per user
    'NUM_RECOMMENDATIONS': 20,

    # Hybrid model weights (must sum to 1.0)
    # Collaborative: "users like you also liked..."
    # Content-based: "because you liked [Movie X]..."
    'COLLABORATIVE_WEIGHT': 0.4,
    'CONTENT_WEIGHT': 0.6,

    # Minimum ratings before collaborative filtering kicks in
    # Below this threshold, we use content-based + popularity only
    'MIN_RATINGS_FOR_CF': 5,

    # Recalculate recommendations after N new interactions
    'RECALC_AFTER_N_INTERACTIONS': 3,

    # Cache recommendations for N seconds (avoid recalculating every page load)
    'CACHE_TTL_SECONDS': 3600,  # 1 hour
}


# ------------------------------------------------------------
# JAZZMIN ADMIN UI CONFIGURATION
# ------------------------------------------------------------
# Jazzmin replaces Django's default admin with a Material Design look.
# Docs: https://django-jazzmin.readthedocs.io/
# JAZZMIN_SETTINGS = {
#     # --- Branding ---
#     "site_title": "CineMatch Admin",
#     "site_header": "CineMatch",
#     "site_brand": "🎬 CineMatch",
#     "welcome_sign": "Welcome to CineMatch Admin",
#     "copyright": "CineMatch AI",

#     # --- Theme ---
#     "theme": "darkly",                  # Bootstrap dark theme
#     "dark_mode_theme": "darkly",

#     # --- Icons (FontAwesome) ---
#     "icons": {
#         "auth": "fas fa-users-cog",
#         "users.user": "fas fa-user",
#         "movies.movie": "fas fa-film",
#         "movies.genre": "fas fa-tags",
#         "interactions.rating": "fas fa-star",
#         "interactions.watchlistitem": "fas fa-bookmark",
#         "recommendations.recommendation": "fas fa-magic",
#     },

#     # --- Sidebar Navigation ---
#     "navigation_expanded": True,
#     "hide_apps": [],
#     "order_with_respect_to": ["users", "movies", "interactions", "recommendations"],

#     # --- UI Customization ---
#     "show_ui_builder": False,
#     "changeform_format": "horizontal_tabs",
#     "related_modal_active": True,

#     # --- Top Menu ---
#     "topmenu_links": [
#         {"name": "View Site", "url": "/", "new_window": False},
#         {"name": "API Docs", "url": "/api/", "new_window": False},
#     ],
# }

# JAZZMIN_UI_TWEAKS = {
#     "navbar": "navbar-dark",
#     "no_navbar_border": True,
#     "body_small_text": False,
#     "sidebar": "sidebar-dark-primary",
#     "brand_colour": "navbar-danger",
#     "accent": "accent-danger",
#     "sidebar_nav_small_text": False,
#     "sidebar_disable_expand": False,
#     "sidebar_nav_child_indent": True,
#     "sidebar_nav_compact_style": False,
#     "sidebar_nav_legacy_style": False,
#     "sidebar_nav_flat_style": False,
# }


# ------------------------------------------------------------
# SITE CONFIGURATION (used in templates via context processor)
# ------------------------------------------------------------
SITE_NAME = os.getenv('SITE_NAME', 'CineMatch')
SITE_TAGLINE = os.getenv('SITE_TAGLINE', 'Your AI-Powered Cinema Companion')
TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w500'



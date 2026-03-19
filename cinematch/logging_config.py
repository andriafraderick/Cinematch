"""
============================================================
CineMatch - Logging Configuration
(core/logging_config.py)
============================================================

Detailed logging configuration for the ML recommendation engine.
Add this to settings.py by importing:

    from core.logging_config import LOGGING

WHAT GETS LOGGED:
  - recommendations.*  → ML engine decisions, scores, timings
  - interactions.*     → Signal fires, rating saves
  - movies.*           → TMDB sync progress
  - django.request     → HTTP requests (WARNING only in prod)

LOG LEVELS:
  DEBUG   → Detailed ML internals (dev only)
  INFO    → Normal operations (sync progress, rec generation)
  WARNING → Non-critical issues (cold start fallback, missing data)
  ERROR   → Failures (API errors, DB issues)
============================================================
"""

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,

    # --- Formatters define log line format ---
    'formatters': {
        'verbose': {
            # Full format: timestamp + level + module + message
            'format': '{asctime} [{levelname}] {name}: {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'simple': {
            'format': '[{levelname}] {name}: {message}',
            'style': '{',
        },
    },

    # --- Handlers define WHERE logs go ---
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file_ml': {
            # Separate log file for ML engine output
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/ml_engine.log',
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'file_app': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/cinematch.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
        },
    },

    # --- Loggers define WHAT to log ---
    'loggers': {
        # Our ML engine — verbose during development
        'recommendations': {
            'handlers': ['console', 'file_ml'],
            'level': 'INFO',
            'propagate': False,
        },
        # Interaction signals
        'interactions': {
            'handlers': ['console', 'file_app'],
            'level': 'INFO',
            'propagate': False,
        },
        # Movie sync
        'movies': {
            'handlers': ['console', 'file_app'],
            'level': 'INFO',
            'propagate': False,
        },
        # Django internals — only warnings in production
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },

    # Root logger catches anything not matched above
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}
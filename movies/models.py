"""
============================================================
CineMatch - Movie Models (movies/models.py)
============================================================

This module defines the CONTENT LAYER — everything about movies
that CineMatch catalogs and recommends.

Data is sourced from TMDB API (see movies/tmdb_client.py).
The management command `python manage.py sync_tmdb` populates this.

MODEL HIERARCHY:
  Genre           ← Action, Comedy, Drama, etc.
  Person          ← Directors, Actors (shared cast/crew table)
  Movie           ← Core movie record (TMDB synced)
    ├── genres       → M2M to Genre
    ├── cast         → M2M to Person (through MovieCast)
    └── crew         → M2M to Person (through MovieCrew)
  StreamingLink   ← Where to watch each movie (JustWatch data)
  MovieImage      ← Backdrop images for the cinematic UI

HOW IT CONNECTS:
  Movie ←── rated by ──── User          (interactions/models.py)
  Movie ←── in list of ── WatchlistItem (interactions/models.py)
  Movie ←── recommended to ── User      (recommendations/models.py)
  Movie ──── has ──────────► StreamingLink
============================================================
"""

from django.db import models
from django.utils.text import slugify
from django.core.validators import MinValueValidator, MaxValueValidator


# ============================================================
# GENRE
# ============================================================
class Genre(models.Model):
    """
    Movie genres — Action, Drama, Comedy, Thriller, etc.

    Genres are used as FEATURES in the content-based ML model.
    Each genre is a dimension in the movie feature vector.

    Sourced from TMDB genre list.
    DATABASE TABLE: movies_genre
    """
    tmdb_id = models.IntegerField(
        unique=True,
        null=True,
        blank=True,
        help_text="TMDB genre ID - used to sync with TMDB API"
    )
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    icon = models.CharField(
        max_length=10,
        blank=True,
        help_text="Emoji icon for UI display: 🎬 💥 😂 etc."
    )

    class Meta:
        db_table = 'movies_genre'
        ordering = ['name']

    def save(self, *args, **kwargs):
        # Auto-generate slug from name on first save
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ============================================================
# PERSON (Actor / Director)
# ============================================================
class Person(models.Model):
    """
    A person in the film industry — actor, director, writer, etc.
    One person can have multiple roles across multiple movies.

    Used as FEATURES in content-based filtering:
    "Because you like Christopher Nolan movies..."

    DATABASE TABLE: movies_person
    """
    tmdb_id = models.IntegerField(unique=True, null=True, blank=True)
    name = models.CharField(max_length=200)
    profile_image_url = models.URLField(blank=True)
    biography = models.TextField(blank=True)
    birth_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'movies_person'
        ordering = ['name']

    def __str__(self):
        return self.name


# ============================================================
# MOVIE (Core Content Model)
# ============================================================
class Movie(models.Model):
    """
    The central model — a single movie in our catalog.

    FIELDS USED BY ML ENGINE:
      - genres          → genre-based content features
      - cast / director → person-based content features
      - keywords        → topic-based content features (JSON)
      - vote_average    → popularity baseline for cold start
      - release_year    → recency weighting

    TMDB SYNC:
      - tmdb_id is the foreign key to TMDB's database
      - Run `python manage.py sync_tmdb --pages 10` to populate

    DATABASE TABLE: movies_movie
    """

    # --- TMDB Identity ---
    tmdb_id = models.IntegerField(
        unique=True,
        db_index=True,
        help_text="TMDB movie ID — primary link to external data"
    )
    imdb_id = models.CharField(max_length=20, blank=True, db_index=True)

    # --- Core Info ---
    title = models.CharField(max_length=300, db_index=True)
    original_title = models.CharField(max_length=300, blank=True)
    slug = models.SlugField(max_length=350, unique=True, blank=True)
    overview = models.TextField(
        blank=True,
        help_text="Movie synopsis / description (from TMDB)"
    )
    tagline = models.CharField(max_length=500, blank=True)

    # --- Classification ---
    genres = models.ManyToManyField(
        Genre,
        related_name='movies',
        blank=True,
        help_text="Primary content feature for content-based filtering"
    )
    original_language = models.CharField(max_length=10, default='en')
    adult = models.BooleanField(
        default=False,
        help_text="Adult content flag — hidden by default (see UserProfile.include_adult_content)"
    )

    # --- Dates ---
    release_date = models.DateField(null=True, blank=True)
    release_year = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Denormalized year for faster filtering"
    )

    # --- Runtime ---
    runtime = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Runtime in minutes"
    )

    # --- Ratings & Popularity (from TMDB) ---
    vote_average = models.FloatField(
        default=0.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(10.0)],
        help_text="TMDB community rating (0-10) — used in cold-start recommendations"
    )
    vote_count = models.PositiveIntegerField(default=0)
    popularity = models.FloatField(
        default=0.0,
        help_text="TMDB popularity score — trending metric"
    )

    # --- ML Feature Storage ---
    # Keywords are stored as JSON for fast content-based feature extraction.
    # Example: ["space", "heist", "time travel", "artificial intelligence"]
    keywords = models.JSONField(
        default=list,
        blank=True,
        help_text="Topic keywords for content-based ML features"
    )
    # Pre-computed TF-IDF feature vector stored as JSON float list.
    # This is calculated by recommendations/engine.py and cached here
    # to avoid re-computing on every recommendation request.
    content_vector = models.JSONField(
        null=True,
        blank=True,
        help_text="Pre-computed content feature vector (DO NOT EDIT MANUALLY)"
    )

    # --- Images ---
    poster_path = models.CharField(
        max_length=300,
        blank=True,
        help_text="TMDB poster path (append to TMDB_IMAGE_BASE to get full URL)"
    )
    backdrop_path = models.CharField(
        max_length=300,
        blank=True,
        help_text="TMDB backdrop path — used as hero image in movie detail page"
    )

    # --- Cast & Crew ---
    cast = models.ManyToManyField(
        Person,
        through='MovieCast',
        related_name='acted_in',
        blank=True
    )
    crew = models.ManyToManyField(
        Person,
        through='MovieCrew',
        related_name='worked_on',
        blank=True
    )

    # --- Metadata ---
    budget = models.BigIntegerField(null=True, blank=True)
    revenue = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=50,
        default='Released',
        choices=[
            ('Released', 'Released'),
            ('In Production', 'In Production'),
            ('Post Production', 'Post Production'),
            ('Planned', 'Planned'),
            ('Canceled', 'Canceled'),
        ]
    )

    # --- System Fields ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_synced = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When TMDB data was last refreshed for this movie"
    )

    class Meta:
        db_table = 'movies_movie'
        ordering = ['-popularity', '-vote_average']
        indexes = [
            models.Index(fields=['release_year', 'vote_average']),
            models.Index(fields=['popularity']),
            models.Index(fields=['tmdb_id']),
        ]

    def save(self, *args, **kwargs):
        # Auto-generate slug from title + year (unique-safe)
        if not self.slug:
            base_slug = slugify(self.title)
            year = self.release_year or ''
            self.slug = f"{base_slug}-{year}" if year else base_slug

        # Denormalize release year from date for faster queries
        if self.release_date and not self.release_year:
            self.release_year = self.release_date.year

        super().save(*args, **kwargs)

    def __str__(self):
        year = f" ({self.release_year})" if self.release_year else ""
        return f"{self.title}{year}"

    
    @property
    def poster_url(self):
        if self.poster_path:
            path = self.poster_path
            if not path.startswith('/'):
                path = '/' + path
            return f"https://image.tmdb.org/t/p/w342{path}"
        # Generate a styled placeholder using the movie title
        title = self.title[:2].upper() if self.title else '??'
        colors = ['1a1a2e', '16213e', '0f3460', '533483', '2b2d42']
        color = colors[self.id % len(colors)]
        return f"https://via.placeholder.com/342x513/{color}/f5a623?text={title}"

    @property
    def backdrop_url(self):
        """Full URL to backdrop/hero image."""
        from django.conf import settings
        if self.backdrop_path:
            # Use larger image for backdrop: w1280 instead of w500
            base = settings.TMDB_IMAGE_BASE.replace('w500', 'w1280')
            return f"{base}{self.backdrop_path}"
        return "/static/img/no-backdrop.jpg"

    @property
    def director(self):
        """Returns the director(s) of this movie."""
        return Person.objects.filter(
            moviecrew__movie=self,
            moviecrew__job='Director'
        )

    @property
    def top_cast(self):
        """Returns top 5 cast members ordered by billing order."""
        return Person.objects.filter(
            moviecast__movie=self
        ).order_by('moviecast__order')[:5]

    def get_genre_list(self):
        """Returns genre names as a comma-separated string for display."""
        return ", ".join(self.genres.values_list('name', flat=True))


# ============================================================
# MOVIE CAST (Through Model)
# ============================================================
class MovieCast(models.Model):
    """
    Through model for Movie ↔ Person (acting roles).
    Stores additional data about the relationship (character name, billing order).

    DATABASE TABLE: movies_moviecast
    """
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    character = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(
        default=0,
        help_text="Billing order (0 = top billed)"
    )

    class Meta:
        db_table = 'movies_moviecast'
        ordering = ['order']
        unique_together = ['movie', 'person', 'character']

    def __str__(self):
        return f"{self.person.name} as {self.character} in {self.movie.title}"


# ============================================================
# MOVIE CREW (Through Model)
# ============================================================
class MovieCrew(models.Model):
    """
    Through model for Movie ↔ Person (crew roles).

    DATABASE TABLE: movies_moviecrew
    """
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    job = models.CharField(
        max_length=100,
        help_text="e.g., Director, Screenplay, Cinematography"
    )
    department = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = 'movies_moviecrew'
        unique_together = ['movie', 'person', 'job']

    def __str__(self):
        return f"{self.person.name} ({self.job}) on {self.movie.title}"


# ============================================================
# STREAMING LINK
# ============================================================
class StreamingLink(models.Model):
    """
    Where a movie can be streamed / rented / purchased.

    This is what makes CineMatch "Netflix-like but for discovery" —
    users find what to watch AND where to watch it.

    Data sources:
    - TMDB Watch Providers API (/movie/{id}/watch/providers)
    - Manual curation for region-specific availability

    DATABASE TABLE: movies_streaminglink
    """

    # Streaming service names
    PROVIDER_CHOICES = [
        ('netflix', 'Netflix'),
        ('prime', 'Amazon Prime Video'),
        ('disney', 'Disney+'),
        ('hotstar', 'Hotstar'),
        ('hulu', 'Hulu'),
        ('hbo', 'HBO Max'),
        ('apple', 'Apple TV+'),
        ('mubi', 'MUBI'),
        ('youtube', 'YouTube'),
        ('other', 'Other'),
    ]

    TYPE_CHOICES = [
        ('stream', 'Stream'),       # Included in subscription
        ('rent', 'Rent'),           # Pay per rental
        ('buy', 'Buy'),             # Purchase permanently
        ('free', 'Free with Ads'),
    ]

    movie = models.ForeignKey(
        Movie,
        on_delete=models.CASCADE,
        related_name='streaming_links'
    )
    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES)
    provider_name = models.CharField(max_length=100)  # Display name
    link_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='stream')
    url = models.URLField(help_text="Direct link to movie on the streaming platform")
    region = models.CharField(
        max_length=10,
        default='IN',
        help_text="ISO country code: IN, US, UK, etc."
    )
    price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price in local currency (for rent/buy types)"
    )
    provider_logo = models.URLField(
        blank=True,
        help_text="URL to provider logo image"
    )

    class Meta:
        db_table = 'movies_streaminglink'
        ordering = ['provider', 'link_type']

    def __str__(self):
        return f"{self.movie.title} on {self.provider_name} ({self.link_type})"
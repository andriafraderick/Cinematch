"""
============================================================
CineMatch - Users Views (users/views.py)
============================================================

These are TEMPLATE-BASED views — they render HTML pages
using Django's template engine (NOT the DRF API).

Difference from api/views.py:
  api/views.py     → returns JSON  (for frontend JS / mobile)
  users/views.py   → returns HTML  (for browser navigation)

Both layers access the same models and business logic.
The template views are used for:
  - Registration page  (/auth/register/)
  - Login page         (/auth/login/)
  - Onboarding page    (/auth/onboarding/)
  - Profile page       (/auth/profile/)
  - Dashboard          (/dashboard/)

These views will be properly completed in Part 4 (frontend).
For now they contain the logic — templates will be built next.

FLOW:
  Browser GET  → view renders template with context
  Browser POST → view validates form → saves → redirect
  Django auth  → session-based for template views
  API calls    → JWT-based (separate, for JS frontend)
============================================================
"""

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.generic import CreateView, UpdateView, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils import timezone
import logging
from django.contrib.auth.views import LoginView
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User, UserProfile
from movies.models import Genre
from interactions.models import Rating, WatchlistItem, WatchEvent

logger = logging.getLogger(__name__)


# ============================================================
# REGISTER VIEW
# ============================================================
class RegisterView(TemplateView):
    """
    User registration page.
    GET  /auth/register/ → show registration form
    POST /auth/register/ → create account, redirect to onboarding
    """
    template_name = 'registration/register.html'

    def get(self, request):
        # Redirect already-logged-in users
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, self.template_name)

    def post(self, request):
        """Handle registration form submission."""
        email = request.POST.get('email', '').strip().lower()
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        full_name = request.POST.get('full_name', '').strip()

        # Validate
        errors = {}
        if not email:
            errors['email'] = 'Email is required.'
        elif User.objects.filter(email=email).exists():
            errors['email'] = 'An account with this email already exists.'

        if not username:
            errors['username'] = 'Username is required.'
        elif User.objects.filter(username=username).exists():
            errors['username'] = 'This username is already taken.'
        elif len(username) < 3:
            errors['username'] = 'Username must be at least 3 characters.'

        if len(password) < 8:
            errors['password'] = 'Password must be at least 8 characters.'
        elif password != password_confirm:
            errors['password_confirm'] = 'Passwords do not match.'

        if errors:
            return render(request, self.template_name, {
                'errors': errors,
                'form_data': {'email': email, 'username': username, 'full_name': full_name}
            })

        # Create user (signals auto-create UserProfile)
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password,
            full_name=full_name
        )

        # Log them in immediately (session-based for template views)
        login(request, user, backend='users.backends.EmailAuthBackend')
        messages.success(request, f"Welcome to CineMatch, {username}! Let's set up your preferences.")

        logger.info(f"New user registered: {username} ({email})")
        return redirect('onboarding')


# ============================================================
# ONBOARDING VIEW
# ============================================================
class OnboardingView(LoginRequiredMixin, TemplateView):
    """
    First-time genre selection.
    GET  /auth/onboarding/ → show genre picker
    POST /auth/onboarding/ → save preferences, generate first recs, go to dashboard
    """
    template_name = 'registration/onboarding.html'
    login_url = '/auth/login/'

    def get(self, request):
        if request.user.is_onboarded:
            return redirect('dashboard')
        genres = Genre.objects.all().order_by('name')
        streaming_services = [
            'Netflix', 'Prime Video', 'Disney+',
            'Apple TV+', 'HBO Max', 'Hotstar',
            'JioCinema', 'Mubi', 'Criterion Channel'
        ]
        return render(request, self.template_name, {
            'genres': genres,
            'streaming_services': streaming_services,
        })

    def post(self, request):
        genre_ids = request.POST.getlist('genres')  # Multiple checkboxes

        if not genre_ids:
            messages.error(request, 'Please select at least one genre.')
            return redirect('onboarding')

        streaming_services = request.POST.getlist('streaming_services')

        # Save preferences to profile
        profile = request.user.profile
        profile.preferred_genres.set(genre_ids)
        profile.streaming_services = streaming_services
        profile.save()

        # Mark onboarded
        request.user.is_onboarded = True
        request.user.save(update_fields=['is_onboarded'])

        # Generate first recommendations
        try:
            from recommendations.tasks import generate_recommendations_for_user
            generate_recommendations_for_user(request.user, force_algorithm='genre')
        except Exception as e:
            logger.warning(f"Failed to generate initial recs: {e}")

        messages.success(request, "Your taste profile is set! Here are your first recommendations.")
        return redirect('dashboard')


# ============================================================
# PROFILE VIEW
# ============================================================
class ProfileView(LoginRequiredMixin, TemplateView):
    """
    User profile page — shows stats, ratings, preferences.
    GET  /auth/profile/
    """
    template_name = 'users/profile.html'
    login_url = '/auth/login/'

    def get(self, request):
        user = request.user
        context = {
            'user': user,
            'recent_ratings': Rating.objects.filter(user=user)
                .select_related('movie').order_by('-created_at')[:10],
            'total_ratings': user.total_ratings,
            'watchlist_count': WatchlistItem.objects.filter(user=user).count(),
            'watch_count': user.profile.total_movies_watched,
            'avg_rating': Rating.objects.filter(user=user)
                .values_list('score', flat=True),
            'all_genres': Genre.objects.all(),
        }
        return render(request, self.template_name, context)

    def post(self, request):
        """Handle profile update."""
        user = request.user
        user.full_name = request.POST.get('full_name', user.full_name)
        user.username = request.POST.get('username', user.username)

        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']

        user.save()

        # Update preferences
        genre_ids = request.POST.getlist('preferred_genres')
        streaming_services = request.POST.getlist('streaming_services')

        profile = user.profile
        if genre_ids:
            profile.preferred_genres.set(genre_ids)
        profile.streaming_services = streaming_services
        profile.preferred_language = request.POST.get('preferred_language', 'en')
        profile.include_adult_content = request.POST.get('include_adult_content') == 'on'
        profile.save()

        messages.success(request, 'Profile updated successfully.')
        return redirect('profile')


class CustomLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        # Generate JWT tokens and pass to template via cookie
        user = form.get_user()
        refresh = RefreshToken.for_user(user)
        response.set_cookie('cm_access', str(refresh.access_token), httponly=False)
        response.set_cookie('cm_refresh', str(refresh), httponly=False)
        return response
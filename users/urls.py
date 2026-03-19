# from django.urls import path
# from django.contrib.auth import views as auth_views
# from users.views import RegisterView, OnboardingView, ProfileView

# urlpatterns = [
#     path('login/', auth_views.LoginView.as_view(
#         template_name='registration/login.html',
#         redirect_authenticated_user=True,
#     ), name='login'),
#     path('logout/', auth_views.LogoutView.as_view(), name='logout'),
#     path('register/', RegisterView.as_view(), name='register'),
#     path('onboarding/', OnboardingView.as_view(), name='onboarding'),
#     path('profile/', ProfileView.as_view(), name='profile'),
# ]

from django.urls import path
from django.contrib.auth import views as auth_views
from users.views import RegisterView, OnboardingView, ProfileView, CustomLoginView

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        redirect_authenticated_user=True,
        next_page='/home/',
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', RegisterView.as_view(), name='register'),
    path('onboarding/', OnboardingView.as_view(), name='onboarding'),
    path('profile/', ProfileView.as_view(), name='profile'),
]
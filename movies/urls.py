# from django.urls import path
# from movies.views import HomeView, MovieDetailView, BrowseView, SearchView

# urlpatterns = [
#     path('', HomeView.as_view(), name='home'),
#     path('browse/', BrowseView.as_view(), name='browse'),
#     path('search/', SearchView.as_view(), name='search'),
#     path('movies/<slug:slug>/', MovieDetailView.as_view(), name='movie_detail'),
# ]

from django.urls import path
from django.contrib.auth import views as auth_views
from movies.views import HomeView, MovieDetailView, BrowseView, SearchView

urlpatterns = [
    # Root URL → login page for everyone
    path('', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        redirect_authenticated_user=True,
    ), name='home'),

    path('home/', HomeView.as_view(), name='movies_home'),
    path('browse/', BrowseView.as_view(), name='browse'),
    path('search/', SearchView.as_view(), name='search'),
    path('movies/<slug:slug>/', MovieDetailView.as_view(), name='movie_detail'),
]
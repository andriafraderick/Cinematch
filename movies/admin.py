from django.contrib import admin
from movies.models import Genre, Movie, Person, MovieCast, MovieCrew, StreamingLink

admin.site.register(Genre)
admin.site.register(Movie)
admin.site.register(Person)
admin.site.register(MovieCast)
admin.site.register(MovieCrew)
admin.site.register(StreamingLink)
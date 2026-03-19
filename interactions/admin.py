from django.contrib import admin
from interactions.models import Rating, WatchlistItem, WatchEvent, ViewHistory

admin.site.register(Rating)
admin.site.register(WatchlistItem)
admin.site.register(WatchEvent)
admin.site.register(ViewHistory)
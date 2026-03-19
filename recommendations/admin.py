from django.contrib import admin
from recommendations.models import Recommendation, RecommendationBatch, SimilarMovie

admin.site.register(Recommendation)
admin.site.register(RecommendationBatch)
admin.site.register(SimilarMovie)
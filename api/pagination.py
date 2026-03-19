"""
============================================================
CineMatch - API Pagination (api/pagination.py)
============================================================

Custom pagination classes for different endpoints.

WHY CUSTOM PAGINATION?
  - Movie lists: 20 per page (standard browsing)
  - Recommendations: return all (max 20) in one go (no pagination needed)
  - Search results: 10 per page (quicker scan)
  - Watchlist: 50 per page (users want to see more at once)

DRF Pagination adds these fields to list responses:
  {
    "count": 1000,           ← total items
    "next": "...?page=3",    ← URL of next page (null if last)
    "previous": "...?page=1",← URL of prev page (null if first)
    "results": [...]          ← actual items for this page
  }
============================================================
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """
    Default pagination: 20 items per page.
    Used for: movie lists, search results.

    Query params:
      ?page=2        → page number
      ?page_size=10  → override page size (up to max_page_size)
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class SmallPagination(PageNumberPagination):
    """
    Small pagination: 10 items per page.
    Used for: search suggestions, actor filmography.
    """
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class LargePagination(PageNumberPagination):
    """
    Large pagination: 50 items per page.
    Used for: watchlist (users want to see their full list).
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class RecommendationPagination(PageNumberPagination):
    """
    Recommendations: returns all recs in one response (no next/prev).
    Max 20 recs per batch (set in RECOMMENDATION_SETTINGS).
    """
    page_size = 20
    max_page_size = 20

    def get_paginated_response(self, data):
        """
        Enhanced response that includes algorithm metadata.
        The frontend uses this to show "Why was this recommended?" info.
        """
        return Response({
            'count': self.page.paginator.count,
            'results': data,
            # Metadata about the recommendation batch
            'meta': {
                'total_recommendations': self.page.paginator.count,
                'page': self.page.number,
            }
        })
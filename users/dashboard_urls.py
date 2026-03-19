from django.urls import path
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboard/dashboard.html'
    login_url = '/auth/login/'

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
]
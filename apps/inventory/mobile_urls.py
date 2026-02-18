from django.urls import path
from . import mobile_views

app_name = 'mobile'

urlpatterns = [
    path('', mobile_views.mobile_home, name='home'),
    path('move/', mobile_views.mobile_move, name='move'),
    path('history/', mobile_views.mobile_history, name='history'),
]

from django.contrib import admin

from .models import LabelSettings


@admin.register(LabelSettings)
class LabelSettingsAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'width_mm', 'height_mm', 'columns', 'dpi', 'updated_at')
    list_filter = ('dpi', 'columns')

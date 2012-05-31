from us_reactors.models import Facility, Reactor
from django.contrib import admin

class FacilityAdmin(admin.ModelAdmin):
    list_display = ('name', 'region', 'city', 'state',)
    list_filter = ('region', 'state',)

class ReactorAdmin(admin.ModelAdmin):
    list_display = ('short_title', 'nrc_id', 'facility',)
    list_filter = ('facility__region','facility__state')

admin.site.register(Facility, FacilityAdmin)
admin.site.register(Reactor, ReactorAdmin)
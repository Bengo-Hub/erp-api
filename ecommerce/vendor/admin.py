from django.contrib import admin
from .models import *

# Register your models here.
class RevieInline(admin.StackedInline):
    model=Review
    foreign_key='vendor'
    extra=0

@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    inlines=[RevieInline]
    list_display=['name',]

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display=['vendor','user','text','rating','created_at']
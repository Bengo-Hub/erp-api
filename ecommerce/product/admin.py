from django.contrib import admin
from .models import *
from business.models import Branch
from django import forms

# Register your models here.
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_per_page = 10
    list_display = ['id','name','parent','level','order','status']
    list_filter = ['parent','level','status']
    search_fields = ['name','status']
    list_editable = ['name','parent','level','order','status']
    list_display_links=['id']

@admin.register(ProductBrands)
class ProductBrandsAdmin(admin.ModelAdmin):
    list_per_page = 10

@admin.register(ProductModels)
class ProductModelsAdmin(admin.ModelAdmin):
    list_per_page = 10


class ProductImagesInline(admin.TabularInline):
    model=ProductImages
    extra=1

@admin.register(ProductImages)
class ProductImagesAdmin(admin.ModelAdmin):
    list_per_page = 10

@admin.register(Products)
class ProductsAdmin(admin.ModelAdmin):
    list_per_page = 10
    inlines = [ProductImagesInline]
    list_display = ['id','title','sku','serial','category','status','is_manufactured','model','brand', 'weight', 'dimentions','updated_at']
    list_filter = ['title','sku','serial','category','status','is_manufactured','model','brand']
    search_fields = ['title','sku','serial','category__name','status','is_manufactured','model','brand__title']
    list_editable = ['title','sku','serial','category','status','is_manufactured','model','brand', 'weight', 'dimentions']
    list_display_links=['id']

    fieldsets = (
        ('Product Information', {
            'fields': ('category','brand', 'model','title','sku','serial', 'description', 'weight', 'dimentions', 'status')
        }),
        )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        #print(qs)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter products based on the obtained branches
            qs = qs.filter(stock__branch__in=branches)
        return qs
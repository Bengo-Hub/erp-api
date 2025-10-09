from django.contrib import admin
from django.utils.html import format_html
from .models import Order

# Admin registration moved to core_orders.admin
# @admin.register(Order)
# class OrderAdmin(admin.ModelAdmin):
#     # ... admin configuration moved to core_orders

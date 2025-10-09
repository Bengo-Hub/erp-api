from django.db import models
from crm.contacts.models import *
# from django.contrib.auth import get_user_model
# User = get_user_model()


class Vendor(models.Model):
    name = models.CharField(max_length=255, default="TDBSoft")


    def __str__(self):
        return self.name

    class Meta:
        db_table = "vendors"
        managed = True
        verbose_name_plural = "Vendors"
        indexes = [
            models.Index(fields=['name'], name='idx_vendor_name'),
        ]


class Review(models.Model):
    vendor = models.ForeignKey(
        "Vendor", on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="reviews")
    text = models.TextField()
    rating = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.rating

    class Meta:
        db_table = "vendor_ratiings"
        managed = True
        verbose_name_plural = "Vendor Ratings"
        indexes = [
            models.Index(fields=['vendor'], name='idx_vendor_review_vendor'),
            models.Index(fields=['user'], name='idx_vendor_review_user'),
            models.Index(fields=['rating'], name='idx_vendor_review_rating'),
            models.Index(fields=['created_at'], name='idx_vendor_review_created_at'),
        ]

from django.db import models
from datetime import datetime
from django.utils import timezone
from django.core.validators import MinLengthValidator
from django.contrib.auth import get_user_model
from business.models import Bussiness,Branch
from crm.contacts.models import Contact
from ecommerce.stockinventory.models import StockInventory
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from decimal import Decimal

User = get_user_model()
# Create your models here.
class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ApiRequestMetric(models.Model):
    """Store API request performance metrics."""
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=512)
    status_code = models.PositiveIntegerField()
    duration_ms = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('0.000'))
    query_count = models.PositiveIntegerField(default=0)
    user_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_api_request_metrics'
        verbose_name = 'API Request Metric'
        verbose_name_plural = 'API Request Metrics'
        indexes = [
            models.Index(fields=['created_at'], name='idx_api_metric_created_at'),
            models.Index(fields=['path'], name='idx_api_metric_path'),
            models.Index(fields=['method'], name='idx_api_metric_method'),
            models.Index(fields=['status_code'], name='idx_api_metric_status'),
        ]


class QueryPerformanceMetric(models.Model):
    """Store function-level performance metrics (decorator-assisted)."""
    operation = models.CharField(max_length=255)
    duration_ms = models.DecimalField(max_digits=10, decimal_places=3, default=Decimal('0.000'))
    query_count = models.PositiveIntegerField(default=0)
    extra = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_query_performance_metrics'
        verbose_name = 'Query Performance Metric'
        verbose_name_plural = 'Query Performance Metrics'
        indexes = [
            models.Index(fields=['operation'], name='idx_query_metric_operation'),
            models.Index(fields=['created_at'], name='idx_query_metric_created_at'),
        ]

# CompanyDetails deprecated; use business.Bussiness across the app

# EmailConfigs and EmailLogs moved to centralized notifications app
# Use: from notifications.models import EmailConfiguration, EmailLog

class ContractSetting(models.Model):
    emai_to = models.EmailField(max_length=100,default="titusowuor30@gmail.com")
    cc_emai_to = models.EmailField(max_length=100,default="titusowuor30@gmail.com")
    duration=models.PositiveIntegerField(default=30,help_text="Send notifications 30 days to expiry")

    def __str__(self) -> str:
        return self.emai_to

    class Meta:
        pass
        #verbose_name_plural = 'Email Configuration'

class Regions(models.Model):
    code=models.CharField(max_length=100)
    name=models.CharField(max_length=255)
    parent_region = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='child_regions')

    def __str__(self) -> str:
        return self.name

    class Meta:
        db_table="regions"
        managed=True
        verbose_name_plural = 'Regions'
        indexes = [
            models.Index(fields=['code'], name='idx_regions_code'),
            models.Index(fields=['name'], name='idx_regions_name'),
            models.Index(fields=['parent_region'], name='idx_regions_parent'),
        ]

class Departments(models.Model):
    parent_departyment = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='child_departments')
    code=models.CharField(max_length=100)
    title=models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.title

    class Meta:
        db_table="departments"
        managed=True
        verbose_name_plural = 'Departments'
        indexes = [
            models.Index(fields=['code'], name='idx_departments_code'),
            models.Index(fields=['title'], name='idx_departments_title'),
            models.Index(fields=['parent_departyment'], name='idx_departments_parent'),
        ]

class Projects(models.Model):
    category = models.ForeignKey("ProjectCategory", on_delete=models.CASCADE, null=True, blank=True, related_name='projects')
    code=models.CharField(max_length=100,verbose_name="Project Code/No.")
    title=models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.title

    class Meta:
        db_table="projects"
        managed=True
        verbose_name_plural = 'Projects'
        indexes = [
            models.Index(fields=['code'], name='idx_projects_code'),
            models.Index(fields=['title'], name='idx_projects_title'),
            models.Index(fields=['category'], name='idx_projects_category'),
        ]

class ProjectCategory(models.Model):
    title=models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.title

    class Meta:
        db_table="project_categories"
        managed=True
        verbose_name_plural = 'Project Categories'

class BankInstitution(models.Model):
    """Bank institution model (KCB, Equity, etc.)"""
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=10, unique=True)
    short_code = models.CharField(max_length=10, unique=True)
    swift_code = models.CharField(max_length=11, blank=True, null=True)
    country = models.CharField(max_length=100, default='Kenya')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        db_table = "bank_institutions"
        managed = True
        verbose_name = 'Bank Institution'
        verbose_name_plural = 'Bank Institutions'
        indexes = [
            models.Index(fields=['name'], name='idx_bank_inst_name'),
            models.Index(fields=['code'], name='idx_bank_inst_code'),
            models.Index(fields=['short_code'], name='idx_bank_inst_short_code'),
            models.Index(fields=['is_active'], name='idx_bank_inst_active'),
        ]


class BankBranches(models.Model):
    """Bank branch model for specific bank locations"""
    bank = models.ForeignKey(BankInstitution, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=10)
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} - {self.bank.name}"

    class Meta:
        db_table = "bank_branches"
        managed = True
        verbose_name = 'Bank Branch'
        verbose_name_plural = 'Bank Branches'
        unique_together = ['bank', 'code']
        indexes = [
            models.Index(fields=['bank'], name='idx_bank_branches_bank'),
            models.Index(fields=['name'], name='idx_bank_branches_name'),
            models.Index(fields=['code'], name='idx_bank_branches_code'),
            models.Index(fields=['is_active'], name='idx_bank_branches_active'),
        ]

class AppSettings(models.Model):
    name=models.CharField(max_length=255,default="Default")
    app_key=models.CharField(max_length=256,default="Nxp43nyKv9k-O9p_IBxvEzBtdk_43O7lNrvEsRSe5H0=")
    cypher_key=models.CharField(max_length=256,default="Nxp43nyKv9k-O9p_IBxvEzBtdk_43O7lNrvEsRSe5H0=")

    def __str__(self):
        return "App Settings"

# Banner model moved to centralized campaigns app
# Use: from crm.campaigns.models import Campaign

class Blog(models.Model):
    author = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='blogs',null=True)
    title = models.CharField(
        max_length=255, default="Yuletide Zen: Finding Balance in Festivity")
    featured_image = models.ImageField(upload_to='Blog/featured', null=True)
    excerpt = models.TextField(default="Dive into the season of joy and mindfulness with Yogi's Delight! Explore our guide on maintaining serenity amidst the festive bustle. From calming yoga routines to mindful gift-giving, discover how you can infuse your holidays with peace and positivity.")
    date_created=models.DateTimeField(default=datetime.now())
    published=models.BooleanField(default=False)

    def __str__(self):
        return self.title

    class Meta:
        db_table = 'blog'
        verbose_name = 'Blog'
        verbose_name_plural = 'Blog'
        indexes = [
            models.Index(fields=['author'], name='idx_blog_author'),
            models.Index(fields=['published'], name='idx_blog_published'),
            models.Index(fields=['date_created'], name='idx_blog_date_created'),
        ]

class Post(models.Model):
    blog=models.ForeignKey(Blog,on_delete=models.CASCADE,related_name='posts')
    title=models.CharField(max_length=255)
    content=models.TextField(default='Yogis official store')
    image=models.ImageField(upload_to='Blog/posts')

    def __str__(self):
        return self.title

    class Meta:
        db_table = 'blog_posts'
        verbose_name = 'Blog Post'
        verbose_name_plural = 'Blog Posts'
        indexes = [
            models.Index(fields=['blog'], name='idx_post_blog'),
            models.Index(fields=['title'], name='idx_post_title'),
        ]

class Comments(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='comments')
    post=models.ForeignKey(Post,on_delete=models.CASCADE,related_name='comments')
    comment=models.TextField()

    def __str__(self):
        return self.user.email

    class Meta:
        db_table = 'post_comments'
        verbose_name = 'Post Comment'
        verbose_name_plural = 'Post Comments'
        indexes = [
            models.Index(fields=['user'], name='idx_comments_user'),
            models.Index(fields=['post'], name='idx_comments_post'),
        ]

class OvertimeRate(models.Model):
    # Overtime types for configuring overtime rates
    OVERTIME_TYPES = [
        ("Normal", "Normal Working Days"),
        ("Weekend", "Non-working Days (e.g. Weekend)"),
        ("Holiday", "Holidays"),
    ]
    overtime_type = models.CharField(max_length=20, choices=OVERTIME_TYPES)
    overtime_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('2.00')) 
    fixed_amount=models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00')) 
    is_active = models.BooleanField(default=True) 

    def save(self, *args, **kwargs):
        if self.overtime_type=='Normal':
            self.fixed_amount=Decimal('200.00')
            self.overtime_rate=Decimal('1.50')
        super(OvertimeRate,self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.overtime_type} - {self.overtime_rate}x"

    class Meta:
        indexes = [
            models.Index(fields=['overtime_type'], name='idx_overtime_rate_type'),
            models.Index(fields=['is_active'], name='idx_overtime_rate_active'),
        ]
    
class PartialMonthPay(models.Model):
    # Prorating Options for Partial Months
    PRORATE_OPTIONS = [
        ("Calendar", "Prorate Based on Calendar Days"),
        ("Daily Rate", "Prorate Based on Daily Rate"),
        ("Full Month", "Pay Full Month, No Prorate"),
    ]

    prorate_option = models.CharField(max_length=20, choices=PRORATE_OPTIONS, default="Calendar")
    prorate_from_start = models.BooleanField(default=True) 
    carry_forward_prorated_pay = models.BooleanField(default=False)
    apply_for = models.CharField(max_length=20, choices=[("Basic", "Basic Pay"), ("All", "All Pay")], default="Basic")
    is_active = models.BooleanField(default=True) 

    def __str__(self):
        return f"{self.prorate_option} - {self.is_active}"

    class Meta:
        indexes = [
            models.Index(fields=['prorate_option'], name='idx_partial_month_pay_option'),
            models.Index(fields=['is_active'], name='idx_partial_month_pay_active'),
        ]


class Location(models.Model):
    """
    Legacy Location model - Use business.Branch instead for multi-branch support.
    This model is kept for backward compatibility but should not be used for new features.
    """
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, unique=True)
    address = models.TextField(blank=True)
    region = models.ForeignKey(Regions, on_delete=models.SET_NULL, null=True, blank=True, related_name='locations')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'locations'
        managed = True
        verbose_name_plural = 'Locations'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name'], name='idx_location_name'),
            models.Index(fields=['code'], name='idx_location_code'),
            models.Index(fields=['region'], name='idx_location_region'),
            models.Index(fields=['is_active'], name='idx_core_location_active'),
        ]

# Approval model moved to approvals app - import from there
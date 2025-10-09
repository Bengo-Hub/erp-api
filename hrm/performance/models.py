from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from hrm.employees.models import Employee
from authmanagement.models import CustomUser

class MetricCategory(models.Model):
    """Categories for organizing performance metrics"""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_metric_categories')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'Metric Categories'

    def __str__(self):
        return self.name

class PerformanceMetric(models.Model):
    """Individual performance metrics that can be assigned to employees"""
    METRIC_TYPES = [
        ('numeric', 'Numeric'),
        ('percentage', 'Percentage'),
        ('boolean', 'Boolean'),
        ('rating', 'Rating'),
        ('text', 'Text')
    ]

    category = models.ForeignKey(MetricCategory, on_delete=models.CASCADE, related_name='metrics')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    metric_type = models.CharField(max_length=20, choices=METRIC_TYPES)
    unit = models.CharField(max_length=50, blank=True)  # e.g., 'hours', 'items', '%'
    min_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    target_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_performance_metrics')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__order', 'name']

    def __str__(self):
        return f"{self.category.name} - {self.name}"

    @property
    def metric_type_display(self):
        return dict(self.METRIC_TYPES).get(self.metric_type, self.metric_type)

class EmployeeMetric(models.Model):
    """Employee-specific metric values and tracking"""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='performance_metrics')
    metric = models.ForeignKey(PerformanceMetric, on_delete=models.CASCADE, related_name='employee_metrics')
    value = models.TextField()  # Store as text to handle different metric types
    numeric_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    date_recorded = models.DateField()
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='recorded_employee_metrics')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_recorded', '-created_at']
        unique_together = ['employee', 'metric', 'date_recorded']

    def __str__(self):
        return f"{self.employee.user.get_full_name()} - {self.metric.name} ({self.date_recorded})"

    def save(self, *args, **kwargs):
        # Convert value to numeric_value if metric type supports it
        if self.metric.metric_type in ['numeric', 'percentage', 'rating']:
            try:
                self.numeric_value = float(self.value)
            except (ValueError, TypeError):
                self.numeric_value = None
        super().save(*args, **kwargs)

class MetricTarget(models.Model):
    """Target values for metrics by employee and period"""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='metric_targets')
    metric = models.ForeignKey(PerformanceMetric, on_delete=models.CASCADE, related_name='targets')
    target_value = models.DecimalField(max_digits=10, decimal_places=2)
    period_start = models.DateField()
    period_end = models.DateField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_metric_targets')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-period_start']
        unique_together = ['employee', 'metric', 'period_start', 'period_end']

    def __str__(self):
        return f"{self.employee.user.get_full_name()} - {self.metric.name} Target"

class PerformanceReview(models.Model):
    """Performance reviews that can include multiple metrics"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='performance_reviews')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    review_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    overall_rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True,
                                       validators=[MinValueValidator(0), MaxValueValidator(5)])
    comments = models.TextField(blank=True)
    reviewer = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, related_name='conducted_reviews')
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_performance_reviews')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-review_date', '-created_at']

    def __str__(self):
        return f"{self.employee.user.get_full_name()} - {self.title}"

class ReviewMetric(models.Model):
    """Metrics included in a performance review"""
    review = models.ForeignKey(PerformanceReview, on_delete=models.CASCADE, related_name='review_metrics')
    metric = models.ForeignKey(PerformanceMetric, on_delete=models.CASCADE, related_name='review_metrics')
    value = models.TextField()
    rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True,
                               validators=[MinValueValidator(0), MaxValueValidator(5)])
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['metric__category__order', 'metric__name']
        unique_together = ['review', 'metric']

    def __str__(self):
        return f"{self.review} - {self.metric.name}"

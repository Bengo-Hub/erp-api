from django.db import models
from django.utils import timezone
from authmanagement.models import CustomUser
from hrm.employees.models import Employee
from django.core.validators import MinValueValidator, MaxValueValidator

class AppraisalCycle(models.Model):
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('activated', 'Activated'),
        ('closed', 'Closed'),
        ('reopened', 'Reopened')
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='created')
    locations = models.ManyToManyField('core.Regions', related_name='appraisal_cycles')
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_appraisal_cycles')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.start_date} - {self.end_date})"

    class Meta:
        ordering = ['-created_at']

class AppraisalTemplate(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class AppraisalQuestion(models.Model):
    QUESTION_TYPES = [
        ('text', 'Text'),
        ('rating', 'Rating'),
        ('multiple_choice', 'Multiple Choice'),
        ('yes_no', 'Yes/No')
    ]

    template = models.ForeignKey(AppraisalTemplate, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES)
    is_required = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.template.name} - {self.question_text[:50]}"

    class Meta:
        ordering = ['order']

class Appraisal(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ]

    cycle = models.ForeignKey(AppraisalCycle, on_delete=models.CASCADE, related_name='appraisals')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='appraisals')
    evaluator = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, related_name='evaluated_appraisals')
    template = models.ForeignKey(AppraisalTemplate, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    overall_rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True,
                                       validators=[MinValueValidator(0), MaxValueValidator(5)])
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee.user.get_full_name()} - {self.cycle.name}"

    class Meta:
        ordering = ['-created_at']

class AppraisalResponse(models.Model):
    appraisal = models.ForeignKey(Appraisal, on_delete=models.CASCADE, related_name='responses')
    question = models.ForeignKey(AppraisalQuestion, on_delete=models.CASCADE)
    response = models.TextField()
    rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True,
                               validators=[MinValueValidator(0), MaxValueValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.appraisal} - {self.question.question_text[:50]}"

class Goal(models.Model):
    STATUS_CHOICES = [
        ('not_started', 'Not Started'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='goals')
    title = models.CharField(max_length=255)
    description = models.TextField()
    start_date = models.DateField(blank=True,null=True)
    end_date = models.DateField(blank=True,null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='not_started')
    progress = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    is_template = models.BooleanField(default=False)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee.user.get_full_name()} - {self.title}"

    class Meta:
        ordering = ['-created_at']

class GoalProgress(models.Model):
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name='progress_updates')
    progress = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    comments = models.TextField()
    updated_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.goal} - {self.progress}%"

    class Meta:
        ordering = ['-created_at'] 
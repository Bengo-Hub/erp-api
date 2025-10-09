from django.db import models
from django.utils import timezone
from hrm.employees.models import Employee


class TrainingCourse(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    capacity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.title

    class Meta:
        db_table = "hrm_training_courses"
        ordering = ["-start_date"]


class TrainingEnrollment(models.Model):
    STATUS_CHOICES = (
        ("enrolled", "Enrolled"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    )
    course = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="enrollments")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="enrollments")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="enrolled")
    enrolled_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "hrm_training_enrollments"
        unique_together = ("course", "employee")
        ordering = ["-enrolled_at"]
        indexes = [
            models.Index(fields=["course", "status"], name="idx_train_course_status"),
        ]


class TrainingEvaluation(models.Model):
    course = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="evaluations")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="training_evaluations")
    rating = models.PositiveIntegerField(default=0)
    feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hrm_training_evaluations"
        ordering = ["-created_at"]

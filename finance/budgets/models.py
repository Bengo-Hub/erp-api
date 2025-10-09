from django.db import models
from django.utils import timezone
from hrm.employees.models import Employee


class Budget(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("archived", "Archived"),
    )
    name = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    created_by = models.ForeignKey('authmanagement.CustomUser', on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'finance_budgets'
        ordering = ['-start_date']

    def __str__(self) -> str:
        return self.name


class BudgetLine(models.Model):
    CATEGORY_CHOICES = (
        ("revenue", "Revenue"),
        ("expense", "Expense"),
        ("capex", "Capital Expenditure"),
        ("other", "Other"),
    )
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='lines')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'finance_budget_lines'
        indexes = [
            models.Index(fields=['budget', 'category'], name='idx_budget_cat'),
        ]

    def __str__(self) -> str:
        return f"{self.budget.name} - {self.name}"

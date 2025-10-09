from django.db import models
from django.utils import timezone
from finance.accounts.models import PaymentAccounts, Transaction
from finance.payment.models import Payment


class BankStatementLine(models.Model):
    account = models.ForeignKey(PaymentAccounts, on_delete=models.CASCADE, related_name='statement_lines')
    statement_date = models.DateField()
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    external_ref = models.CharField(max_length=100, blank=True, null=True)
    matched_transaction = models.ForeignKey(Transaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='matched_statement_lines')
    matched_payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name='matched_statement_lines')
    is_reconciled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'finance_bank_statement_lines'
        ordering = ['-statement_date']
        indexes = [
            models.Index(fields=['account', 'statement_date'], name='idx_stmt_acc_date'),
        ]

    def __str__(self) -> str:
        return f"{self.account.name} - {self.statement_date} - {self.amount}"



from datetime import timedelta, timezone
from celery import shared_task
from notifications.services import EmailService
from hrm.employees.models import Contract


@shared_task
def check_expiring_contracts():
    try:
        print("Contracts background task running...!")
        today = timezone.now().date()
        one_month_from_now = today + timedelta(days=30)

        # Query contracts expiring in one month
        expiring_contracts = Contract.objects.filter(
            contract_end_date__lte=one_month_from_now,
            contract_end_date__gte=today
        )

        for contract in expiring_contracts:
            employee = contract.employee
            # Send reminder email using Celery
            subject = 'Contract Expiration Reminder'
            message = f'Hello {employee.user.first_name}, your contract is expiring on {contract.contract_end_date}.'
            recipient_list = [employee.user.email]
            email_service = EmailService()
            email_service.send_email(
                subject=subject,
                message=message,
                recipient_list=recipient_list,
                async_send=True
            )
            print(f"Email task triggered for {employee.user.email}")

        # Update expired contracts
        expired_contracts = Contract.objects.filter(contract_end_date__lt=today)
        expired_contracts.update(status='expired')
    except Exception as e:
        print("Contracts background task error: " + str(e))
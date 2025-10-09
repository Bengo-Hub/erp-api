# tasks.py
from celery import shared_task, group, chord
from hrm.employees.models import Employee
from hrm.payroll.utils import PayrollGenerator

@shared_task
def process_payslip(employee_id, payment_period, recover_advances, command):
    """
    Celery task to process a single employee's payslip.
    This is a legacy wrapper for backward compatibility.
    """
    try:
        employee = Employee.objects.get(id=employee_id)
        payroll_result = PayrollGenerator(None, employee, payment_period, recover_advances, command).generate_payroll()
        return payroll_result
    except Exception as e:
        return {"employee_id": employee_id, "error": str(e)}

@shared_task
def schedule_payslips(employee_ids, payment_period, recover_advances, command):
    """
    Celery task to schedule payslips for multiple employees.
    This is a legacy wrapper for backward compatibility.
    """
    try:
        # Import the new batch processing task
        from hrm.payroll.tasks import batch_process_payslips
        
        # Use the new batch processing task
        return batch_process_payslips.delay(
            employee_ids=employee_ids,
            payment_period=payment_period,
            recover_advances=recover_advances,
            command=command,
            user_id=None
        ).get()
    except Exception as e:
        print(e)
        return {"error": str(e)}
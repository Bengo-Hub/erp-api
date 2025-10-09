from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import permissions
from notifications.services import EmailService
from hrm.employees.models import Employee
from datetime import datetime, date
from rest_framework.exceptions import ValidationError
from rest_framework import viewsets, status
import json
from hrm.payroll.utils import PayrollGenerator
from .tasks import batch_process_payslips, process_single_payslip, rerun_payslip
from .models import Payslip
from .serializers import *
from itertools import groupby
from django.db.models import Sum, Count, Q
from django.contrib.contenttypes.models import ContentType
from rest_framework.decorators import action
from collections import defaultdict
from django.http import JsonResponse
from rest_framework.views import APIView
from django.core.files.uploadedfile import UploadedFile
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from rest_framework.pagination import PageNumberPagination
from django.core.cache import cache
from core.cache import cache_result, get_cache_key
# Import our new task modules
from hrm.payroll.tasks import process_single_payslip, batch_process_payslips, distribute_payslips_by_email, generate_payroll_reports
from core.modules.email_tasks import send_email_with_retry, send_bulk_emails
from rest_framework.decorators import api_view
from .analytics.payroll_analytics import PayrollAnalyticsService
from rest_framework.decorators import action
from rest_framework import status
from django.contrib.auth import get_user_model
from .services.payroll_approval_service import PayrollApprovalService

User = get_user_model()


class ProcessPayrollViewSet(viewsets.ViewSet):
    queryset = Payslip.objects.all()
    serializer_class = PayslipSerializer
    permission_classes=[IsAuthenticated]
    pagination_class = PageNumberPagination  # Enable pagination

    def get_object(self, pk):
        # Helper method to retrieve a Payslip instance
        return Payslip.objects.get(pk=pk)

    def retrieve(self, request, pk=None):
        try:
            # Get the payslip object by ID (pk)
            payslip = self.get_object(pk)
            serializer = self.serializer_class(payslip)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Payslip.DoesNotExist:
            return Response({"detail": "Payslip not found."}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['get'], url_path='employees')
    def get_employees(self, request):
        fromdate = request.query_params.get("fromdate", None)
        todate = request.query_params.get("todate", None)
        employement_type = request.query_params.getlist('employement_type', None)
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)

        # Start with base queryset
        employees = Employee.objects.all()
        
        # Apply filters dynamically
        if department_ids:
            employees = employees.filter(hr_details__department_id__in=department_ids)
        
        # Apply employment type filter - this is the key fix
        if employement_type:
            # Ensure we only get employees with the specified employment types
            # This will exclude casual and consultant employees if they're not in the selected types
            employees = employees.filter(salary_details__employment_type__in=employement_type)
            print(f"Filtering by employment types: {employement_type}")
            print(f"Employees found after employment type filter: {employees.count()}")
        else:
            # If no employment types specified, exclude casual and consultant by default
            # as they have different payroll processing flows
            employees = employees.exclude(
                salary_details__employment_type__in=['casual', 'consultant']
            )
            print("No employment types specified, excluding casual and consultant employees by default")
        
        if region_ids:
            employees = employees.filter(hr_details__region_id__in=region_ids)
        
        # Validate payment period types and filter by payroll date
        if fromdate and todate:
            try:
                # Strip the time part from the date strings
                fromdate = datetime.strptime(fromdate[:10], "%Y-%m-%d").date()
                todate = datetime.strptime(todate[:10], "%Y-%m-%d").date()
                employees = employees.filter(
                    contracts__status='active',
                    contracts__contract_end_date__gte=fromdate
                )
                print(f"Filtering by date range: {fromdate} to {todate}")
                print(f"Employees found after date filter: {employees.count()}")
            except ValueError as e:
                return Response({
                    "detail": str(e) + ". Invalid date format for payroll date range. Use YYYY-MM-DD.", 
                    "success": False
                })

        # Final count for debugging
        final_count = employees.count()
        print(f"Final employee count for payroll processing: {final_count}")
        
        # Log employment types distribution for debugging
        if final_count > 0:
            employment_distribution = employees.values_list(
                'salary_details__employment_type', flat=True
            ).distinct()
            print(f"Employment types in final result: {list(employment_distribution)}")

        serializer = PayrollEmployeeSerializer(employees, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def list(self, request):
        fromdate = request.query_params.get("fromdate", None)
        todate = request.query_params.get("todate", None)
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        employee_ids = request.query_params.getlist("employee_ids[]", None)

        # Apply filters dynamically
        payslips = Payslip.objects.filter(payroll_status='complete',delete_status=False).order_by('employee__id')
        if department_ids:
            payslips = payslips.filter(employee__hr_details__department_id__in=department_ids)
        if region_ids:
            payslips = payslips.filter(employee__hr_details__region_id__in=region_ids)
        if employee_ids:
            payslips = payslips.filter(employee__id__in=employee_ids).order_by('employee__id')

         # Validate payment period types and filter by payroll date
        if fromdate and todate:
            try:
                # Strip the time part from the date strings
                fromdate = datetime.strptime(fromdate[:10], "%Y-%m-%d").date()
                todate = datetime.strptime(todate[:10], "%Y-%m-%d").date()
                payslips = payslips.filter(payment_period__range=[fromdate, todate])
            except ValueError as e:
                return Response({"detail": str(e) + ". Invalid date format for payroll date range. Use YYYY-MM-DD.", "success": False})

        # Group payslips by payment_period month
        grouped_payslips = payslips.values('payment_period__year', 'payment_period__month').annotate(
            total_payslips=Count('id'),
            total_basic_pay=Sum('employee__salary_details__monthly_salary'),
            total_net_pay=Sum('net_pay'),
            approved_count=Count('id', filter=Q(approval_status='approved')),
            unapproved_count=Count('id', filter=~Q(approval_status='approved'))
        ).order_by('payment_period__year', 'payment_period__month').distinct()

        # Prepare final response with payslip details per month
        response_data = []
        for group in grouped_payslips:
            year = group['payment_period__year']
            month = group['payment_period__month']

            # Filter individual payslips for this specific year and month
            individual_payslips = payslips.filter(payment_period__year=year, payment_period__month=month)
            individual_payslips_data = PayslipSerializer(individual_payslips, many=True).data

            # Append grouped data along with individual payslips
            response_data.append({
                "year": year,
                "month": month,
                "total_payslips": group['total_payslips'],
                "total_basic_pay": group['total_basic_pay'],
                "total_net_pay": group['total_net_pay'],
                "approved_payslips": group['approved_count'],
                "unapproved_payslips": group['unapproved_count'],
                "payslips": individual_payslips_data
            })

        return Response(response_data)
    
    def create(self, request):
        # Get payment period and other data from request.data (for POST requests)
        payment_period = request.data.get("payment_period", None)
        department_ids = request.data.get("department", None)
        region_ids = request.data.get("region", None)
        project_ids = request.data.get("project", None)
        employee_ids = request.data.get("employee_ids", None)
        recover_advances = request.data.get("recover_advances", False)
        command = request.data.get("command", "queue")
        process_async = request.data.get("async", True)  # New parameter for async processing

        # Validate payment_period type
        if isinstance(payment_period, str):
            try:
                # Try full date first (YYYY-MM-DD)
                payment_period = datetime.strptime(payment_period, "%Y-%m-%d").date()
            except ValueError:
                try:
                    # Fallback to month-only (YYYY-MM)
                    payment_period = datetime.strptime(payment_period, "%Y-%m").date()
                except ValueError:
                    return Response({
                        "detail": "Invalid date format for payment_period. Use YYYY-MM or YYYY-MM-DD.",
                        "success": False
                    })
        
        # Get employee IDs based on filters if not explicitly provided
        if not employee_ids:
            employees = Employee.objects.filter(contracts__status='active', contracts__contract_end_date__gte=payment_period)
            if department_ids:
                employees = employees.filter(hr_details__department_id__in=list(map(lambda x: int(x), department_ids)))
            if region_ids:
                employees = employees.filter(hr_details__region_id__in=list(map(lambda x: int(x), region_ids)))
            if project_ids:
                employees = employees.filter(hr_details__project_id__in=list(map(lambda x: int(x), project_ids)))
            employee_ids = [employee.id for employee in employees]
        
        # Handle empty employee IDs
        if len(employee_ids) == 0:
            return Response({
                "detail": f"No active employee contracts found for the period beginning {payment_period}. Please consider renewing employee contracts!",
                "success": False
            })
        
        # Always use async processing for payroll operations (except queue command)
        if command != "queue":
            # Schedule the batch processing task
            task = batch_process_payslips.delay(
                employee_ids=employee_ids,
                payment_period=payment_period,
                recover_advances=recover_advances,
                command=command,
                user_id=request.user.id
            )
            
            return Response({
                "message": f"Payroll processing for {len(employee_ids)} employees has been queued.",
                "task_id": task.id,
                "status": "processing",
                "success": True
            })
        
        # Otherwise, process synchronously (original logic)
        data = []
        errors = set()
        
        # Optional formula overrides - handle gracefully if not provided
        formula_overrides = request.data.get('formula_overrides') or {}
        
        for empid in employee_ids:
            employee = Employee.objects.filter(id=empid).first()
            if employee is not None:
                try:
                    # Call the PayrollGenerator class
                    payroll_result = PayrollGenerator(
                        request, 
                        employee, 
                        payment_period, 
                        recover_advances, 
                        command, 
                        formula_overrides=formula_overrides
                    ).generate_payroll()
                    
                    # Handle the result
                    if isinstance(payroll_result, Payslip):
                        # If it's a Payslip object, serialize it
                        serializer = PayslipSerializer(payroll_result)
                        data.append(serializer.data)
                        _, created = PayslipAudit.objects.update_or_create(
                            payslip=payroll_result,
                            defaults={
                                'action': 'Created',
                                'action_by': request.user
                            })
                    elif isinstance(payroll_result, dict) and "success" in payroll_result:
                        # If it's a warning, message, or error (as a dict), handle accordingly
                        if not payroll_result.get("success", True):
                            errors.add(payroll_result["detail"])
                        else:
                            # Success case - might be a voucher or other result
                            data.append(payroll_result)
                    else:
                        # Handle unexpected responses (e.g., other message formats)
                        errors.add(f"Unexpected result for employee {employee.id}")
                        
                except Exception as e:
                    # Log the error and continue processing other employees
                    error_msg = f"Error processing employee {employee.id}: {str(e)}"
                    errors.add(error_msg)
                    print(error_msg)
                    continue

        # Return the results, including errors if there are any
        if errors:
            return Response({
                "detail": "Some errors occurred during payroll processing.", 
                "errors": list(set(errors)), 
                "success": False, 
                "data": data
            })
        return Response({"data": data, "success": True})
    
    def destroy(self, request,pk=None):
        try:
            # Retrieve the payslip ID from the request data
            if not pk:
                return Response({"detail": "Payslip ID is required.", "success": False}, status=400)
            # Retrieve the payslip object
            payslip = Payslip.objects.get(id=pk)
            # Update the delete status
            payslip.delete_status = True
            payslip.save()
            # Success response
            message = f"Payslip for {payslip.employee.user.first_name} for the period {payslip.period_end} deleted successfully!"
            return Response({"data": {"message": message}, "success": True})

        except Payslip.DoesNotExist:
            return Response({"detail": "Payslip not found.", "success": False}, status=404)
        
        except Exception as e:
            return Response(
                {
                    "detail": "Some errors occurred during payslip deletion.",
                    "errors": str(e),
                    "success": False,
                    "data": {}
                },
                status=500
            )

class PayrollAuditsViewSet(viewsets.ViewSet):
    queryset = PayslipAudit.objects.all()
    serializer_class = PayslipAuditSerializer
    permission_classes=[IsAuthenticated]

    def list(self, request):
        fromdate = request.query_params.get("fromdate", None)
        todate = request.query_params.get("todate", None)
        payslipid = request.query_params.get("payslipid", 0)

        # Apply filters dynamically
        audits = PayslipAudit.objects.filter(payslip__id=payslipid).order_by('action_date')
    
         # Validate payment period types and filter by payroll date
        if fromdate and todate:
            try:
                # Strip the time part from the date strings
                fromdate = datetime.strptime(fromdate[:10], "%Y-%m-%d").date()
                todate = datetime.strptime(todate[:10], "%Y-%m-%d").date()
                audits = audits.filter(action_date__range=[fromdate, todate])
            except ValueError as e:
                return Response({"detail": str(e) + ". Invalid date format for payroll date range. Use YYYY-MM-DD.", "success": False})
        serializer=PayslipAuditSerializer(audits,many=True)
        return Response(serializer.data,status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def generate_casual_voucher(self, request):
        """
        Generate payment voucher for casual employees based on attendance and daily rates.
        """
        try:
            employee_id = request.data.get('employee_id')
            payment_period = request.data.get('payment_period')
            
            if not employee_id or not payment_period:
                return Response({
                    'success': False,
                    'detail': 'Employee ID and payment period are required'
                }, status=400)
            
            # Parse payment period
            try:
                if isinstance(payment_period, str):
                    payment_period = datetime.strptime(payment_period, '%Y-%m-%d').date()
                elif isinstance(payment_period, str) and len(payment_period) == 7:
                    payment_period = datetime.strptime(payment_period + '-01', '%Y-%m-%d').date()
            except ValueError:
                return Response({
                    'success': False,
                    'detail': 'Invalid payment period format. Use YYYY-MM-DD or YYYY-MM'
                }, status=400)
            
            # Get employee
            try:
                employee = Employee.objects.get(id=employee_id)
            except Employee.DoesNotExist:
                return Response({
                    'success': False,
                    'detail': 'Employee not found'
                }, status=404)
            
            # Queue casual voucher generation as background task
            task = process_single_payslip.delay(
                employee_id=employee_id,
                payment_period=payment_period,
                recover_advances=False,
                command='casual',
                user_id=request.user.id
            )
            
            return Response({
                "message": f"Casual voucher generation for employee {employee_id} has been queued.",
                "task_id": task.id,
                "status": "processing",
                "success": True
            })
                
        except Exception as e:
            return Response({
                'success': False,
                'detail': f'Error generating casual voucher: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['post'])
    def rerun_payslip(self, request):
        """
        Rerun a specific payslip calculation asynchronously.
        """
        try:
            payslip_id = request.data.get('payslip_id')
            if not payslip_id:
                return Response({
                    'success': False,
                    'detail': 'payslip_id is required'
                }, status=400)
            
            # Queue payslip rerun as background task
            task = rerun_payslip.delay(
                payslip_id=payslip_id,
                user_id=request.user.id
            )
            
            return Response({
                "message": f"Payslip rerun for ID {payslip_id} has been queued.",
                "task_id": task.id,
                "status": "processing",
                "success": True
            })
                
        except Exception as e:
            return Response({
                'success': False,
                'detail': f'Error queuing payslip rerun: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['get'])
    def task_status(self, request):
        """
        Check the status of a background task.
        """
        try:
            task_id = request.query_params.get('task_id')
            if not task_id:
                return Response({
                    'success': False,
                    'detail': 'task_id is required'
                }, status=400)
            
            from celery.result import AsyncResult
            
            # Get task result
            task_result = AsyncResult(task_id)
            
            response_data = {
                'task_id': task_id,
                'status': task_result.status,
                'success': True
            }
            
            if task_result.ready():
                if task_result.successful():
                    response_data['result'] = task_result.result
                    response_data['message'] = 'Task completed successfully'
                else:
                    response_data['error'] = str(task_result.result)
                    response_data['message'] = 'Task failed'
            else:
                response_data['message'] = 'Task is still processing'
            
            return Response(response_data)
                
        except Exception as e:
            return Response({
                'success': False,
                'detail': f'Error checking task status: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['post'])
    def generate_consultant_voucher(self, request):
        """
        Generate payment voucher for consultants based on monthly salary and benefits.
        """
        try:
            employee_id = request.data.get('employee_id')
            payment_period = request.data.get('payment_period')
            
            if not employee_id or not payment_period:
                return Response({
                    'success': False,
                    'detail': 'Employee ID and payment period are required'
                }, status=400)
            
            # Parse payment period
            try:
                if isinstance(payment_period, str):
                    payment_period = datetime.strptime(payment_period, '%Y-%m-%d').date()
                elif isinstance(payment_period, str) and len(payment_period) == 7:
                    payment_period = datetime.strptime(payment_period + '-01', '%Y-%m-%d').date()
            except ValueError:
                return Response({
                    'success': False,
                    'detail': 'Invalid payment period format. Use YYYY-MM-DD or YYYY-MM'
                }, status=400)
            
            # Get employee
            try:
                employee = Employee.objects.get(id=employee_id)
            except Employee.DoesNotExist:
                return Response({
                    'success': False,
                    'detail': 'Employee not found'
                }, status=404)
            
            # Queue consultant voucher generation as background task
            task = process_single_payslip.delay(
                employee_id=employee_id,
                payment_period=payment_period,
                recover_advances=False,
                command='consultant',
                user_id=request.user.id
            )
            
            return Response({
                "message": f"Consultant voucher generation for employee {employee_id} has been queued.",
                "task_id": task.id,
                "status": "processing",
                "success": True
            })
                
        except Exception as e:
            return Response({
                'success': False,
                'detail': f'Error generating consultant voucher: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['post'])
    def process_with_formulas(self, request):
        """
        Process payroll with specific formula overrides for enhanced flexibility.
        """
        try:
            employee_ids = request.data.get('employee_ids', [])
            payment_period = request.data.get('payment_period')
            formula_overrides = request.data.get('formula_overrides', {})
            recover_advances = request.data.get('recover_advances', False)
            
            if not employee_ids or not payment_period:
                return Response({
                    'success': False,
                    'detail': 'Employee IDs and payment period are required'
                }, status=400)
            
            # Parse payment period
            try:
                if isinstance(payment_period, str):
                    payment_period = datetime.strptime(payment_period, '%Y-%m-%d').date()
                elif isinstance(payment_period, str) and len(payment_period) == 7:
                    payment_period = datetime.strptime(payment_period + '-01', '%Y-%m-%d').date()
            except ValueError:
                return Response({
                    'success': False,
                    'detail': 'Invalid payment period format. Use YYYY-MM-DD or YYYY-MM'
                }, status=400)
            
            # Validate formula overrides
            from hrm.payroll_settings.models import Formulas
            validated_overrides = {}
            
            for formula_type, formula_id in formula_overrides.items():
                if formula_id:
                    try:
                        formula = Formulas.objects.get(
                            id=formula_id,
                            is_active=True
                        )
                        validated_overrides[formula_type] = formula_id
                    except Formulas.DoesNotExist:
                        return Response({
                            'success': False,
                            'detail': f'Invalid {formula_type} formula ID: {formula_id}'
                        }, status=400)
            
            # Process payroll for each employee
            results = []
            for employee_id in employee_ids:
                try:
                    employee = Employee.objects.get(id=employee_id)
                    
                    payroll_generator = PayrollGenerator(
                        request=request,
                        employee=employee,
                        payment_period=payment_period,
                        recover_advances=recover_advances,
                        command='regular',
                        formula_overrides=validated_overrides
                    )
                    
                    # Generate payroll
                    payroll_result = payroll_generator.generate_payroll()
                    
                    if payroll_result.get('success'):
                        results.append({
                            'employee_id': employee_id,
                            'employee_name': f"{employee.user.first_name} {employee.user.last_name}",
                            'status': 'success',
                            'payslip_id': payroll_result.get('payslip_id'),
                            'details': payroll_result
                        })
                    else:
                        results.append({
                            'employee_id': employee_id,
                            'employee_name': f"{employee.user.first_name} {employee.user.last_name}",
                            'status': 'failed',
                            'error': payroll_result.get('detail', 'Unknown error')
                        })
                        
                except Employee.DoesNotExist:
                    results.append({
                        'employee_id': employee_id,
                        'status': 'failed',
                        'error': 'Employee not found'
                    })
                except Exception as e:
                    results.append({
                        'employee_id': employee_id,
                        'status': 'failed',
                        'error': str(e)
                    })
            
            # Return comprehensive results
            success_count = sum(1 for r in results if r['status'] == 'success')
            failed_count = len(results) - success_count
            
            return Response({
                'success': True,
                'detail': f'Payroll processing completed. {success_count} successful, {failed_count} failed.',
                'results': results,
                'summary': {
                    'total_employees': len(employee_ids),
                    'successful': success_count,
                    'failed': failed_count,
                    'formula_overrides_used': bool(validated_overrides)
                }
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'detail': f'Error processing payroll: {str(e)}'
            }, status=500)

    @action(detail=False, methods=['post'])
    def calculation_preview(self, request):
        """
        Provide a preview of payroll calculations without generating actual payslips.
        """
        try:
            employee_id = request.data.get('employee_id')
            payment_period = request.data.get('payment_period')
            formula_overrides = request.data.get('formula_overrides', {})
            
            if not employee_id or not payment_period:
                return Response({
                    'success': False,
                    'detail': 'Employee ID and payment period are required'
                }, status=400)
            
            # Parse payment period
            try:
                if isinstance(payment_period, str):
                    payment_period = datetime.strptime(payment_period, '%Y-%m-%d').date()
                elif isinstance(payment_period, str) and len(payment_period) == 7:
                    payment_period = datetime.strptime(payment_period + '-01', '%Y-%m-%d').date()
            except ValueError:
                return Response({
                    'success': False,
                    'detail': 'Invalid payment period format. Use YYYY-MM-DD or YYYY-MM'
                }, status=400)
            
            # Get employee
            try:
                employee = Employee.objects.get(id=employee_id)
            except Employee.DoesNotExist:
                return Response({
                    'success': False,
                    'detail': 'Employee not found'
                }, status=404)
            
            # Generate calculation preview
            payroll_generator = PayrollGenerator(
                request=request,
                employee=employee,
                payment_period=payment_period,
                recover_advances=False,
                command='preview',
                formula_overrides=formula_overrides
            )
            
            # Get calculation breakdown
            preview_data = {
                'employee': {
                    'id': employee.id,
                    'name': f"{employee.user.first_name} {employee.user.last_name}",
                    'staff_no': getattr(employee.hr_details.first(), 'job_or_staff_number', 'N/A'),
                    'basic_salary': getattr(employee.salary_details.first(), 'basic_salary', 0)
                },
                'payment_period': payment_period.strftime('%B %Y'),
                'formula_overrides': formula_overrides,
                'calculations': {
                    'gross_pay': payroll_generator.calculate_gross_pay(),
                    'taxable_income': payroll_generator.calculate_taxable_income(),
                    'income_tax': payroll_generator.calculate_income_tax(),
                    'nssf': payroll_generator.calculate_nssf(),
                    'nhif': payroll_generator.calculate_nhif(),
                    'net_pay': payroll_generator.calculate_net_pay()
                },
                'components': {
                    'earnings': payroll_generator.get_earnings_breakdown(),
                    'deductions': payroll_generator.get_deductions_breakdown(),
                    'benefits': payroll_generator.get_benefits_breakdown()
                }
            }
            
            return Response({
                'success': True,
                'detail': 'Calculation preview generated successfully',
                'data': preview_data
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'detail': f'Error generating calculation preview: {str(e)}'
            }, status=500)

class EmailPayslipsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        try:
            # Extract form data
            emails = request.POST.getlist('emails')
            names = request.POST.getlist('names')
            periods = request.POST.getlist('period')
            files = request.FILES.getlist('files')
            process_async = request.data.get("async", True)  # New parameter for async processing

            if not emails or not files:
                return JsonResponse({'error': 'Emails and files are required'}, status=400)

            if process_async:
                # Prepare email data for async processing
                email_data_list = []
                
                for idx, email in enumerate(emails):
                    # Validate and match file with email
                    file = files[idx] if idx < len(files) else None
                    
                    if file:
                        # Prepare template context
                        context = {
                            "name": names[idx] if idx < len(names) else "Employee",
                            "period": periods[idx] if idx < len(periods) else "Current Period",
                            "company_name": "Bengo ERP",
                            "footer_text": "This is an automated email. Please do not reply."
                        }
                        
                        # Queue the email task
                        email_data_list.append({
                            "subject": f"Payslip - ID {names[idx] if idx < len(names) else 'N/A'}",
                            "body": f"Dear {names[idx]},\n\nPlease find attached your payslip for the period of {periods[idx]}.\n\nRegards,\nProcurePro Team",
                            "recipients": [email],
                            "attachments": [file]
                        })
                
                # Send emails asynchronously
                result = send_bulk_emails.delay(email_data_list)
                
                return JsonResponse({
                    'message': f'Payslips queued for sending to {len(emails)} recipients',
                    'task_id': result.id,
                    'status': 'processing'
                }, status=202)  # 202 Accepted
            
            else:
                # Original synchronous implementation
                for idx, email in enumerate(emails):
                    file = files[idx] if idx < len(files) else None
                    
                    if file:
                        attachments = [file]
                        subject = f"Payslip - ID {names[idx] if idx < len(names) else 'N/A'}"
                        body = f"Dear {names[idx]},\n\nPlease find attached your payslip for the period of {periods[idx]}.\n\nRegards,\nProcurePro Team"
                        
                        email_service = EmailService()
                        email_service.send_email(
                            subject=subject,
                            message=body,
                            recipient_list=[email],
                            attachments=attachments,
                            async_send=True
                        )
                    else:
                        print(f"File missing for email: {email}")
                
                return JsonResponse({'message': 'Payslips emailed successfully'}, status=200)

        except Exception as e:
            print(f"Error: {e}")
            return JsonResponse({'error': f'Failed to email payslips: {str(e)}'}, status=500)

class EmployeeAdvancesViewSet(viewsets.ModelViewSet):
    queryset = Advances.objects.all()
    serializer_class = EmployeeAdvancesSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Advances.objects.all()
        employee_id = self.request.query_params.get('employee', None)
        department_id = self.request.query_params.get('department', None)
        region_id = self.request.query_params.get('region', None)
        from_date = self.request.query_params.get('from_date', None)
        to_date = self.request.query_params.get('to_date', None)

        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        if department_id:
            queryset = queryset.filter(employee__hr_details__department_id=department_id)
        if region_id:
            queryset = queryset.filter(employee__hr_details__region_id=region_id)
        if from_date and to_date:
            queryset = queryset.filter(issue_date__range=[from_date, to_date])

        return queryset

    def parse_date(self, date_str):
        """Convert ISO format date string to YYYY-MM-DD format"""
        if date_str:
            try:
                # Parse ISO format and return date portion
                return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date().isoformat()
            except (ValueError, AttributeError):
                # If parsing fails, return the original string
                return date_str
        return date_str

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                # Convert dates and get employee
                request.data['issue_date'] = self.parse_date(request.data.get('issue_date'))
                request.data['next_payment_date'] = self.parse_date(request.data.get('next_payment_date'))
                request.data['employee'] = Employee.objects.get(pk=request.data.get('employee'))
                #request.data['approver'] = request.user.id
                
                # Extract repay_option data
                repay_option_data = request.data.pop('repay_option')
                
                # Get the first matching RepayOption or create a new one
                repay_options = RepayOption.objects.filter(amount=repay_option_data['amount'],no_of_installments=repay_option_data['no_of_installments'],installment_amount=repay_option_data['installment_amount'])
                if repay_options.exists():
                    repay_option = repay_options.first()
                else:
                    repay_option = RepayOption.objects.create(**repay_option_data)
        

                # Create Advance with the repay_option
                advance = Advances.objects.create(
                    **request.data,
                    repay_option=repay_option
                )
                serializer = self.get_serializer(advance)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        
        try:
            with transaction.atomic():
                # Convert dates if provided
                if 'issue_date' in request.data:
                    request.data['issue_date'] = self.parse_date(request.data['issue_date'])
                if 'next_payment_date' in request.data:
                    request.data['next_payment_date'] = self.parse_date(request.data['next_payment_date'])
                
                # Handle employee if provided
                if 'employee' in request.data:
                    request.data['employee'] = Employee.objects.get(pk=request.data.get('employee'))
                
                # Set approver
                #request.data['approver'] = request.user.id
                
                # Handle repay_option if provided
                if 'repay_option' in request.data:
                    repay_option_data = request.data.pop('repay_option')
                    
                    # Get the first matching RepayOption or create a new one
                    repay_options = RepayOption.objects.filter(amount=repay_option_data['amount'],no_of_installments=repay_option_data['no_of_installments'],installment_amount=repay_option_data['installment_amount'])
                    if repay_options.exists():
                        repay_option = repay_options.first()
                    else:
                        repay_option = RepayOption.objects.create(**repay_option_data)
                    instance.repay_option = repay_option
                
                # Update other fields
                for field, value in request.data.items():
                    setattr(instance, field, value)
                instance.save()
                
                serializer = self.get_serializer(instance)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

class EmployeeLossDamagesViewSet(viewsets.ModelViewSet): 
    queryset = LossesAndDamages.objects.all() 
    serializer_class = EmployeeLossDamagesSerializer  
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = LossesAndDamages.objects.all()
        employee_id = self.request.query_params.get('employee', None)
        department_id = self.request.query_params.get('department', None)
        region_id = self.request.query_params.get('region', None)
        from_date = self.request.query_params.get('from_date', None)
        to_date = self.request.query_params.get('to_date', None)

        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        if department_id:
            queryset = queryset.filter(employee__hr_details__department_id=department_id)
        if region_id:
            queryset = queryset.filter(employee__hr_details__region_id=region_id)
        if from_date and to_date:
            queryset = queryset.filter(issue_date__range=[from_date, to_date])

        return queryset

    def parse_date(self, date_str):
        """Convert ISO format date string to YYYY-MM-DD format"""
        if date_str:
            try:
                # Parse ISO format and return date portion
                return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date().isoformat()
            except (ValueError, AttributeError):
                # If parsing fails, return the original string
                return date_str
        return date_str

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                # Convert dates and get employee
                request.data['issue_date'] = self.parse_date(request.data.get('issue_date'))
                request.data['next_payment_date'] = self.parse_date(request.data.get('next_payment_date'))
                request.data['employee'] = Employee.objects.get(pk=request.data.get('employee'))
                #request.data['approver'] = request.user.id
                
                # Extract repay_option data
                repay_option_data = request.data.pop('repay_option')
                
                # Get the first matching RepayOption or create a new one
                repay_options = RepayOption.objects.filter(amount=repay_option_data['amount'],no_of_installments=repay_option_data['no_of_installments'],installment_amount=repay_option_data['installment_amount'])
                if repay_options.exists():
                    repay_option = repay_options.first()
                else:
                    repay_option = RepayOption.objects.create(**repay_option_data)
        

                # Create Advance with the repay_option
                advance = LossesAndDamages.objects.create(
                    **request.data,
                    repay_option=repay_option
                )
                serializer = self.get_serializer(advance)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        
        try:
            with transaction.atomic():
                # Convert dates if provided
                if 'issue_date' in request.data:
                    request.data['issue_date'] = self.parse_date(request.data['issue_date'])
                if 'next_payment_date' in request.data:
                    request.data['next_payment_date'] = self.parse_date(request.data['next_payment_date'])
                
                # Handle employee if provided
                if 'employee' in request.data:
                    request.data['employee'] = Employee.objects.get(pk=request.data.get('employee'))
                
                # Set approver
                #request.data['approver'] = request.user.id
                
                # Handle repay_option if provided
                if 'repay_option' in request.data:
                    repay_option_data = request.data.pop('repay_option')
                    
                    # Get the first matching RepayOption or create a new one
                    repay_options = RepayOption.objects.filter(amount=repay_option_data['amount'],no_of_installments=repay_option_data['no_of_installments'],installment_amount=repay_option_data['installment_amount'])
                    if repay_options.exists():
                        repay_option = repay_options.first()
                    else:
                        repay_option = RepayOption.objects.create(**repay_option_data)
                    instance.repay_option = repay_option
                
                # Update other fields
                for field, value in request.data.items():
                    setattr(instance, field, value)
                instance.save()
                
                serializer = self.get_serializer(instance)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['patch'], url_path='bulk-update')
    def bulk_update(self, request):
        ids = request.data.get('ids', [])
        action_type = request.data.get('action', None)
        update_fields = request.data.get('update_fields', {})
        if not ids or not action_type:
            return Response({'error': 'ids and action are required.'}, status=status.HTTP_400_BAD_REQUEST)
        qs = LossesAndDamages.objects.filter(id__in=ids)
        count = 0
        if action_type == 'pause':
            count = qs.update(is_active=False)
        elif action_type == 'restart':
            count = qs.update(is_active=True)
        elif action_type == 'reschedule':
            # update_fields should contain the fields to update, e.g., next_payment_date
            for obj in qs:
                for field, value in update_fields.items():
                    setattr(obj, field, value)
                obj.save()
            count = qs.count()
        elif action_type == 'delete':
            count = qs.delete()[0]
        else:
            return Response({'error': 'Invalid action.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'message': f'{action_type.capitalize()}d {count} records.'}, status=status.HTTP_200_OK)

class ClaimItemViewSet(viewsets.ModelViewSet):
    queryset = ClaimItems.objects.all()
    serializer_class = ClaimItemSerializer

class ExpenseClaimViewSet(viewsets.ModelViewSet):
    queryset = ExpenseClaims.objects.filter(delete_status=False)
    serializer_class = ExpenseClaimSerializer

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        # Serialize the queryset without pagination
        serializer = self.get_serializer(self.queryset, many=True)
        return Response(serializer.data)


    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            try:
                # Extract claim data from the request
                claim_data = json.loads(request.data.get('claim'))
                print(claim_data)
                claim_items_data = json.loads(request.data.get('claim_items'))
                attachment = request.FILES.get('attachment')  # Handle files
                
                # Create the ExpenseClaim instance  
                #claim_data['attachment']=attachment
                employee=Employee.objects.get(pk=claim_data['employee'])  
                claim_data.pop('employee')
                if employee:
                    claim = ExpenseClaims.objects.get_or_create(employee=employee,defaults=claim_data)[0]
                    #get approver
                    payslip_content_type=ContentType.objects.get_for_model(claim)
                    approval=Approval.objects.get(content_type=payslip_content_type)
                    claim.approver=approval.user if approval else None
                    claim.save()

                    # Handle claim items
                    if claim_items_data:
                        for item_data in claim_items_data:
                            item_data['claim'] = claim.id  # Link item to the claim
                            item_serializer = ClaimItemSerializer(data=item_data)
                            if item_serializer.is_valid():
                                item_serializer.save()
                            else:
                                return Response(item_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                    
                    # Handle file attachments
                    if attachment:
                        # Handle the file, e.g., by saving it in the `ExpenseClaims` instance
                        claim.attachment = attachment  # This assumes a single attachment, adapt if needed
                        claim.save()
                return Response({"message":"Claim created successfully!"}, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({"message":e}, status=status.HTTP_400_BAD_REQUEST)
    
    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            with transaction.atomic():
                # Update the ExpenseClaim object
                claim_data=dict(json.loads(request.data.get('claim', None)))
                attachment = request.FILES.get('attachment') 
                claim_data.pop('attachment')
                serializer = self.get_serializer(instance, data=claim_data)
                serializer.is_valid(raise_exception=True)
                claim = serializer.save()

                 # Handle file attachments
                if attachment:
                    # Handle the file, e.g., by saving it in the `ExpenseClaims` instance
                    claim.attachment = attachment  # This assumes a single attachment, adapt if needed
                    claim.save()

                # Update claim items if provided
                claim_items_data = json.loads(request.data.get('claim_items', []))
                for item_data in claim_items_data:
                    item_id = item_data.get('id')
                    if item_id:  # Update existing item
                        item_instance = ClaimItems.objects.get(id=item_id, claim=claim)
                        item_serializer = ClaimItemSerializer(item_instance, data=item_data)
                        item_serializer.is_valid(raise_exception=True)
                        item_serializer.save()
                    else:  # Create new item
                        item_data['claim'] = claim.id
                        item_serializer = ClaimItemSerializer(data=item_data)
                        item_serializer.is_valid(raise_exception=True)
                        item_serializer.save()

                return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            with transaction.atomic():
                # Partial update the ExpenseClaim object
                serializer = self.get_serializer(instance, data=request.data, partial=True)
                serializer.is_valid(raise_exception=True)
                claim = serializer.save()

                return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['patch'], url_path='bulk-update')
    def bulk_update(self, request, *args, **kwargs):
        """
        Bulk patch update for a list of ExpenseClaims based on their IDs.
        """
        try:
            data = request.data
            claim_ids = data.get('claim_ids', [])
            update_fields = data.get('update_fields', {})

            if not claim_ids or not update_fields:
                return Response(
                    {"error": "Both 'claim_ids' and 'update_fields' are required."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Ensure the IDs and fields are valid
            claims_to_update = ExpenseClaims.objects.filter(id__in=claim_ids)

            if not claims_to_update.exists():
                return Response(
                    {"error": "No matching claims found for the given IDs."},
                    status=status.HTTP_404_NOT_FOUND
                )

            with transaction.atomic():
                # Perform updates for each claim
                for claim in claims_to_update:
                    for field, value in update_fields.items():
                        if hasattr(claim, field):
                            setattr(claim, field, value)
                        else:
                            return Response(
                                {"error": f"Field '{field}' does not exist in ExpenseClaims model."},
                                status=status.HTTP_400_BAD_REQUEST
                            )
                    claim.save()

            return Response(
                {"message": f"Successfully updated {len(claims_to_update)} claims."},
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            instance.delete_status = True  
            instance.is_active = False  
            instance.save()
            return Response({"message": "Expense claim marked as inactive."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def payroll_analytics(request):
    """
    Get payroll analytics data.
    """
    try:
        period = request.query_params.get('period', 'month')
        business_id = request.query_params.get('business_id')
        
        analytics_service = PayrollAnalyticsService()
        data = analytics_service.get_payroll_dashboard_data(
            business_id=business_id,
            period=period
        )
        
        return Response({
            'success': True,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error fetching payroll analytics: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }, status=500)


class PayrollApprovalViewSet(viewsets.ViewSet):
    """
    Payroll Approval ViewSet - Handles payroll approval workflows
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.approval_service = PayrollApprovalService()
    
    @action(detail=False, methods=['get'])
    def pending_approvals(self, request):
        """
        Get pending approvals for the current user
        """
        try:
            pending_approvals = self.approval_service.get_pending_approvals(request.user)
            
            approvals_data = []
            for approval in pending_approvals:
                approvals_data.append({
                    'id': approval.id,
                    'title': approval.content_object.__str__() if approval.content_object else 'Unknown',
                    'amount': approval.approval_amount,
                    'step_name': approval.step.name,
                    'requested_at': approval.requested_at,
                    'workflow_name': approval.workflow.name,
                    'content_type': approval.content_type.model,
                    'object_id': approval.object_id
                })
            
            return Response({
                'success': True,
                'data': approvals_data,
                'count': len(approvals_data)
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Error fetching pending approvals: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """
        Approve a payroll item
        """
        try:
            approval_id = int(pk)
            notes = request.data.get('notes', '')
            comments = request.data.get('comments', '')
            
            result = self.approval_service.approve_payroll_item(
                approval_id=approval_id,
                user=request.user,
                notes=notes,
                comments=comments
            )
            
            if result['success']:
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except ValueError:
            return Response({
                'success': False,
                'error': 'Invalid approval ID'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Error approving payroll item: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """
        Reject a payroll item
        """
        try:
            approval_id = int(pk)
            notes = request.data.get('notes', '')
            comments = request.data.get('comments', '')
            
            result = self.approval_service.reject_payroll_item(
                approval_id=approval_id,
                user=request.user,
                notes=notes,
                comments=comments
            )
            
            if result['success']:
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
                
        except ValueError:
            return Response({
                'success': False,
                'error': 'Invalid approval ID'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Error rejecting payroll item: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['get'])
    def approval_summary(self, request, pk=None):
        """
        Get approval summary for a payroll object
        """
        try:
            # Get the payroll object (payslip, casual voucher, etc.)
            payroll_object = self._get_payroll_object(pk)
            
            if not payroll_object:
                return Response({
                    'success': False,
                    'error': 'Payroll object not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            result = self.approval_service.get_approval_summary(payroll_object)
            
            if result['success']:
                return Response(result, status=status.HTTP_200_OK)
            else:
                return Response(result, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            return Response({
                'success': False,
                'error': f'Error getting approval summary: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_payroll_object(self, object_id):
        """
        Get payroll object by ID
        """
        try:
            # Try to get payslip first
            from .models import Payslip
            return Payslip.objects.get(id=object_id)
        except Payslip.DoesNotExist:
            # Add other payroll object types here when they exist
            # from .models import CasualVoucher, ConsultantVoucher
            # try:
            #     return CasualVoucher.objects.get(id=object_id)
            # except CasualVoucher.DoesNotExist:
            #     try:
            #         return ConsultantVoucher.objects.get(id=object_id)
            #     except ConsultantVoucher.DoesNotExist:
            #         return None
            return None
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, filters
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend

from crm.contacts.utils import ImportContacts
from ecommerce.product.functions import ImportProducts
from .serializers import *
from hrm.payroll_settings.serializers import *
from hrm.payroll_settings.models import *
from hrm.payroll.serializers import *
from hrm.payroll.models import *
from hrm.employees.models import *
from .services.ess_utils import create_ess_account, reset_ess_password, deactivate_ess_account
from rest_framework.renderers import *
from rest_framework.response import Response
from rest_framework.permissions import *
from rest_framework.views import APIView
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from .utils import EmployeeDataImport
from rest_framework import viewsets, status
from rest_framework.decorators import action
from datetime import datetime, timedelta
from rest_framework.authentication import BaseAuthentication,TokenAuthentication,SessionAuthentication
from django.db.models import F,Q,Prefetch
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import api_view
from .analytics.employee_analytics import EmployeeAnalyticsService
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)

class EmployeeBankAccountViewSet(viewsets.ModelViewSet):
    queryset = EmployeeBankAccount.objects.all()
    serializer_class = EmployeeBankAccountSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PageNumberPagination

    def list(self, request, *args, **kwargs):
        emp_id = request.query_params.get('emp_id')
        qs = self.get_queryset()
        if emp_id:
            qs = qs.filter(employee__id=emp_id)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        """Ensure only one primary account per employee."""
        instance = serializer.save()
        if instance.is_primary:
            EmployeeBankAccount.objects.filter(employee=instance.employee).exclude(pk=instance.pk).update(is_primary=False)

    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.is_primary:
            EmployeeBankAccount.objects.filter(employee=instance.employee).exclude(pk=instance.pk).update(is_primary=False)


class UploadEmployData(APIView):
    permission_classes=[IsAuthenticated]

    @csrf_exempt
    def post(self, request, format=None):
        file_name = None
        try:
            organisation=Bussiness.objects.filter(Q(owner=self.request.user)|Q(employees__user=self.request.user)).first()
            if organisation is None:
                return Response({'error': "No Company or Business Details found. Please register company details before importing employees"}, status=status.HTTP_400_BAD_REQUEST)
            if 'file' not in request.FILES:
                return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)
            
            file_obj = request.FILES['file']
            fileType = request.data.get('fileType')
            
            # Save the uploaded file temporarily
            file_name = default_storage.save(file_obj.name, ContentFile(file_obj.read()))
            path = default_storage.path(file_name)
            
            # Process the file based on fileType
            if fileType == 'products':
                import_response = ImportProducts(request, path, organisation).save_product()
            elif fileType == 'contacts':
                import_response = ImportContacts(request, path, organisation).save_contact()
            else:
                # Default to employee import
                import_response = EmployeeDataImport(request=request, path=path, organisation=organisation).import_employee_data()
            
            return Response({'message': import_response}, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        finally:
            # Always clean up the uploaded file after processing (success or failure)
            if file_name:
                try:
                    if default_storage.exists(file_name):
                        default_storage.delete(file_name)
                        print(f"✓ Cleaned up uploaded file: {file_name}")
                except Exception as cleanup_error:
                    print(f"Warning: Failed to delete uploaded file {file_name}: {cleanup_error}")

class EmployeeViewSet(BaseModelViewSet):#cruds
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    #serializer_class = PersonalDataSerializer
    permission_classes=[IsAuthenticated]
    pagination_class = PageNumberPagination  # Enable pagination

    def update(self, request, *args, **kwargs):
        """
        Treat PUT as partial update to avoid forcing non-critical fields.
        Also normalize date_of_birth if provided as ISO datetime.
        """
        # Normalize date_of_birth to YYYY-MM-DD if provided as datetime string
        data = request.data
        try:
            # request.data may be immutable (e.g., QueryDict). Copy if possible.
            data = data.copy() if hasattr(data, 'copy') else dict(data)
        except Exception:
            data = request.data
        dob = data.get('date_of_birth')
        if isinstance(dob, str) and 'T' in dob:
            # Best-effort normalization: keep the date portion
            try:
                # Attempt common formats then fallback to slicing
                for fmt in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
                    try:
                        parsed = datetime.strptime(dob, fmt).date()
                        data['date_of_birth'] = parsed.isoformat()
                        break
                    except ValueError:
                        continue
                else:
                    data['date_of_birth'] = dob[:10]
            except Exception:
                # If parsing fails, let serializer handle it with expanded formats
                pass

        # Force partial updates to relax required fields
        kwargs['partial'] = True
        # Reuse BaseModelViewSet update flow but pass our normalized data explicitly
        try:
            correlation_id = self.get_correlation_id()
            instance = self.get_object()
            old_data = self.get_serializer(instance).data
            serializer = self.get_serializer(instance, data=data, partial=True)
            if not serializer.is_valid():
                return APIResponse.validation_error(
                    message='Validation failed',
                    errors=serializer.errors,
                    correlation_id=correlation_id
                )
            updated_instance = serializer.save()
            new_data = self.get_serializer(updated_instance).data
            changes = {key: {'old': old_data.get(key), 'new': new_data.get(key)}
                       for key in new_data if old_data.get(key) != new_data.get(key)}
            self.log_operation(
                operation=AuditTrail.UPDATE,
                obj=updated_instance,
                changes=changes,
                reason=f'Updated {self.get_entity_type()}'
            )
            return APIResponse.success(
                data=new_data,
                message=f'{self.get_entity_type()} updated successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            # Defer to parent standardized handler on unexpected errors
            return super().update(request, *args, **kwargs)

    def get_object(self):
        """
        Override get_object to allow retrieving:
        - Any employee when superuser
        - The current user's own employee record regardless of organisation filters
        - Employees within the same organisation context as the requesting user
        """
        from django.http import Http404
        pk = self.kwargs.get(self.lookup_field or 'pk')
        try:
            obj = Employee.objects.select_related('organisation', 'user').get(pk=pk)
        except Employee.DoesNotExist:
            raise Http404
        user = self.request.user
        if getattr(user, 'is_superuser', False):
            return obj
        # Allow if the employee belongs to the requester
        if obj.user_id == getattr(user, 'id', None):
            return obj
        # Allow if within user's organisation context (owner or same organisation as user's employee)
        org_ids = Bussiness.objects.filter(
            Q(owner=user) | Q(id=getattr(getattr(user, "employee", None), "organisation_id", None))
        ).values_list('id', flat=True)
        if obj.organisation_id in list(org_ids):
            return obj
        # Otherwise, act as not found
        raise Http404

    def get_queryset(self):
        """Filter employees with optimized queries using select_related and prefetch_related."""
        from core.utils import get_branch_id_from_request
        
        queryset = super().get_queryset()
        
        # Optimize queries for related objects
        queryset = queryset.select_related('organisation', 'user')
        queryset = queryset.prefetch_related('hr_details', 'bank_accounts__bank_branch')
        
        # Get branch from X-Branch-ID header
        branch_id = get_branch_id_from_request(self.request)
        if not branch_id:
            # Fallback to query param
            branch_id = self.request.query_params.get('branch_id', None)
        
        employement_type = (
            self.request.query_params.getlist('employment_type', None)
            or self.request.query_params.getlist('employment_type[]', None)
            or self.request.query_params.getlist('employement_type', None)
            or self.request.query_params.getlist('employement_type[]', None)
        )
        contract_start_date = self.request.query_params.get("contract_start_date", None)
        contract_end_date = self.request.query_params.get("contract_end_date", None)
        
        # Support multiple filter parameter formats for departments and regions
        department_ids = (
            self.request.query_params.getlist("department[]", None) or 
            self.request.query_params.getlist("department", None) or
            ([self.request.query_params.get("department")] if self.request.query_params.get("department") else None)
        )
        
        region_ids = (
            self.request.query_params.getlist("region[]", None) or 
            self.request.query_params.getlist("region", None) or
            ([self.request.query_params.get("region")] if self.request.query_params.get("region") else None)
        )
        
        project_ids = (
            self.request.query_params.getlist("project[]", None) or 
            self.request.query_params.getlist("project", None) or
            ([self.request.query_params.get("project")] if self.request.query_params.get("project") else None)
        )
        
        employee_ids = self.request.query_params.getlist("employee_ids[]", None)

        # Apply branch filtering if branch_id is available
        if branch_id:
            # Filter through hr_details which has branch relationship; if no matches yet (e.g., data not linked),
            # skip to avoid hiding all employees.
            branch_qs = queryset.filter(hr_details__branch_id=branch_id)
            if branch_qs.exists():
                queryset = branch_qs
            
        if not self.request.user.is_superuser:
            orgs = Bussiness.objects.filter(
                Q(owner=self.request.user) |
                Q(id=getattr(getattr(self.request.user, "employee", None), "organisation_id", None))
            )
            if orgs.exists():
                queryset = queryset.filter(Q(organisation__in=orgs))
            else:
                # Fallback to business context header if provided
                try:
                    from core.utils import get_business_id_from_request
                    biz_id = get_business_id_from_request(self.request)
                except Exception:
                    biz_id = None
                if biz_id:
                    queryset = queryset.filter(organisation_id=biz_id)
                else:
                    # If there is only one business in the system, default to it
                    try:
                        total_biz = Bussiness.objects.count()
                        if total_biz == 1:
                            queryset = queryset.filter(organisation=Bussiness.objects.first())
                    except Exception:
                        pass
        
        # Apply employment type filtering - this is the key fix
        if employement_type:
            # Ensure we only get employees with the specified employment types
            # This will exclude casual and consultant employees if they're not in the selected types
            queryset = queryset.filter(salary_details__employment_type__in=employement_type)
            print(f"Employee view - Filtering by employment types: {employement_type}")
        else:
            # If no employment types specified, exclude casual and consultant by default
            # as they have different payroll processing flows
            queryset = queryset.exclude(
                salary_details__employment_type__in=['casual', 'consultant']
            )
            print("Employee view - No employment types specified, excluding casual and consultant employees by default")
        
        # Apply department filter
        if department_ids:
            # Filter None values
            department_ids = [d for d in department_ids if d is not None and d != '']
            if department_ids:
                queryset = queryset.filter(hr_details__department_id__in=department_ids)
        
        # Apply region filter
        if region_ids:
            # Filter None values
            region_ids = [r for r in region_ids if r is not None and r != '']
            if region_ids:
                queryset = queryset.filter(hr_details__region_id__in=region_ids)
        
        # Apply project filter
        if project_ids:
            # Filter None values
            project_ids = [p for p in project_ids if p is not None and p != '']
            if project_ids:
                queryset = queryset.filter(hr_details__project_id__in=project_ids)
        
        # Apply employee IDs filter
        if employee_ids:
            queryset = queryset.filter(id__in=employee_ids).order_by('id')

         # Validate payment period types and filter by payroll date
        if contract_start_date and contract_end_date:
            try:
                # Strip the time part from the date strings
                contract_start_date = datetime.strptime(contract_start_date[:10], "%Y-%m-%d").date()
                contract_end_date = datetime.strptime(contract_end_date[:10], "%Y-%m-%d").date()
                queryset = queryset.filter(Q(contracts__contract_start_date__gte=contract_start_date) & Q(contracts__contract_end_date__lte=contract_end_date))
            except ValueError as e:
                # Log the error but don't return Response from get_queryset
                print(f"Date parsing error: {e}")
                # Return empty queryset on date error
                return Employee.objects.none()
        return queryset
    
    def perform_create(self, serializer):
        """Override create to handle ESS account creation"""
        employee = serializer.save()
        
        # If allow_ess is True, create ESS account and send welcome email
        if employee.allow_ess:
            result = create_ess_account(employee)
            if result['success']:
                logger.info(f"ESS account created for employee {employee.id}")
            else:
                logger.warning(f"Failed to create ESS account for employee {employee.id}: {result['message']}")
        
        return employee
    
    def perform_update(self, serializer):
        """Override update to handle ESS activation changes"""
        employee = serializer.save()
        
        # Check if allow_ess was just enabled
        if employee.allow_ess and not employee.ess_activated_at:
            result = create_ess_account(employee)
            if result['success']:
                logger.info(f"ESS account activated for employee {employee.id}")
        
        return employee
    
    @action(detail=True, methods=['post'], url_path='ess/reset-password')
    def reset_ess_password(self, request, pk=None):
        """Reset ESS password for an employee (Admin only)"""
        employee = self.get_object()
        
        if not employee.allow_ess:
            return Response(
                {'error': 'ESS access is not enabled for this employee'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        new_password = request.data.get('new_password')
        result = reset_ess_password(employee, new_password)
        
        if result['success']:
            return Response({
                'message': 'ESS password reset successfully',
                'temporary_password': result['temporary_password']
            })
        else:
            return Response(
                {'error': 'Failed to reset password'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], url_path='ess/activate')
    def activate_ess(self, request, pk=None):
        """Activate ESS access for an employee"""
        employee = self.get_object()
        employee.allow_ess = True
        employee.save()
        
        result = create_ess_account(employee)
        
        if result['success']:
            return Response({
                'message': 'ESS account activated and welcome email sent',
                'email_sent': result['email_sent']
            })
        else:
            return Response(
                {'error': result['message']},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['post'], url_path='ess/deactivate')
    def deactivate_ess(self, request, pk=None):
        """Deactivate ESS access for an employee"""
        employee = self.get_object()
        result = deactivate_ess_account(employee)
        
        if result['success']:
            return Response({'message': result['message']})
        else:
            return Response(
                {'error': 'Failed to deactivate ESS'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            ) 

class EmployeeStatusAPIView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Get today's date and date one month from now
        today = timezone.now().date()
        one_month_from_now = today + timedelta(days=30)

        # Query active employees
        active_employees = Employee.objects.filter(contracts__status='active').distinct().count()
        
        # Query inactive employees
        inactive_employees = Employee.objects.exclude(contracts__status='active').distinct().count()

        # Query employees with contracts expiring in one month
        expiring_contracts = Employee.objects.filter(
            contracts__status="active",
            contracts__contract_end_date__lte=one_month_from_now,
            contracts__contract_end_date__gte=today
        ).distinct().count()

        # Prepare the response data
        response_data = {
            "active_employees": active_employees,
            "inactive_employees":inactive_employees,
            "expiring_contracts":expiring_contracts,
        }
        return Response(response_data, status=status.HTTP_200_OK)

class EmployeeDeductionsViewSet(viewsets.ModelViewSet):#crudf
    queryset = Deductions.objects.all()
    serializer_class = DeductionsSerializer
    permission_classes=[IsAuthenticated]
    #authentication_classes=[BaseAuthentication,TokenAuthentication,SessionAuthentication]
    pagination_class = PageNumberPagination  # Enable pagination
    
    def list(self, request, *args, **kwargs):
        from core.utils import get_branch_id_from_request
        
        # Support multiple filter parameter formats
        department_ids = (
            request.query_params.getlist("department[]", None) or 
            request.query_params.getlist("department", None) or
            ([request.query_params.get("department")] if request.query_params.get("department") else None)
        )
        region_ids = (
            request.query_params.getlist("region[]", None) or 
            request.query_params.getlist("region", None) or
            ([request.query_params.get("region")] if request.query_params.get("region") else None)
        )
        project_ids = (
            request.query_params.getlist("project[]", None) or 
            request.query_params.getlist("project", None) or
            ([request.query_params.get("project")] if request.query_params.get("project") else None)
        )
        deduction_id = request.query_params.get("deduction", None)
        emp_id = request.query_params.get("emp_id", None)
        
        # Get branch from X-Branch-ID header
        branch_id = get_branch_id_from_request(request)

        # Apply filters dynamically
        deductions = self.get_queryset()
        
        if branch_id:
            deductions = deductions.filter(employee__hr_details__branch_id=branch_id)
            
        if emp_id:
            deductions = deductions.filter(employee__id=emp_id)
            
        if department_ids:
            department_ids = [d for d in department_ids if d is not None and d != '']
            if department_ids:
                deductions = deductions.filter(employee__hr_details__department__id__in=department_ids)
                
        if region_ids:
            region_ids = [r for r in region_ids if r is not None and r != '']
            if region_ids:
                deductions = deductions.filter(employee__hr_details__region__id__in=region_ids)
                
        if project_ids:
            project_ids = [p for p in project_ids if p is not None and p != '']
            if project_ids:
                deductions = deductions.filter(employee__hr_details__project__id__in=project_ids)
                
        if deduction_id:
            print(deduction_id)
            deductions = deductions.filter(deduction__id=deduction_id)
        
        # Paginate the queryset
        page = self.paginate_queryset(deductions)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(deductions, many=True)
        # Return the serialized data in the response
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        try:
            deductions_data = request.data  # Expecting a list or single object

            # Ensure data is in list format
            if isinstance(deductions_data, dict):  
                deductions_data = list(deductions_data)

            created_deductions = []

            for data in deductions_data:
                employee_id = data.get("employee")
                deduction_id = data.get("deduction", {}).get("wb_code")  # Assuming wb_code is unique
                fixed_amount = Decimal(data.get("fixed_amount", 0))
                paid_to_date = Decimal(data.get("paid_to_date", 0))
                quantity = Decimal(data.get("quantity", 0))
                amount = Decimal(data.get("amount", 0))
                employer_amount = Decimal(data.get("employer_amount", 0))
                percent_of_basic= Decimal(data.get("percent_of_basic", 0))
                # Ensure required fields are present
                if not employee_id or not deduction_id:
                    return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

                # Fetch Employee & Deduction Instances
                try:
                    employee = Employee.objects.get(id=employee_id)
                    deduction = PayrollComponents.objects.get(wb_code=deduction_id)
                    if percent_of_basic>0:
                        amount=Decimal(employee.salary_details.first().monthly_salary)*Decimal(percent_of_basic/100)
                        data['amount']=amount
                except Employee.DoesNotExist:
                    return Response({"error": "Employee not found"}, status=status.HTTP_404_NOT_FOUND)
                except PayrollComponents.DoesNotExist:
                    return Response({"error": "Deduction component not found"}, status=status.HTTP_404_NOT_FOUND)

                # Check if deduction already exists for employee
                existing_deduction = Deductions.objects.filter(employee=employee, deduction=deduction).first()
                if existing_deduction:
                    self.update_employee_deduction(existing_deduction,data)
                else:
                    # Create Deduction
                    new_deduction = Deductions.objects.create(
                        employee=employee,
                        deduction=deduction,
                        paid_to_date=paid_to_date,
                        quantity=quantity,
                        amount=amount if amount>0 else fixed_amount,
                        employer_amount=employer_amount,
                        is_active=True
                    )
            return Response({'message':'Records updated successfully'}, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update_employee_deduction(self, instance, data):
        serializer = self.get_serializer(instance, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return 'Record updated successfully'
        
    @action(detail=False, methods=['post'], url_path='remove-deduction')
    def remove_employee_deduction(self, request):
        """ Remove an employee's deduction based on deduction_id and employee_id """
        deduction_id = request.data.get('deduction_id')
        employee_id = request.data.get('employee_id')

        if not deduction_id or not employee_id:
            return Response({'error': 'Both deduction_id and employee_id are required'}, status=status.HTTP_400_BAD_REQUEST)

        deduction = get_object_or_404(Deductions, id=deduction_id, employee_id=employee_id)
        deduction.delete()
        return Response({'message': 'Deduction removed successfully'}, status=status.HTTP_204_NO_CONTENT)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()  
        serializer = self.get_serializer(instance, data=request.data, partial=True) 
        serializer.is_valid(raise_exception=True)
        serializer.save() 
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object() 
        instance.delete()  
        return Response(
            {"message": "Deduction deleted successfully."},
            status=status.HTTP_204_NO_CONTENT
        )

class EmployeeEarningsViewSet(viewsets.ModelViewSet):#crudf
    queryset = Earnings.objects.all()
    serializer_class = EarningsSerializer
    permission_classes=[IsAuthenticated]
    #authentication_classes=[BaseAuthentication,TokenAuthentication,SessionAuthentication]
    pagination_class = PageNumberPagination  # Enable pagination

    def list(self, request, *args, **kwargs):
        from core.utils import get_branch_id_from_request
        
        # Support multiple filter parameter formats
        department_ids = (
            request.query_params.getlist("department[]", None) or 
            request.query_params.getlist("department", None) or
            ([request.query_params.get("department")] if request.query_params.get("department") else None)
        )
        region_ids = (
            request.query_params.getlist("region[]", None) or 
            request.query_params.getlist("region", None) or
            ([request.query_params.get("region")] if request.query_params.get("region") else None)
        )
        project_ids = (
            request.query_params.getlist("project[]", None) or 
            request.query_params.getlist("project", None) or
            ([request.query_params.get("project")] if request.query_params.get("project") else None)
        )
        earning_id = request.query_params.get("earning", None)
        emp_id = request.query_params.get("emp_id", None)
        
        # Get branch from X-Branch-ID header
        branch_id = get_branch_id_from_request(request)

        # Apply filters dynamically
        earnings = self.get_queryset()
        
        if branch_id:
            earnings = earnings.filter(employee__hr_details__branch_id=branch_id)
            
        if emp_id:
            earnings = earnings.filter(employee__id=emp_id)
            
        if department_ids:
            department_ids = [d for d in department_ids if d is not None and d != '']
            if department_ids:
                earnings = earnings.filter(employee__hr_details__department__id__in=department_ids)
                
        if region_ids:
            region_ids = [r for r in region_ids if r is not None and r != '']
            if region_ids:
                earnings = earnings.filter(employee__hr_details__region__id__in=region_ids)
                
        if project_ids:
            project_ids = [p for p in project_ids if p is not None and p != '']
            if project_ids:
                earnings = earnings.filter(employee__hr_details__project__id__in=project_ids)
                
        if earning_id:
            print(earning_id)
            earnings = earnings.filter(earning__id=earning_id)
        
        # Paginate the queryset
        page = self.paginate_queryset(earnings)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(earnings, many=True)
        # Return the serialized data in the response
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        try:
            earnings_data = request.data  # Expecting a list or single object

            # Ensure data is in list format
            if isinstance(earnings_data, dict):  
                earnings_data = list(earnings_data)

            created_earnings = []

            for data in earnings_data:
                employee_id = data.get("employee")
                earning_id = data.get("earning", {}).get("wb_code")  # Assuming wb_code is unique
                amount = Decimal(data.get("amount", 0))
                quantity = Decimal(data.get("quantity", 0))
                rate = Decimal(data.get("rate", 0))
                percent_of_basic=Decimal(data.get("percent_of_basic", 0))

                # Ensure required fields are present
                if not employee_id or not earning_id:
                    return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

                # Fetch Employee & Deduction Instances
                try:
                    employee = Employee.objects.get(id=employee_id)
                    earning = PayrollComponents.objects.get(wb_code=earning_id)
                    if percent_of_basic>0:
                        amount=Decimal(employee.salary_details.first().monthly_salary)*Decimal(percent_of_basic/100)
                        data['amount']=amount
                except Employee.DoesNotExist:
                    return Response({"error": "Employee not found"}, status=status.HTTP_404_NOT_FOUND)
                except PayrollComponents.DoesNotExist:
                    return Response({"error": "Earning component not found"}, status=status.HTTP_404_NOT_FOUND)

                # Check if deduction already exists for employee
                existing_earning = Earnings.objects.filter(employee=employee, earning=earning).first()
                if existing_earning:
                    self.update_employee_earning(existing_earning,data)
                else:
                    # Create Deduction
                    new_item = Earnings.objects.create(
                        employee=employee,
                        earning=earning,
                        amount=amount,
                        quantity=quantity,
                        rate=rate,
                        is_active=True
                    )
                    created_earnings.append(new_item)

            return Response({'message':'Records updated successfully!'}, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update_employee_earning(self, instance, data):
        serializer = self.get_serializer(instance, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return 'Record updated successfully'
        
    @action(detail=False, methods=['post'], url_path='remove-earning')
    def remove_employee_earning(self, request):
        earning_id = request.data.get('earning_id')
        employee_id = request.data.get('employee_id')

        if not earning_id or not employee_id:
            return Response({'error': 'Both earning_id and employee_id are required'}, status=status.HTTP_400_BAD_REQUEST)

        earning = get_object_or_404(Earnings, id=earning_id, employee_id=employee_id)
        earning.delete()
        return Response({'message': 'Earning removed successfully'}, status=status.HTTP_204_NO_CONTENT)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()  
        serializer = self.get_serializer(instance, data=request.data, partial=True) 
        serializer.is_valid(raise_exception=True)
        serializer.save() 
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object() 
        instance.delete()  
        return Response(
            {"message": "Earning deleted successfully."},
            status=status.HTTP_204_NO_CONTENT
        )

class EmployeeBenefitsViewSet(viewsets.ModelViewSet):#crudf
    queryset = Benefits.objects.all()
    serializer_class = BenefitsSerializer
    permission_classes=[IsAuthenticated]
    #authentication_classes=[BaseAuthentication,TokenAuthentication,SessionAuthentication]
    pagination_class = PageNumberPagination  # Enable pagination

    def list(self, request, *args, **kwargs):
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        benefit_id = request.query_params.get("earning", None)
        emp_id = request.query_params.get("emp_id", None)

        # Apply filters dynamically
        benefits = self.get_queryset()
        if emp_id:
            benefits = benefits.filter(employee__id=emp_id)
        if department_ids:
            benefits = benefits.filter(employee__hr_details__department__id__in=department_ids)
        if region_ids:
            benefits = benefits.filter(employee__hr_details__region__id__in=region_ids)
        if benefit_id:
            benefits = benefits.filter(benefit__id=benefit_id)

         # Paginate the queryset
        page = self.paginate_queryset(benefits)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    def create(self, request, *args, **kwargs):
        try:
            benefits_data = request.data  # Can be a list or a single object
            
            # Ensure data is a list for uniform processing
            if isinstance(benefits_data, dict):  
                benefits_data = [benefits_data]

            created_benefits = []

            for data in benefits_data:
                employee_id = data.get("employee")
                benefit_id = data.get("benefit", {}).get("wb_code")  # Assuming wb_code is unique
                amount = Decimal(data.get("amount", 0))
                percent_of_basic = Decimal(data.get("percent_of_basic", 0))

                # Ensure required fields are present
                if not employee_id or not benefit_id:
                    return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

                # Fetch Employee & Benefit Instances
                try:
                    employee = Employee.objects.get(id=employee_id)
                    benefit = PayrollComponents.objects.get(wb_code=benefit_id)

                    # Calculate amount based on percent of basic salary
                    if percent_of_basic > 0:
                        salary = Decimal(employee.salary_details.first().monthly_salary)
                        amount = salary * Decimal(percent_of_basic / 100)
                        data['amount']=amount
                except Employee.DoesNotExist:
                    return Response({"error": "Employee not found"}, status=status.HTTP_404_NOT_FOUND)
                except PayrollComponents.DoesNotExist:
                    return Response({"error": "Benefit component not found"}, status=status.HTTP_404_NOT_FOUND)

                # Check if the benefit already exists
                existing_benefit = Benefits.objects.filter(employee=employee, benefit=benefit).first()

                if existing_benefit:
                    # **Update Existing Benefit**
                    self.update_employee_benefit(existing_benefit, data)
                else:
                    new_item = Benefits.objects.create(
                        employee=employee,
                        benefit=benefit,
                        amount=amount,
                        is_active=True
                    )
                    created_benefits.append(new_item)

            return Response({'message':'Records updated successfully!'}, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update_employee_benefit(self, benefit_instance, data):
        serializer = self.get_serializer(benefit_instance, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return 'Record updated successfully'
    
    @action(detail=False, methods=['post'], url_path='remove-benefit')
    def remove_employee_benefit(self, request):
        benefit_id = request.data.get('benefit_id')
        employee_id = request.data.get('employee_id')

        if not benefit_id or not employee_id:
            return Response({'error': 'Both benefit_id and employee_id are required'}, status=status.HTTP_400_BAD_REQUEST)

        benefit = get_object_or_404(Benefits, id=benefit_id, employee_id=employee_id)
        benefit.delete()
        return Response({'message': 'Benefit removed successfully'}, status=status.HTTP_204_NO_CONTENT)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()  
        serializer = self.get_serializer(instance, data=request.data, partial=True) 
        serializer.is_valid(raise_exception=True)
        serializer.save() 
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object() 
        instance.delete()  
        return Response(
            {"message": "Earning deleted successfully."},
            status=status.HTTP_204_NO_CONTENT
        )
   
class EmployeeLoansViewSet(viewsets.ModelViewSet):  # CRUD functionality
    queryset = EmployeLoans.objects.all()  # Queryset for EmployeLoans
    serializer_class = LoansSerializer  # Ensure this serializer is set up correctly
    permission_classes = [IsAuthenticated]
    pagination_class = PageNumberPagination  # Enable pagination

    def list(self, request, *args, **kwargs):
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        loan_id = request.query_params.get("earning", None)
        emp_id = request.query_params.get("emp_id", None)

        # Apply filters dynamically
        loans = self.get_queryset()
        if emp_id:
            loans = loans.filter(employee__id=emp_id)
        if department_ids:
            loans = loans.filter(employee__hr_details__department__id__in=department_ids)
        if region_ids:
            loans = loans.filter(employee__hr_details__region__id__in=region_ids)
        if loan_id:
            loans = loans.filter(loan__id=loan_id)
        
        # Paginate the queryset
        page = self.paginate_queryset(loans)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        # Return the serialized data in the response
        return Response(serializer.data)
     
class SalaryDetailsViewSet(viewsets.ModelViewSet):
    queryset = SalaryDetails.objects.all()
    serializer_class = SalaryDetailsSerializer
    permission_classes=[IsAuthenticated]
    pagination_class = PageNumberPagination  # Enable pagination

    def perform_create(self, serializer):
        """Assign Regular shift by default if no shift is provided"""
        if not serializer.validated_data.get('work_shift'):
            from hrm.attendance.models import WorkShift
            # Get or create Regular shift
            regular_shift, created = WorkShift.objects.get_or_create(
                name='Regular Shift',
                defaults={
                    'grace_minutes': 15,
                    'total_hours_per_week': 40.00
                }
            )
            serializer.save(work_shift=regular_shift)
        else:
            serializer.save()

    def list(self, request, *args, **kwargs):
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        emp_id = request.query_params.get("emp_id", None)

        # Apply filters dynamically
        queryset = self.get_queryset()
        if emp_id:
            queryset = queryset.filter(employee__id=emp_id)
        if department_ids:
            queryset = queryset.filter(employee__hr_details__department__id__in=department_ids)
        if region_ids:
            queryset = queryset.filter(employee__hr_details__region__id__in=region_ids)

        # Paginate the queryset
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class HRDetailsViewSet(viewsets.ModelViewSet):
    queryset = HRDetails.objects.all()
    serializer_class = HRDetailsSerializer
    permission_classes=[IsAuthenticated]
    pagination_class = PageNumberPagination  # Enable pagination

    def list(self, request, *args, **kwargs):
        from core.utils import get_branch_id_from_request
        
        # Support multiple filter parameter formats
        department_ids = (
            request.query_params.getlist("department[]", None) or 
            request.query_params.getlist("department", None) or
            ([request.query_params.get("department")] if request.query_params.get("department") else None)
        )
        region_ids = (
            request.query_params.getlist("region[]", None) or 
            request.query_params.getlist("region", None) or
            ([request.query_params.get("region")] if request.query_params.get("region") else None)
        )
        project_ids = (
            request.query_params.getlist("project[]", None) or 
            request.query_params.getlist("project", None) or
            ([request.query_params.get("project")] if request.query_params.get("project") else None)
        )
        emp_id = request.query_params.get("emp_id", None)
        
        # Get branch from X-Branch-ID header
        branch_id = get_branch_id_from_request(request)

        # Apply filters dynamically
        queryset = self.get_queryset()
        
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
            
        if emp_id:
            queryset = queryset.filter(employee__id=emp_id)
            
        if department_ids:
            department_ids = [d for d in department_ids if d is not None and d != '']
            if department_ids:
                queryset = queryset.filter(department__id__in=department_ids)
                
        if region_ids:
            region_ids = [r for r in region_ids if r is not None and r != '']
            if region_ids:
                queryset = queryset.filter(region__id__in=region_ids)
                
        if project_ids:
            project_ids = [p for p in project_ids if p is not None and p != '']
            if project_ids:
                queryset = queryset.filter(project__id__in=project_ids)
        
        # Paginate the queryset
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        # Serialize the filtered queryset

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class ContractViewSet(viewsets.ModelViewSet):
    queryset = Contract.objects.all()
    serializer_class = ContractSerializer
    permission_classes=[IsAuthenticated]
    pagination_class = PageNumberPagination  # Enable pagination

    def list(self, request, *args, **kwargs):
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        emp_id = request.query_params.get("emp_id", None)

        # Apply filters dynamically
        queryset = self.get_queryset()
        if emp_id:
            queryset = queryset.filter(employee__id=emp_id)
        if department_ids:
            queryset = queryset.filter(employee__hr_details__department__id__in=department_ids)
        if region_ids:
            queryset = queryset.filter(employee__hr_details__region__id__in=region_ids)
       
        # Paginate the queryset
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        # Serialize the filtered queryset
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """
        Create a new contract
        """
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['patch'], url_path='terminate')
    def terminate(self, request, pk=None):
        """
        Terminate an existing contract
        """
        contract = self.get_object()
        if contract.status != 'terminated':
            contract.status = 'terminated'
            contract.contract_end_date = datetime.now().date()  # Set end date to now
            contract.save()
            return Response({"status": "Contract terminated successfully."})
        return Response({"error": "Contract is already terminated."}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['patch','post'], url_path='renew')
    def renew(self, request, pk=None):
        """
        Renew an existing contract (single).
        Accepts:
          - renewal_duration (months, default 12)
          - salary_adjustment (percent, default 0)
          - status (default 'active')
        """
        from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
        contract = self.get_object()
        months = int(request.data.get('renewal_duration', 12) or 12)
        pct = request.data.get('salary_adjustment', 0) or 0
        try:
            pct = Decimal(str(pct))
        except (InvalidOperation, ValueError):
            pct = Decimal('0')
        new_status = str(request.data.get('status', 'active') or 'active')

        # Compute new end date by adding months to current end date (or start if missing)
        base_date = contract.contract_end_date or contract.contract_start_date or timezone.now().date()
        # Add months safely
        total_months = base_date.month - 1 + months
        new_year = base_date.year + total_months // 12
        new_month = (total_months % 12) + 1
        from calendar import monthrange
        last_day = monthrange(new_year, new_month)[1]
        new_day = min(base_date.day, last_day)
        new_end_date = base_date.replace(year=new_year, month=new_month, day=new_day)

        # Adjust salary by percentage
        try:
            new_salary = (contract.salary * (Decimal('1') + (pct / Decimal('100')))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except Exception:
            new_salary = contract.salary

        contract.contract_end_date = new_end_date
        contract.salary = new_salary
        contract.status = new_status
        contract.save()

        return Response({
            "message": "Contract renewed successfully",
            "id": contract.id,
            "contract_end_date": contract.contract_end_date,
            "salary": str(contract.salary),
            "status": contract.status
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='extend')
    def extend(self, request, pk=None):
        """
        Extend an existing contract
        """
        contract = self.get_object()
        if contract.status == 'active':
            extra_days = int(request.data.get('days', 30))  # Default extension period is 30 days
            contract.contract_end_date = contract.contract_end_date + timedelta(days=extra_days)
            contract.save()
            return Response({"status": f"Contract extended by {extra_days} days."})
        return Response({"error": "Only active contracts can be extended."}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='renew')
    def renew_batch(self, request):
        """
        Batch renew contracts.
        Body:
          - ids: [contractId,...] (required)
          - renewal_duration: months (default 12)
          - salary_adjustment: percent (default 0)
          - status: new status (default 'active')
        """
        from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
        ids = request.data.get('ids') or request.data.get('contract_ids') or []
        if not isinstance(ids, list) or not ids:
            return Response({"error": "ids array is required"}, status=status.HTTP_400_BAD_REQUEST)
        months = int(request.data.get('renewal_duration', 12) or 12)
        pct = request.data.get('salary_adjustment', 0) or 0
        try:
            pct = Decimal(str(pct))
        except (InvalidOperation, ValueError):
            pct = Decimal('0')
        new_status = str(request.data.get('status', 'active') or 'active')

        updated = []
        errors = []
        from calendar import monthrange
        for cid in ids:
            try:
                contract = Contract.objects.get(pk=cid)
                base_date = contract.contract_end_date or contract.contract_start_date or timezone.now().date()
                total_months = base_date.month - 1 + months
                new_year = base_date.year + total_months // 12
                new_month = (total_months % 12) + 1
                last_day = monthrange(new_year, new_month)[1]
                new_day = min(base_date.day, last_day)
                new_end_date = base_date.replace(year=new_year, month=new_month, day=new_day)
                # Adjust salary by percentage
                try:
                    new_salary = (contract.salary * (Decimal('1') + (pct / Decimal('100')))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except Exception:
                    new_salary = contract.salary
                contract.contract_end_date = new_end_date
                contract.salary = new_salary
                contract.status = new_status
                contract.save()
                updated.append({"id": contract.id, "contract_end_date": contract.contract_end_date, "salary": str(contract.salary), "status": contract.status})
            except Exception as e:
                errors.append({"id": cid, "error": str(e)})

        return Response({"updated": updated, "errors": errors, "count": len(updated)}, status=status.HTTP_200_OK)

class ContactDetailsViewSet(viewsets.ModelViewSet):
    queryset = ContactDetails.objects.all()
    serializer_class = ContactDetailsSerializer
    permission_classes=[IsAuthenticated]
    pagination_class = PageNumberPagination  # Enable pagination

    def update(self, request, *args, **kwargs):
        """
        Treat PUT as partial updates so profile edits don't require full address payload.
        """
        kwargs['partial'] = True
        return super().update(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        emp_id = request.query_params.get("emp_id", None)

        # Apply filters dynamically
        queryset = self.get_queryset()
        if emp_id:
            queryset = queryset.filter(employee__id=emp_id)
        if department_ids:
            queryset = queryset.filter(employee__hr_details__department__id__in=department_ids)
        if region_ids:
            queryset = queryset.filter(employee__hr_details__region__id__in=region_ids)
        
        # Paginate the queryset
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        # Serialize the filtered queryset
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class NextOfKinViewSet(viewsets.ModelViewSet):
    queryset = NextOfKin.objects.all()
    serializer_class = NextOfKinSerializer
    permission_classes=[IsAuthenticated]
    pagination_class = PageNumberPagination  # Enable pagination

    def list(self, request, *args, **kwargs):
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        emp_id = request.query_params.get("emp_id", None)

        # Apply filters dynamically
        queryset = self.get_queryset()
        if emp_id:
            queryset = queryset.filter(employee__id=emp_id)
        if department_ids:
            queryset = queryset.filter(employee__hr_details__department__id__in=department_ids)
        if region_ids:
            queryset = queryset.filter(employee__hr_details__region__id__in=region_ids)
        # Paginate the queryset
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        # Serialize the filtered queryset
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class EmployeePayrollDataViewSet(viewsets.ViewSet):
    def list(self, request, *args, **kwargs):
        """
        Fetch payroll data based on category and title.
        """
        category = str(request.query_params.get('category', '')).lower()
        title = str(request.query_params.get('title[]', ''))
        employment_type=request.query_params.get('employment_type', '')
        print(category)
        
        if category == "loans":
            data = EmployeLoans.objects.filter(employee__salary_details__employment_type__icontains=employment_type)
            serializer = EmployeeLoanSerializer(data, many=True)
        elif category == "deductions":
            data = Deductions.objects.filter(deduction__title=title,employee__salary_details__employment_type__icontains=employment_type)
            serializer = DeductionsSerializer(data, many=True)
        elif category == "benefits":
            data = Benefits.objects.filter(benefit__title=title,employee__salary_details__employment_type__icontains=employment_type)
            serializer = BenefitsSerializer(data, many=True)
        elif category == "earnings":
            data = Earnings.objects.filter(earning__title=title,employee__salary_details__employment_type__icontains=employment_type)
            serializer = EarningsSerializer(data, many=True)
        else:
            return Response(
                {"error": "Invalid category. Choose from: Loans, Deductions, Benefits, Earnings."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        """
        Create or update employee payroll data based on category.
        """
        category = str(request.data.get('category')).lower()
        title = str(request.data.get('title'))
        employee_id = request.data.get('employee_id')

        if category == "loans":
            model = EmployeLoans
            serializer_class = EmployeeLoanSerializer
        elif category == "deductions":
            model = Deductions
            serializer_class = DeductionsSerializer
        elif category == "benefits":
            model = Benefits
            serializer_class = BenefitsSerializer
        elif category == "earnings":
            model = Earnings
            serializer_class = EarningsSerializer
        else:
            return Response(
                {"error": "Invalid category. Choose from: Loans, Deductions, Benefits, Earnings."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get the object to update or create a new one if not found
        instance = get_object_or_404(model, employee_id=employee_id, id=request.data.get("id"))
        serializer = serializer_class(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class JobTitleViewSet(BaseModelViewSet):
    """
    ViewSet for managing job titles.
    """
    queryset = JobTitle.objects.all()
    serializer_class = JobTitleSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['title']
    ordering_fields = ['title']
    ordering = ['title']

class JobGroupViewSet(BaseModelViewSet):
    """
    ViewSet for managing job groups.
    """
    queryset = JobGroup.objects.all()
    serializer_class = JobGroupSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['title', 'description']
    ordering_fields = ['title']
    ordering = ['title']

class WorkersUnionViewSet(BaseModelViewSet):
    """
    ViewSet for managing workers unions.
    """
    queryset = WorkersUnion.objects.all()
    serializer_class = WorkersUnionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ['name', 'code', 'registration_number']
    ordering_fields = ['name', 'code']
    ordering = ['name']

class ESSSettingsViewSet(APIView):
    """
    API View for ESS Settings (Singleton).
    Provides retrieve and update functionality only.
    Accessible to all authenticated users, including those without Employee records.
    Uses APIView instead of ViewSet to completely bypass employee filtering.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk=None):
        """
        Get ESS settings - accessible to all users.
        Does not require employee record.
        """
        try:
            from hrm.attendance.models import ESSSettings
            from hrm.attendance.serializers import ESSSettingsSerializer
            from core.response import APIResponse, get_correlation_id
            
            correlation_id = get_correlation_id(request)
            
            # Load settings without employee context
            settings = ESSSettings.load()
            serializer = ESSSettingsSerializer(settings)
            
            return APIResponse.success(
                data=serializer.data,
                message='ESS settings retrieved successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            from core.response import APIResponse, get_correlation_id
            correlation_id = get_correlation_id(request)
            logger.error(f"Error fetching ESS settings: {str(e)}", exc_info=True)
            import traceback
            logger.error(traceback.format_exc())
            
            # Return default settings if table doesn't exist yet or any error occurs
            # This ensures ESS settings are always available, even without migrations
            return APIResponse.success(
                data={
                    'id': 1,
                    'enable_shift_based_restrictions': True,
                    'exempt_roles': [],
                    'exempt_roles_details': [],
                    'allow_payslip_view': True,
                    'allow_leave_application': True,
                    'allow_timesheet_application': True,  # Enable all by default
                    'allow_overtime_application': True,
                    'allow_advance_salary_application': True,
                    'allow_losses_damage_submission': True,
                    'allow_expense_claims_application': True,
                    'require_password_change_on_first_login': True,
                    'session_timeout_minutes': 60,
                    'allow_weekend_login': False,
                    'max_failed_login_attempts': 5,
                    'account_lockout_duration_minutes': 30
                },
                message='Using default settings - run "python manage.py setup_ess_settings" to persist',
                correlation_id=correlation_id
            )
    
    def put(self, request, pk=None):
        """Update ESS settings (PUT)"""
        return self.patch(request, pk)
    
    def patch(self, request, pk=None):
        """Update ESS settings"""
        try:
            from hrm.attendance.models import ESSSettings
            from hrm.attendance.serializers import ESSSettingsSerializer
            from core.response import APIResponse, get_correlation_id
            
            correlation_id = get_correlation_id(request)
            settings = ESSSettings.load()
            serializer = ESSSettingsSerializer(settings, data=request.data, partial=True)
            
            if serializer.is_valid():
                serializer.save()
                return APIResponse.success(
                    data=serializer.data,
                    message='ESS settings updated successfully',
                    correlation_id=correlation_id
                )
            
            return APIResponse.validation_error(
                message='Validation failed',
                errors=serializer.errors,
                correlation_id=correlation_id
            )
        except Exception as e:
            from core.response import APIResponse, get_correlation_id
            correlation_id = get_correlation_id(request)
            logger.error(f"Error updating ESS settings: {str(e)}", exc_info=True)
            
            return APIResponse.server_error(
                message='Failed to update ESS settings. Please run migrations first.',
                error_id=str(e),
                correlation_id=correlation_id
            )

@api_view(['GET'])
def employee_analytics(request):
    """
    Get employee analytics data.
    """
    try:
        period = request.query_params.get('period', 'month')
        business_id = request.query_params.get('business_id')
        
        analytics_service = EmployeeAnalyticsService()
        data = analytics_service.get_employee_dashboard_data(
            business_id=business_id,
            period=period
        )
        
        return Response({
            'success': True,
            'data': data,
            'timestamp': timezone.now().isoformat()
        })
    except Exception as e:
        return Response({
            'success': False,
            'message': f'Error fetching employee analytics: {str(e)}',
            'timestamp': timezone.now().isoformat()
        }, status=500)

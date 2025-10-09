from django.utils.timezone import make_aware
from datetime import datetime, date
from rest_framework.views import APIView
from rest_framework.response import Response
from hrm.employees.serializers import *
from hrm.payroll.models import *
from hrm.payroll.serializers import *
from hrm.payroll_settings.serializers import (
    ScheduledPayslipSerializer, ApprovalSerializer, FormulaItemSerializer, 
    SplitRatioSerializer, FormulasSerializer, PayrollComponentsSerializer
)
from .models import PayrollComponents, ScheduledPayslip, Approval, Formulas, Loans, FormulaItems, SplitRatio
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Value, F
from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers
from hrm.employees.models import HRDetails
from authmanagement.models import CustomUser
from .services.formula_version_service import FormulaVersionService


class PayrollComponentsViewSet(viewsets.ViewSet):
    
    def list(self, request, *args, **kwargs):
        try:
            # Get query parameters for filtering
            category = request.query_params.get('category')
            taxable_status = request.query_params.get('taxable_status')
            is_active = request.query_params.get('is_active', 'true').lower() == 'true'
            
            # Build queryset
            components = PayrollComponents.objects.filter(is_active=is_active)
            
            if category:
                components = components.filter(category=category)
            if taxable_status:
                components = components.filter(taxable_status=taxable_status)
                
            serializer = PayrollComponentsSerializer(components, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='payrolldata')
    def get_payroll_data(self, request):
        """Get payroll data for a specific component"""
        try:
            _params = getattr(request, 'query_params', request.GET)
            component_id = _params.get('component_id', None)
            employee_id = _params.get('employee_id', None)
            department = _params.get('department', None)
            region = _params.get('region', None)
            project = _params.get('project', None)
            
            if not component_id:
                return Response({'error': 'Component ID is required'}, status=status.HTTP_400_BAD_REQUEST)

            item = PayrollComponents.objects.filter(id=component_id).first()
            if item is None:
                return Response({'error': 'Component not found'}, status=status.HTTP_404_NOT_FOUND)

            response_data = []
            rate = 0
            
            if employee_id is not None:
                # Get data for specific employee
                employee = Employee.objects.filter(
                    salary_details__employment_type__icontains="regular",
                    contracts__status='active',
                    id=employee_id
                ).first()
                
                if employee:
                    if getattr(item, "mode", None) == 'perday':
                        rate = SalaryDetails.objects.get(employee=employee).daily_rate
                    if getattr(item, "mode", None) == 'perhour':
                        rate = SalaryDetails.objects.get(employee=employee).hourly_rate
                    hr = HRDetails.objects.filter(employee=employee).first() if employee else None
                    
                    response_data = {
                        "id": 0,
                        "component": {
                            "id": getattr(item, 'id', None),
                            "wb_code": item.wb_code,
                            "title": item.title,
                            "checkoff": item.checkoff,
                            "statutory": item.statutory,
                            "constant": item.constant,
                            "mode": item.mode,
                        },
                        "employee": {
                            "name": f"{employee.user.first_name} {employee.user.last_name}",
                            "staffNo": hr.job_or_staff_number if hr else None,
                            "id": getattr(employee, 'id', None),
                        } if employee else None,
                        "data": {
                            "wb_code": item.wb_code,
                            "is_active": True,
                            "amount": 0,
                            "quantity": 0,
                            "checkoff": item.checkoff,
                            "employer_amount": 0,
                            "paid_to_date": 0
                        }
                    }
            else:
                # Get data for all employees with filters
                employees_query = Employee.objects.filter(
                    salary_details__employment_type__icontains="regular",
                    contracts__status='active'
                ).select_related('user').prefetch_related('hr_details')
                
                # Apply department filter
                if department:
                    if isinstance(department, list):
                        employees_query = employees_query.filter(hr_details__department_id__in=department)
                    else:
                        employees_query = employees_query.filter(hr_details__department_id=department)
                
                # Apply region filter
                if region:
                    if isinstance(region, list):
                        employees_query = employees_query.filter(hr_details__region_id__in=region)
                    else:
                        employees_query = employees_query.filter(hr_details__region_id=region)
                
                # Apply project filter
                if project:
                    if isinstance(project, list):
                        employees_query = employees_query.filter(hr_details__project_id__in=project)
                    else:
                        employees_query = employees_query.filter(hr_details__project_id=project)
                
                for employee in employees_query:
                    if getattr(item, "mode", None) == 'perday':
                        try:
                            rate = SalaryDetails.objects.get(employee=employee).daily_rate
                        except SalaryDetails.DoesNotExist:
                            rate = 0
                    if getattr(item, "mode", None) == 'perhour':
                        try:
                            rate = SalaryDetails.objects.get(employee=employee).hourly_rate
                        except SalaryDetails.DoesNotExist:
                            rate = 0
                    
                    hr = HRDetails.objects.filter(employee=employee).first()
                    response_data.append({
                        "id": 0,
                        "component": {
                            "id": getattr(item, 'id', None),
                            "wb_code": item.wb_code,
                            "title": item.title,
                            "checkoff": item.checkoff,
                            "statutory": item.statutory,
                            "constant": item.constant,
                            "mode": item.mode,
                        },
                        "employee": {
                            "name": f"{employee.user.first_name} {employee.user.last_name}",
                            "staffNo": hr.job_or_staff_number if hr else None,
                            "id": getattr(employee, 'id', None)
                        } if employee else None,
                        "data": {
                            "wb_code": item.wb_code,
                            "is_active": True,
                            "amount": 0,
                            "quantity": 0,
                            "checkoff": item.checkoff,
                            "employer_amount": 0,
                            "paid_to_date": 0
                        }
                    })

            return Response(response_data, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
class ScheduledPayslipViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing scheduled payslip emails.
    Allows creating, editing, and managing scheduled payslip distributions.
    """
    queryset = ScheduledPayslip.objects.all()
    serializer_class = ScheduledPayslipSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'delivery_status', 'document_type']
    search_fields = ['document_type', 'comments']
    ordering_fields = ['scheduled_time', 'payroll_period', 'created_at']

    def perform_create(self, serializer):
        serializer.save(composer=self.request.user)

    def perform_update(self, serializer):
        serializer.save()

class FormulaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Formulas
        fields = '__all__'

class FormulaViewSet(viewsets.ModelViewSet):
    queryset = Formulas.objects.all()
    serializer_class = FormulasSerializer
    permission_classes=[IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        _params = getattr(self.request, 'query_params', self.request.GET)
        type_param = _params.get('type')
        category = _params.get('category')
        effective_date = _params.get('effective_date')
        if type_param:
            qs = qs.filter(type=type_param)
        if category:
            qs = qs.filter(category=category)
        if effective_date:
            try:
                dt = make_aware(datetime.strptime(effective_date[:10], "%Y-%m-%d"))
                qs = qs.filter(
                    (models.Q(effective_from__isnull=True) | models.Q(effective_from__lte=dt)) &
                    (models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=dt))
                )
            except Exception as e:
                # Log the error for debugging but continue with default behavior
                print(f"Error filtering formulas by date: {e}")
                # Continue with unfiltered queryset
        return qs.order_by('-is_current', '-effective_from')

    @action(detail=True, methods=['get', 'post', 'patch'], url_path='items')
    def items(self, request, pk=None):
        formula = self.get_object()
        if request.method == 'GET':
            items = FormulaItems.objects.filter(formula=formula)
            serializer = FormulaItemSerializer(items, many=True)
            return Response(serializer.data)
        elif request.method == 'POST':
            serializer = FormulaItemSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save(formula=formula)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        elif request.method == 'PATCH':
            items = FormulaItems.objects.filter(formula=formula)
            for item in items:
                item.delete()
            for item_data in request.data:
                serializer = FormulaItemSerializer(data=item_data)
                if serializer.is_valid():
                    serializer.save(formula=formula)
            return Response({"detail": "Items updated successfully"}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='effective')
    def get_effective_formula(self, request):
        """Get effective formula for a specific date and type"""
        try:
            formula_service = FormulaVersionService()
            
            formula_type = request.query_params.get('type')
            category = request.query_params.get('category')
            payroll_date = request.query_params.get('payroll_date')
            formula_id = request.query_params.get('formula_id')
            
            if not formula_type:
                return Response(
                    {"detail": "Formula type is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Parse payroll date if provided
            parsed_date = None
            if payroll_date:
                try:
                    parsed_date = datetime.strptime(payroll_date[:10], "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"detail": "Invalid payroll date format"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Parse formula_id if provided
            parsed_formula_id = None
            if formula_id:
                try:
                    parsed_formula_id = int(formula_id)
                except ValueError:
                    return Response(
                        {"detail": "Invalid formula ID"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            effective_formula = formula_service.get_effective_formula(
                formula_type=formula_type,
                category=category,
                payroll_date=parsed_date,
                formula_id=parsed_formula_id
            )
            
            if effective_formula:
                serializer = FormulasSerializer(effective_formula)
                return Response(serializer.data, status=status.HTTP_200_OK)
            else:
                return Response(
                    {"detail": "No effective formula found"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except Exception as e:
            return Response(
                {"detail": f"Error getting effective formula: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='history')
    def get_formula_history(self, request):
        """Get formula history for a specific period"""
        try:
            formula_service = FormulaVersionService()
            
            formula_type = request.query_params.get('type')
            category = request.query_params.get('category')
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            
            if not formula_type:
                return Response(
                    {"detail": "Formula type is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Parse dates if provided
            parsed_start_date = None
            parsed_end_date = None
            
            if start_date:
                try:
                    parsed_start_date = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"detail": "Invalid start date format"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            if end_date:
                try:
                    parsed_end_date = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"detail": "Invalid end date format"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            formula_history = formula_service.get_formula_history(
                formula_type=formula_type,
                category=category,
                start_date=parsed_start_date,
                end_date=parsed_end_date
            )
            
            serializer = FormulaSerializer(formula_history, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
                
        except Exception as e:
            return Response(
                {"detail": f"Error getting formula history: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'], url_path='migrate')
    def migrate_formulas(self, request):
        """Migrate formulas to a new version"""
        try:
            formula_service = FormulaVersionService()
            
            new_version = request.data.get('new_version')
            formula_type = request.data.get('formula_type')
            category = request.data.get('category')
            
            if not new_version:
                return Response(
                    {"detail": "New version is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            migration_result = formula_service.migrate_formulas_to_new_version(
                new_version=new_version,
                formula_type=formula_type,
                category=category
            )
            
            if migration_result['success']:
                return Response({
                    "detail": f"Successfully migrated {migration_result['migrated_count']} formulas",
                    "migrated_count": migration_result['migrated_count']
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    "detail": "Migration failed",
                    "errors": migration_result['errors']
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            return Response(
                {"detail": f"Error migrating formulas: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='relief-status')
    def get_relief_status(self, request):
        """Get relief status for a specific date"""
        try:
            formula_service = FormulaVersionService()
            
            relief_type = request.query_params.get('relief_type')
            payroll_date = request.query_params.get('payroll_date')
            
            if not relief_type:
                return Response(
                    {"detail": "Relief type is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Parse payroll date if provided
            parsed_date = None
            if payroll_date:
                try:
                    parsed_date = datetime.strptime(payroll_date[:10], "%Y-%m-%d").date()
                except ValueError:
                    return Response(
                        {"detail": "Invalid payroll date format"}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            relief_status = formula_service.get_relief_status(
                relief_type=relief_type,
                payroll_date=parsed_date
            )
            
            return Response(relief_status, status=status.HTTP_200_OK)
                
        except Exception as e:
            return Response(
                {"detail": f"Error getting relief status: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class FormulaManagementAPIView(APIView):
    """API view for formula management operations"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get formula management dashboard data"""
        try:
            formula_service = FormulaVersionService()
            
            # Get current formulas by type
            current_formulas = {}
            formula_types = ['income', 'deduction', 'levy']
            
            for formula_type in formula_types:
                current_formula = formula_service.get_effective_formula(
                    formula_type=formula_type,
                    payroll_date=date.today()
                )
                if current_formula:
                    current_formulas[formula_type] = {
                        'id': current_formula.id,
                        'title': current_formula.title,
                        'version': current_formula.version,
                        'effective_from': current_formula.effective_from,
                        'is_current': current_formula.is_current
                    }
            
            # Get relief status
            relief_status = {}
            relief_types = ['Personal Relief', 'SHIF Relief', 'Housing Levy Relief']
            
            for relief_type in relief_types:
                status_info = formula_service.get_relief_status(relief_type)
                relief_status[relief_type] = status_info
            
            return Response({
                'current_formulas': current_formulas,
                'relief_status': relief_status,
                'last_updated': datetime.now().isoformat()
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {"detail": f"Error getting formula management data: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Handle formula management operations"""
        try:
            operation = request.data.get('operation')
            
            if operation == 'validate_transition':
                return self._validate_formula_transition(request)
            elif operation == 'apply_transition':
                return self._apply_formula_transition(request)
            elif operation == 'update_relief':
                return self._update_relief_status(request)
            else:
                return Response(
                    {"detail": f"Unknown operation: {operation}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
                
        except Exception as e:
            return Response(
                {"detail": f"Error processing formula management operation: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _validate_formula_transition(self, request):
        """Validate formula transition"""
        try:
            formula_service = FormulaVersionService()
            
            old_formula_id = request.data.get('old_formula_id')
            new_formula_id = request.data.get('new_formula_id')
            
            if not old_formula_id or not new_formula_id:
                return Response(
                    {"detail": "Both old and new formula IDs are required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            old_formula = Formulas.objects.get(id=old_formula_id)
            new_formula = Formulas.objects.get(id=new_formula_id)
            
            validation_result = formula_service.validate_formula_compatibility(
                old_formula, new_formula
            )
            
            return Response(validation_result, status=status.HTTP_200_OK)
            
        except Formulas.DoesNotExist:
            return Response(
                {"detail": "One or both formulas not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"detail": f"Error validating transition: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _apply_formula_transition(self, request):
        """Apply formula transition"""
        try:
            formula_service = FormulaVersionService()
            
            old_formula_id = request.data.get('old_formula_id')
            new_formula_id = request.data.get('new_formula_id')
            transition_date = request.data.get('transition_date')
            
            if not old_formula_id or not new_formula_id or not transition_date:
                return Response(
                    {"detail": "Old formula ID, new formula ID, and transition date are required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Parse transition date
            try:
                parsed_transition_date = datetime.strptime(transition_date[:10], "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"detail": "Invalid transition date format"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            old_formula = Formulas.objects.get(id=old_formula_id)
            new_formula = Formulas.objects.get(id=new_formula_id)
            
            success = formula_service.handle_formula_transition(
                old_formula, new_formula, parsed_transition_date
            )
            
            if success:
                return Response({
                    "detail": "Formula transition applied successfully"
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    "detail": "Failed to apply formula transition"
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Formulas.DoesNotExist:
            return Response(
                {"detail": "One or both formulas not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"detail": f"Error applying transition: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _update_relief_status(self, request):
        """Update relief status"""
        try:
            relief_type = request.data.get('relief_type')
            is_active = request.data.get('is_active')
            effective_date = request.data.get('effective_date')
            
            if not relief_type:
                return Response(
                    {"detail": "Relief type is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Find and update relief
            relief = Relief.objects.filter(title__icontains=relief_type).first()
            if not relief:
                return Response(
                    {"detail": f"Relief '{relief_type}' not found"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            relief.is_active = is_active
            if effective_date:
                relief.notes = f"Status updated effective {effective_date}"
            relief.save()
            
            return Response({
                "detail": f"Relief '{relief_type}' status updated successfully",
                "relief": {
                    "title": relief.title,
                    "is_active": relief.is_active,
                    "type": relief.type,
                    "percentage": relief.percentage,
                    "fixed_limit": relief.fixed_limit
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {"detail": f"Error updating relief status: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class ApprovalViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing module approvers.
    Allows setting approvers for different modules like Losses & Damages, Advance Pay, Payroll, etc.
    """
    queryset = Approval.objects.all()
    serializer_class = ApprovalSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['content_type']
    search_fields = ['user__first_name', 'user__last_name', 'content_type__model']
    ordering_fields = ['created_at', 'content_type__model']

    def create(self, request, *args, **kwargs):
        try:
            request.data['user'] = CustomUser.objects.get(email=request.data.get('user'))
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
    def update(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            user = CustomUser.objects.get(email=request.data.get('user'))
            instance.user = user
            instance.save()
            return Response(self.get_serializer(instance).data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    def get_queryset(self):
        """Filter approvals based on query parameters."""
        queryset = super().get_queryset()
        _params = getattr(self.request, 'query_params', self.request.GET)
        content_type_id = _params.get('content_type_id')
        if content_type_id:
            queryset = queryset.filter(content_type_id=content_type_id)
        if _params.get('user_id'):
            queryset = queryset.filter(user_id=_params.get('user_id'))
        if _params.get('module'):
            queryset = queryset.filter(content_type__model=_params.get('module'))
        return queryset.select_related('user', 'content_type')
    
    @action(detail=False, methods=['get'], url_path='content-types')
    def content_types(self, request):
        """Return list of content types available for approval assignment."""
        content_types = []
        
        # Get all content types
        all_content_types = ContentType.objects.all()
        
        for ct in all_content_types:
            try:
                model_class = ct.model_class()
                has_approval_fields = False
                if model_class is not None:
                    # Get all field names for this model
                    meta = getattr(model_class, '_meta', None)
                    field_names = [f.name for f in meta.get_fields()] if meta else []
                    
                    # Check if model has any approval-related fields
                    has_approval_fields = any(
                        field in field_names 
                        for field in ['approver', 'approved', 'status']
                    )
                
                if has_approval_fields and model_class is not None:
                    # Get human-readable name from model's Meta class if available
                    meta = getattr(model_class, '_meta', None)
                    verbose_name = getattr(meta, 'verbose_name', ct.model.title()) if meta else ct.model.title()
                    verbose_name_plural = getattr(meta, 'verbose_name_plural', None) if meta else None
                    
                    content_types.append({
                        'id': ct.id,
                        'app_label': ct.app_label,
                        'model': ct.model,
                        'name': verbose_name_plural or verbose_name,
                        'icon':'fas fa-cog',
                    })
            except Exception as e:
                # Skip if there's any error inspecting the model
                continue
        return Response(content_types)

    

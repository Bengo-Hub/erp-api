from statistics import LinearRegression
from rest_framework import viewsets, permissions, filters
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db import models
from django.db.models import Q, F
from django_filters.rest_framework import DjangoFilterBackend
from datetime import timedelta
from datetime import datetime
import pandas as pd
import numpy as np
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from .models import *
from .serializers import *
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from django.db import transaction
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


# finished product and raw material views are not defined in the original code
class FinishedProductViewSet(BaseModelViewSet):
    queryset = Products.objects.filter(Q(is_manufactured=True) & Q(status='active')).select_related('category', 'brand')
    serializer_class = FinalProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['description', 'title']
    search_fields = ['title', 'description']
    ordering_fields = ['id', 'title', 'description']

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | 
                Q(description__icontains=search)
            )
        # Branch scoping - filter by stock's branch when provided
        try:
            from core.utils import get_branch_id_from_request
            branch_id = self.request.query_params.get('branch_id') or get_branch_id_from_request(self.request)
        except Exception:
            branch_id = None

        if branch_id:
            queryset = queryset.filter(stock__branch_id=branch_id).distinct()
        return queryset

class RawMaterialViewSet(BaseModelViewSet):
    queryset = Products.objects.filter(stock__is_raw_material=True, stock__delete_status=False).select_related('category', 'brand')
    serializer_class = RawMaterialProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['description', 'title']
    search_fields = ['title', 'description']
    ordering_fields = ['id', 'title', 'description']

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | 
                Q(description__icontains=search)
            )
        # Branch scoping - filter by stock's branch when provided
        try:
            from core.utils import get_branch_id_from_request
            branch_id = self.request.query_params.get('branch_id') or get_branch_id_from_request(self.request)
        except Exception:
            branch_id = None

        if branch_id:
            queryset = queryset.filter(stock__branch_id=branch_id).distinct()
        return queryset

# views.py

class ProductFormulaViewSet(BaseModelViewSet):
    queryset = ProductFormula.objects.filter(is_active=True).select_related('final_product')
    serializer_class = ProductFormulaSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['final_product', 'is_active', 'version']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at', 'updated_at', 'version']
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['markup_percentage'] = self.request.query_params.get('markup', 30)
        return context
    
    def create(self, request, *args, **kwargs):
        try:
            correlation_id = get_correlation_id(request)
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return APIResponse.validation_error(message='Product formula validation failed', errors=serializer.errors, correlation_id=correlation_id)
            with transaction.atomic():
                instance = serializer.save()
                AuditTrail.log(operation=AuditTrail.CREATE, module='manufacturing', entity_type='ProductFormula', entity_id=instance.id, user=request.user, reason=f'Created product formula', request=request)
            return APIResponse.created(data=self.get_serializer(instance).data, message='Product formula created successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error creating product formula: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error creating product formula', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=True, methods=['post'])
    def add_ingredient(self, request, pk=None):
        formula = self.get_object()
        serializer = FormulaIngredientSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.save(formula=formula)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['delete'])
    def remove_ingredient(self, request, pk=None):
        formula = self.get_object()
        ingredient_id = request.data.get('ingredient_id')
        
        try:
            ingredient = formula.ingredients.get(id=ingredient_id)
            ingredient.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except FormulaIngredient.DoesNotExist:
            return Response(
                {"detail": "Ingredient not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['post'])
    def create_new_version(self, request, pk=None):
        formula = self.get_object()
        
        # Validate request data
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create new version
        new_formula = formula.clone_for_new_version()
        
        # Update fields if provided in request
        data = serializer.validated_data
        for field in ['name', 'description', 'expected_output_quantity', 'output_unit']:
            if field in data:
                setattr(new_formula, field, data[field])
        
        # Handle ingredients if provided
        if 'ingredients' in request.data:
            new_formula.ingredients.all().delete()
            for ingredient_data in request.data['ingredients']:
                FormulaIngredient.objects.create(
                    formula=new_formula,
                    raw_material_id=ingredient_data['raw_material']['id'],
                    quantity=ingredient_data['quantity'],
                    unit_id=ingredient_data['unit']['id'],
                    notes=ingredient_data.get('notes', '')
                )
        
        new_formula.save()
        
        return Response(
            self.get_serializer(new_formula).data, 
            status=status.HTTP_201_CREATED
        )


class FormulaIngredientViewSet(BaseModelViewSet):
    queryset = FormulaIngredient.objects.all().select_related('formula', 'raw_material', 'unit')
    serializer_class = FormulaIngredientSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['formula', 'raw_material']


class ProductionBatchViewSet(BaseModelViewSet):
    queryset = ProductionBatch.objects.all().select_related('formula', 'location', 'supervisor', 'created_by')
    serializer_class = ProductionBatchSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'formula', 'location', 'supervisor']
    search_fields = ['batch_number', 'notes']
    ordering_fields = ['scheduled_date', 'created_at', 'start_date', 'end_date', 'status']
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset()
        try:
            from core.utils import get_branch_id_from_request
            branch_id = self.request.query_params.get('branch_id') or get_branch_id_from_request(self.request)
        except Exception:
            branch_id = None

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        if not self.request.user.is_superuser:
            from business.models import Branch
            user = self.request.user
            owned_branches = Branch.objects.filter(business__owner=user)
            employee_branches = Branch.objects.filter(business__employees__user=user)
            branches = owned_branches | employee_branches
            queryset = queryset.filter(branch__in=branches)
        return queryset
    
    @action(detail=True, methods=['post'])
    def start_production(self, request, pk=None):
        try:
            correlation_id = get_correlation_id(request)
            batch = self.get_object()
            batch.start_production()
            AuditTrail.log(operation=AuditTrail.UPDATE, module='manufacturing', entity_type='ProductionBatch', entity_id=batch.id, user=request.user, reason='Production started', request=request)
            return APIResponse.success(data=self.get_serializer(batch).data, message='Production started successfully', correlation_id=correlation_id)
        except ValueError as e:
            logger.error(f'Error starting production: {str(e)}')
            return APIResponse.bad_request(message='Cannot start production', error_id=str(e), correlation_id=get_correlation_id(request))
        except Exception as e:
            logger.error(f'Error starting production: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error starting production', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=True, methods=['post'])
    def complete_production(self, request, pk=None):
        try:
            correlation_id = get_correlation_id(request)
            batch = self.get_object()
            actual_quantity = Decimal(str(request.data.get('actual_quantity'))) if request.data.get('actual_quantity') else None
            
            if not actual_quantity:
                return APIResponse.bad_request(message='actual_quantity is required', error_id='missing_quantity', correlation_id=correlation_id)
            
            batch.complete_production(Decimal(actual_quantity))
            AuditTrail.log(operation=AuditTrail.UPDATE, module='manufacturing', entity_type='ProductionBatch', entity_id=batch.id, user=request.user, reason=f'Production completed with quantity {actual_quantity}', request=request)
            return APIResponse.success(data=self.get_serializer(batch).data, message='Production completed successfully', correlation_id=correlation_id)
        except ValueError as e:
            logger.error(f'Error completing production: {str(e)}')
            return APIResponse.bad_request(message='Cannot complete production', error_id=str(e), correlation_id=get_correlation_id(request))
        except Exception as e:
            logger.error(f'Error completing production: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error completing production', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=True, methods=['post'])
    def cancel_production(self, request, pk=None):
        try:
            correlation_id = get_correlation_id(request)
            batch = self.get_object()
            reason = request.data.get('reason', '')
            
            batch.cancel_production(reason)
            AuditTrail.log(operation=AuditTrail.CANCEL, module='manufacturing', entity_type='ProductionBatch', entity_id=batch.id, user=request.user, reason=f'Production cancelled: {reason}', request=request)
            return APIResponse.success(data=self.get_serializer(batch).data, message='Production cancelled successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error cancelling production: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error cancelling production', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=True, methods=['post'])
    def add_quality_check(self, request, pk=None):
        try:
            correlation_id = get_correlation_id(request)
            batch = self.get_object()
            serializer = QualityCheckSerializer(data=request.data)
            
            if serializer.is_valid():
                quality_check = serializer.save(batch=batch, inspector=request.user)
                AuditTrail.log(operation=AuditTrail.CREATE, module='manufacturing', entity_type='QualityCheck', entity_id=quality_check.id, user=request.user, reason='Quality check added', request=request)
                return APIResponse.created(data=serializer.data, message='Quality check added successfully', correlation_id=correlation_id)
            
            return APIResponse.validation_error(message='Quality check validation failed', errors=serializer.errors, correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error adding quality check: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error adding quality check', error_id=str(e), correlation_id=get_correlation_id(request))
    
    @action(detail=False, methods=['get'])
    def check_material_availability(self, request):
        try:
            correlation_id = get_correlation_id(request)
            formula_id = request.query_params.get('formula')
            quantity = request.query_params.get('quantity')
            
            if not formula_id or not quantity:
                return APIResponse.bad_request(message='formula and quantity parameters are required', error_id='missing_params', correlation_id=correlation_id)
            
            formula = ProductFormula.objects.get(id=formula_id)
            batch_ratio = Decimal(quantity) / Decimal(formula.expected_output_quantity)
            
            missing_materials = []
            for ingredient in formula.ingredients.all():
                required_quantity = ingredient.quantity * batch_ratio
                stock_level = ingredient.raw_material.stock_level
                
                if stock_level < required_quantity:
                    missing_materials.append({
                        'material': ingredient.raw_material.product.title,
                        'required': required_quantity,
                        'available': stock_level,
                        'shortage': required_quantity - stock_level
                    })
            
            return APIResponse.success(data=missing_materials, message='Material availability checked', correlation_id=correlation_id)
        except ProductFormula.DoesNotExist:
            return APIResponse.not_found(message='Formula not found', error_id='formula_not_found', correlation_id=get_correlation_id(request))
        except Exception as e:
            logger.error(f'Error checking material availability: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error checking material availability', error_id=str(e), correlation_id=get_correlation_id(request))


class QualityCheckViewSet(viewsets.ModelViewSet):
    queryset = QualityCheck.objects.all()
    serializer_class = QualityCheckSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['batch', 'result', 'inspector']
    ordering_fields = ['check_date', 'created_at']
    
    def perform_create(self, serializer):
        print(serializer.validated_data)
        serializer.save(inspector=self.request.user)
        
    @action(detail=False, methods=['get'], url_path='inspectors', name='inspectors')
    def inspectors(self, request):
        """
        Get list of inspectors who can perform quality checks
        """        
        # Get users with quality check permissions
        quality_check_permission = Permission.objects.filter(codename__in=[
            'add_qualitycheck', 'change_qualitycheck', 'view_qualitycheck'
        ])
        
        # Get users with any of these permissions
        inspectors = User.objects.filter(
            Q(groups__permissions__in=quality_check_permission) | 
            Q(user_permissions__in=quality_check_permission)
        ).distinct()
        
        # Format response
        result = [{
            'id': user.id,
            'username': user.username,
            'full_name': f"{user.first_name} {user.last_name}".strip() or user.username,
            'email': user.email
        } for user in inspectors]
        
        return Response(result)


class ManufacturingAnalyticsViewSet(viewsets.ModelViewSet):
    queryset = ManufacturingAnalytics.objects.all()
    serializer_class = ManufacturingAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['get'], name='dashboard', url_path='dashboard')
    def dashboard(self, request):
        """
        Get manufacturing dashboard data for the specified time period
        """
        period = request.query_params.get('period', 'month')
        
        # Define time range based on period
        today = datetime.now().date()
        if period == 'week':
            start_date = today - timedelta(days=7)
        elif period == 'month':
            start_date = today - timedelta(days=30)
        elif period == 'quarter':
            start_date = today - timedelta(days=90)
        elif period == 'year':
            start_date = today - timedelta(days=365)
        else:
            start_date = today - timedelta(days=30)  # Default to month
            
        # Get production statistics
        total_batches = ProductionBatch.objects.filter(
            created_at__date__gte=start_date
        ).count()
        
        completed_batches = ProductionBatch.objects.filter(
            status='completed',
            end_date__date__gte=start_date
        ).count()
        
        in_progress_batches = ProductionBatch.objects.filter(
            status='in_progress'
        ).count()
        
        planned_batches = ProductionBatch.objects.filter(
            status='planned',
            scheduled_date__gte=today
        ).count()
        
        # Calculate completion rate
        completion_rate = round((completed_batches / total_batches * 100) 
                               if total_batches > 0 else 0, 1)
        
        # Get production chart data
        batch_data = ProductionBatch.objects.filter(
            created_at__date__gte=start_date
        ).values('status').annotate(count=models.Count('id'))
        
        production_chart = {
            'labels': [],
            'datasets': [{
                'label': 'Production Batches',
                'data': [],
                'backgroundColor': []
            }]
        }
        
        status_colors = {
            'completed': '#22C55E',  # green
            'in_progress': '#F59E0B',  # amber 
            'planned': '#3B82F6',  # blue
            'cancelled': '#64748B',  # slate
            'failed': '#EF4444',  # red,
        }
        
        for item in batch_data:
            status_display = item['status'].replace('_', ' ').title()
            production_chart['labels'].append(status_display)
            production_chart['datasets'][0]['data'].append(item['count'])
            production_chart['datasets'][0]['backgroundColor'].append(
                status_colors.get(item['status'], '#CBD5E1')  # default slate-300
            )
        
        # Get material alert data
        material_alerts = []
        raw_materials = StockInventory.objects.filter(
            is_raw_material=True,
            delete_status=False
        ).annotate(
            usage_count=models.Count('batch_usages')
        ).order_by('-usage_count')[:10]
        print(raw_materials)
        
        for material in raw_materials:
            if material.stock_level <= material.reorder_level:
                status = 'critical' if material.stock_level <= material.reorder_level / 2 else 'low'
                material_alerts.append({
                    'id': material.id,
                    'name': material.product.title,
                    'current_stock': material.stock_level,
                    'unit': material.unit.title if material.unit else 'Units',
                    'reorder_level': material.reorder_level,
                    'status': status,
                    'last_updated': material.updated_at.isoformat() if material.updated_at else None
                })
        
        # Get materials usage chart data
        materials_chart = {
            'labels': [],
            'datasets': [{
                'label': 'Usage (last 30 days)',
                'data': []
            }]
        }
        
        top_materials = BatchRawMaterial.objects.filter(
            batch__start_date__gte=today - timedelta(days=30)
        ).values('raw_material__product__title').annotate(
            total_quantity=models.Sum('actual_quantity')
        ).order_by('-total_quantity')[:5]
        
        for material in top_materials:
            materials_chart['labels'].append(material['raw_material__product__title'])
            materials_chart['datasets'][0]['data'].append(float(material['total_quantity'] or 0))
        
        # Get recent batches
        recent_batches = []
        batches = ProductionBatch.objects.all().order_by('-created_at')[:5]
        
        for batch in batches:
            recent_batches.append({
                'id': batch.id,
                'batch_number': batch.batch_number,
                'formula_name': batch.formula.name,
                'status': batch.status,
                'scheduled_date': batch.scheduled_date.isoformat() if batch.scheduled_date else None,
                'completed_date': batch.end_date.isoformat() if batch.end_date else None,
                'location': batch.location.location_name if batch.location else None,
                'quantity': batch.planned_quantity
            })
        
        # Assemble response
        response_data = {
            'stats': {
                'total_batches': total_batches,
                'completed_batches': completed_batches,
                'in_progress_batches': in_progress_batches,
                'planned_batches': planned_batches,
                'completion_rate': completion_rate,
                'material_alerts_count': len(material_alerts)
            },
            'production_chart': production_chart,
            'materials_chart': materials_chart,
            'recent_batches': recent_batches,
            'material_alerts': material_alerts
        }
        
        return Response(response_data)
    
    @action(detail=False, methods=['get'])
    def insights(self, request):
        """
        Get manufacturing insights and recommendations
        """
        # Current date for calculations
        today = datetime.now().date()
        
        # Get production efficiency data
        completed_batches = ProductionBatch.objects.filter(
            status='completed',
            end_date__date__gte=today - timedelta(days=90)
        )
        
        # Calculate average production times
        production_times = []
        for batch in completed_batches:
            if batch.start_date and batch.end_date:
                duration = (batch.end_date - batch.start_date).total_seconds() / 3600  # hours
                production_times.append(duration)
        
        avg_production_time = round(sum(production_times) / len(production_times), 1) if production_times else 0
        
        # Get quality metrics
        quality_checks = QualityCheck.objects.filter(
            check_date__date__gte=today - timedelta(days=90)
        )
        
        total_checks = quality_checks.count()
        pass_checks = quality_checks.filter(result='pass').count()
        pass_rate = round((pass_checks / total_checks * 100) if total_checks > 0 else 0, 1)
        
        # Get formulas with quality issues
        problem_formulas = []
        formula_quality_issues = {}
        
        for check in quality_checks.filter(result='fail'):
            formula_id = check.batch.formula.id
            formula_name = check.batch.formula.name
            
            if formula_id not in formula_quality_issues:
                formula_quality_issues[formula_id] = {
                    'id': formula_id,
                    'name': formula_name,
                    'fail_count': 0,
                    'total_count': 0
                }
            
            formula_quality_issues[formula_id]['fail_count'] += 1
            formula_quality_issues[formula_id]['total_count'] += 1
        
        # Add pass counts to each formula
        for check in quality_checks.filter(result='pass'):
            formula_id = check.batch.formula.id
            formula_name = check.batch.formula.name
            
            if formula_id not in formula_quality_issues:
                formula_quality_issues[formula_id] = {
                    'id': formula_id,
                    'name': formula_name,
                    'fail_count': 0,
                    'total_count': 0
                }
            
            formula_quality_issues[formula_id]['total_count'] += 1
        
        # Calculate failure rates and format for output
        for formula_id, data in formula_quality_issues.items():
            fail_rate = round((data['fail_count'] / data['total_count'] * 100), 1)
            
            if fail_rate > 10:  # Only flag formulas with >10% failure rate
                problem_formulas.append({
                    'id': data['id'],
                    'name': data['name'],
                    'fail_rate': fail_rate,
                    'fail_count': data['fail_count'],
                    'total_count': data['total_count']
                })
        
        # Sort by failure rate (highest first)
        problem_formulas.sort(key=lambda x: x['fail_rate'], reverse=True)
        
        # Get optimization opportunities (batches that took longer than average)
        optimization_opportunities = []
        
        if avg_production_time > 0:
            for batch in completed_batches:
                if batch.start_date and batch.end_date:
                    duration = (batch.end_date - batch.start_date).total_seconds() / 3600  # hours
                    
                    if duration > avg_production_time * 1.25:  # 25% longer than average
                        optimization_opportunities.append({
                            'id': batch.id,
                            'batch_number': batch.batch_number,
                            'formula_name': batch.formula.name,
                            'duration_hours': round(duration, 1),
                            'avg_duration_hours': avg_production_time,
                            'difference_percent': round((duration / avg_production_time - 1) * 100, 1)
                        })
        
        # Sort by difference percentage (highest first)
        optimization_opportunities.sort(key=lambda x: x['difference_percent'], reverse=True)
        
        # Assemble insights response
        insights_data = {
            'performance_metrics': {
                'avg_production_time_hours': avg_production_time,
                'quality_pass_rate': pass_rate,
                'batches_analyzed': len(completed_batches)
            },
            'quality_insights': {
                'problem_formulas': problem_formulas[:5],  # Top 5 problematic formulas
                'improvement_opportunity': pass_rate < 95  # Flag if pass rate is below 95%
            },
            'efficiency_insights': {
                'optimization_opportunities': optimization_opportunities[:5],  # Top 5 opportunities
                'improvement_potential': len(optimization_opportunities) > 0
            },
            'recommendations': []
        }
        
        # Generate recommendations based on insights
        if pass_rate < 95 and problem_formulas:
            insights_data['recommendations'].append({
                'type': 'quality',
                'priority': 'high',
                'title': 'Review Formula Quality Issues',
                'description': f'Investigate quality issues with {problem_formulas[0]["name"]} '
                               f'which has a failure rate of {problem_formulas[0]["fail_rate"]}%.'
            })
        
        if len(optimization_opportunities) > 0:
            insights_data['recommendations'].append({
                'type': 'efficiency',
                'priority': 'medium',
                'title': 'Optimize Production Time',
                'description': f'Batch {optimization_opportunities[0]["batch_number"]} took '
                               f'{optimization_opportunities[0]["difference_percent"]}% longer than average. '
                               f'Review production process for improvements.'
            })
        
        # Get material recommendations
        material_insights = self.get_material_insights()
        insights_data['material_insights'] = material_insights
        
        if material_insights['low_stock_count'] > 0:
            insights_data['recommendations'].append({
                'type': 'inventory',
                'priority': 'high' if material_insights['critical_stock_count'] > 0 else 'medium',
                'title': 'Reorder Raw Materials',
                'description': f'You have {material_insights["critical_stock_count"]} materials at '
                               f'critically low levels and {material_insights["low_stock_count"]} '
                               f'materials below reorder level.'
            })
        
        if material_insights['excess_stock_count'] > 0:
            insights_data['recommendations'].append({
                'type': 'inventory',
                'priority': 'low',
                'title': 'Reduce Excess Inventory',
                'description': f'You have {material_insights["excess_stock_count"]} materials with '
                               f'excess inventory. Consider adjusting order quantities.'
            })
        
        return Response(insights_data, status=status.HTTP_200_OK)
    
    def get_material_insights(self):
        """Helper method to get material inventory insights"""
        raw_materials = StockInventory.objects.filter(
            is_raw_material=True
        )
        
        low_stock = 0
        critical_stock = 0
        excess_stock = 0
        
        for material in raw_materials:
            if material.stock_level <= material.reorder_level:
                low_stock += 1
                if material.stock_level <= material.reorder_level / 2:
                    critical_stock += 1
            elif material.stock_level >= material.reorder_level * 3:  # More than 3x reorder level
                excess_stock += 1
        
        return {
            'total_materials': raw_materials.count(),
            'low_stock_count': low_stock,
            'critical_stock_count': critical_stock,
            'excess_stock_count': excess_stock
        }
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['date']
    ordering_fields = ['date']
    
    @action(detail=False, methods=['get'])
    def production_trends(self, request):
        """
        Get production trends using pandas for data analysis
        """
        days = int(request.query_params.get('days', 30))
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Get production data
        batches = ProductionBatch.objects.filter(
            end_date__date__range=[start_date, end_date],
            status='completed'
        ).values(
            'end_date__date', 'actual_quantity', 'formula__final_product__title',
            'labor_cost', 'overhead_cost'
        )
        
        if not batches:
            return Response([], status=status.HTTP_200_OK)
        
        # Convert to DataFrame using pandas
        df = pd.DataFrame(list(batches))
        df.rename(columns={
            'end_date__date': 'date',
            'formula__final_product__title': 'product'
        }, inplace=True)
        
        # Convert columns to appropriate types
        df['actual_quantity'] = pd.to_numeric(df['actual_quantity'], errors='coerce').fillna(0)
        df['labor_cost'] = pd.to_numeric(df['labor_cost'], errors='coerce').fillna(0)
        df['overhead_cost'] = pd.to_numeric(df['overhead_cost'], errors='coerce').fillna(0)
        
        # Group by date and product
        daily_production = df.groupby(['date', 'product']).agg({
            'actual_quantity': 'sum',
            'labor_cost': 'sum',
            'overhead_cost': 'sum'
        }).reset_index()
        
        daily_production.rename(columns={
            'actual_quantity': 'quantity'
        }, inplace=True)
        
        # Get raw material costs
        batch_materials = BatchRawMaterial.objects.filter(
            batch__end_date__date__range=[start_date, end_date],
            batch__status='completed'
        ).values(
            'batch__end_date__date', 'batch__formula__final_product__title',
            'cost'
        )
        
        material_df = pd.DataFrame(list(batch_materials))
        
        if not material_df.empty:
            material_df.rename(columns={
                'batch__end_date__date': 'date',
                'batch__formula__final_product__title': 'product',
                'cost': 'material_cost'
            }, inplace=True)
            
            # Convert to appropriate types
            material_df['material_cost'] = pd.to_numeric(material_df['material_cost'], errors='coerce').fillna(0)
            
            # Group by date and product
            material_costs = material_df.groupby(['date', 'product']).agg({
                'material_cost': 'sum'
            }).reset_index()
            
            # Merge dataframes
            result = pd.merge(
                daily_production, 
                material_costs, 
                on=['date', 'product'], 
                how='left'
            ).fillna(0)
        else:
            # No material costs data, add zero column
            result = daily_production.copy()
            result['material_cost'] = 0
        
        # Calculate total cost and unit cost
        result['total_cost'] = result['material_cost'] + result['labor_cost'] + result['overhead_cost']
        result['unit_cost'] = result.apply(lambda x: x['total_cost'] / x['quantity'] if x['quantity'] > 0 else 0, axis=1)
        
        # Convert date objects to strings for serialization
        result['date'] = result['date'].astype(str)
        
        # Convert to dict for JSON serialization
        return Response(result.to_dict('records'), status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def material_usage_analysis(self, request):
        """
        Analyze raw material usage patterns using pandas
        """
        days = int(request.query_params.get('days', 30))
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Get material usage data from production batches
        batch_materials = BatchRawMaterial.objects.filter(
            batch__created_at__date__range=[start_date, end_date]
        ).values(
            'batch__created_at__date', 'raw_material__product__title', 'raw_material_id',
            'planned_quantity', 'actual_quantity', 'cost',
            'batch__formula__final_product__title'
        )
        
        if not batch_materials:
            return Response({
                'material_summary': [],
                'product_usage': [],
                'daily_trends': []
            }, status=status.HTTP_200_OK)
        
        # Convert to DataFrame
        df = pd.DataFrame(list(batch_materials))
        df.rename(columns={
            'batch__created_at__date': 'date',
            'raw_material__product__title': 'raw_material',
            'batch__formula__final_product__title': 'product'
        }, inplace=True)
        
        # Handle null actual_quantity
        df['actual_quantity'] = df['actual_quantity'].fillna(df['planned_quantity'])
        
        # Convert columns to appropriate types
        df['actual_quantity'] = pd.to_numeric(df['actual_quantity'], errors='coerce').fillna(0)
        df['planned_quantity'] = pd.to_numeric(df['planned_quantity'], errors='coerce').fillna(0)
        df['cost'] = pd.to_numeric(df['cost'], errors='coerce').fillna(0)
        
        # Calculate efficiency
        df['efficiency'] = df.apply(lambda x: x['actual_quantity'] / x['planned_quantity'] 
                                  if x['planned_quantity'] > 0 else 1.0, axis=1)
        
        # Group by raw material - avoid including raw_material in agg function
        material_usage = df.groupby('raw_material').agg({
            'actual_quantity': 'sum',
            'cost': 'sum',
            'efficiency': 'mean'
        }).reset_index()
        
        # Count occurrences separately
        usage_counts = df.groupby('raw_material').size().reset_index(name='usage_count')
        
        # Merge the usage counts with the main aggregation
        material_usage = pd.merge(material_usage, usage_counts, on='raw_material', how='left')
        
        material_usage.rename(columns={
            'actual_quantity': 'total_usage',
            'cost': 'total_cost',
            'efficiency': 'avg_efficiency'
        }, inplace=True)
        
        # Add efficiency_std column (standard deviation of efficiency)
        efficiency_std = df.groupby('raw_material')['efficiency'].std().reset_index()
        efficiency_std.rename(columns={'efficiency': 'efficiency_std'}, inplace=True)
        
        # Merge with material_usage
        material_usage = pd.merge(material_usage, efficiency_std, on='raw_material', how='left')
        material_usage['efficiency_std'] = material_usage['efficiency_std'].fillna(0)
        
        # Group by product and raw material
        product_usage = df.groupby(['product', 'raw_material']).agg({
            'actual_quantity': 'sum',
            'cost': 'sum'
        }).reset_index()
        
        product_usage.rename(columns={
            'actual_quantity': 'usage'
        }, inplace=True)
        
        # Sort by total usage descending
        material_usage = material_usage.sort_values('total_usage', ascending=False)
        
        # Get top 5 raw materials by usage
        top_materials = material_usage.head(5)['raw_material'].tolist()
        
        # Get daily trend for top materials
        daily_trends = df[df['raw_material'].isin(top_materials)].groupby(['date', 'raw_material']).agg({
            'actual_quantity': 'sum'
        }).reset_index()
        
        daily_trends.rename(columns={
            'actual_quantity': 'usage'
        }, inplace=True)
        
        # Convert date objects to strings for serialization
        daily_trends['date'] = daily_trends['date'].astype(str)
        
        return Response({
            'material_summary': material_usage.to_dict('records'),
            'product_usage': product_usage.to_dict('records'),
            'daily_trends': daily_trends.to_dict('records')
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def predict_material_needs(self, request):
        """
        Predict future raw material needs using simple linear regression
        """
        days_history = int(request.query_params.get('days_history', 90))
        days_forecast = int(request.query_params.get('days_forecast', 30))
        
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days_history)
        
        # Get historical material usage - fixed to filter by date range
        batch_materials = BatchRawMaterial.objects.filter(
            batch__created_at__date__range=[start_date, end_date],
            batch__status='completed'
        ).values(
            'batch__created_at__date', 'raw_material__product__title',
            'raw_material_id', 'actual_quantity'
        )
        
        if not batch_materials:
            return Response({"detail": "Not enough historical data"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Convert to DataFrame
        df = pd.DataFrame(list(batch_materials))
        df.rename(columns={
            'batch__created_at__date': 'date',
            'raw_material__product__title': 'raw_material',
            'raw_material_id': 'material_id'
        }, inplace=True)
        
        # Fill missing values and convert to appropriate types
        df['actual_quantity'] = pd.to_numeric(df['actual_quantity'].fillna(0), errors='coerce').fillna(0)
        df['date'] = pd.to_datetime(df['date'])
        
        # Group by date and material - include unit information
        daily_usage = df.groupby(['date', 'raw_material', 'material_id']).agg({
            'actual_quantity': 'sum'
        }).reset_index()
        
        daily_usage.rename(columns={
            'actual_quantity': 'usage'
        }, inplace=True)
        
        # Sort by date
        daily_usage = daily_usage.sort_values('date')
        
        # Get unique materials with their units
        materials = StockInventory.objects.filter(
            id__in=daily_usage['material_id'].unique()
        ).values('id', 'product__title', 'unit__title')
        
        material_map = {m['id']: m for m in materials}
        
        # Prepare forecast results
        forecast_results = []
        
        # For each material, perform forecasting
        for material_id, group in daily_usage.groupby('material_id'):
            material_name = material_map.get(material_id, {}).get('product__title', 'Unknown')
            unit = material_map.get(material_id, {}).get('unit__title', 'units')
            
            # Prepare data for regression
            dates = group['date']
            usage = group['usage'].values
            
            # Convert dates to numeric (days since first date)
            first_date = dates.iloc[0]
            day_nums = np.array([(d - first_date).days for d in dates]).reshape(-1, 1)
            usage_array = np.array(usage)
            
            # Simple linear regression
            try:
                model = LinearRegression()
                model.fit(day_nums, usage_array)
                
                # Prepare forecast dates
                forecast_dates = [end_date + timedelta(days=i) for i in range(1, days_forecast + 1)]
                forecast_day_nums = np.array([(d - first_date).days for d in forecast_dates]).reshape(-1, 1)
                
                # Make predictions
                predictions = model.predict(forecast_day_nums)
                predictions = np.maximum(predictions, 0)  # Ensure no negative predictions
                
                # Calculate confidence interval (simple version)
                residuals = usage_array - model.predict(day_nums)
                stdev = np.std(residuals)
                upper_bound = predictions + 1.96 * stdev  # 95% CI
                lower_bound = np.maximum(predictions - 1.96 * stdev, 0)
                
                # Format results
                material_forecast = {
                    'material': material_name,
                    'material_id': material_id,
                    'unit': unit,
                    'coefficient': float(model.coef_[0]),
                    'intercept': float(model.intercept_),
                    'forecast': [
                        {
                            'date': date.isoformat(),
                            'predicted_usage': float(pred),
                            'upper_bound': float(upper),
                            'lower_bound': float(lower)
                        }
                        for date, pred, upper, lower in zip(forecast_dates, predictions, upper_bound, lower_bound)
                    ],
                    'total_predicted_usage': float(sum(predictions)),
                    'average_daily_usage': float(np.mean(usage)),
                    'confidence_interval': float(stdev)
                }
                
                forecast_results.append(material_forecast)
            except Exception as e:
                print(f"Error forecasting for material {material_id}: {str(e)}")
                continue
        
        # Get current inventory levels
        material_ids = [item['material_id'] for item in forecast_results]
        inventory = StockInventory.objects.filter(id__in=material_ids).select_related('product', 'unit')
        
        inventory_dict = {item.id: item for item in inventory}
        
        # Add inventory status to results
        for result in forecast_results:
            material_id = result['material_id']
            inventory_item = inventory_dict.get(material_id)
            
            if inventory_item:
                current_level = inventory_item.stock_level
                reorder_level = inventory_item.reorder_level
                predicted_usage = result['total_predicted_usage']
                
                result['current_inventory'] = current_level
                result['reorder_level'] = reorder_level
                result['predicted_shortage'] = max(0, predicted_usage - current_level)
                
                # Calculate days until shortage
                avg_daily = result['average_daily_usage']
                if avg_daily > 0:
                    days_until_shortage = int(current_level / avg_daily)
                    # Adjust for confidence interval (conservative estimate)
                    days_until_shortage = int(current_level / (avg_daily + result['confidence_interval']))
                else:
                    days_until_shortage = 999
                
                result['days_until_shortage'] = days_until_shortage
                result['reorder_needed'] = days_until_shortage < days_forecast
                
                # Determine status
                if current_level <= reorder_level / 2:
                    result['status'] = 'Critical'
                elif current_level <= reorder_level:
                    result['status'] = 'Low Stock'
                else:
                    result['status'] = 'Sufficient'
        
        # Sort by urgency (days until shortage)
        forecast_results.sort(key=lambda x: x['days_until_shortage'])
        
        return Response(forecast_results, status=status.HTTP_200_OK)
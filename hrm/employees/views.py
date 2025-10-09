from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from django.utils import timezone

from crm.contacts.utils import ImportContacts
from ecommerce.product.functions import ImportProducts
from .serializers import *
from hrm.payroll_settings.serializers import *
from hrm.payroll_settings.models import *
from hrm.payroll.serializers import *
from hrm.payroll.models import *
from hrm.employees.models import *
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


class UploadEmployData(APIView):
    permission_classes=[IsAuthenticated]

    @csrf_exempt
    def post(self, request, format=None):
        organisation=Bussiness.objects.filter(Q(owner=self.request.user)|Q(employees__user=self.request.user)).first()
        if organisation is None:
            return Response({'error': "No Company or Business Details found. Please register company details before importing employees"}, status=status.HTTP_400_BAD_REQUEST)
        if 'file' not in request.FILES:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)
        file_obj = request.FILES['file']
        fileType = request.data.get('fileType')
        # Save the uploaded file
        file_name = default_storage.save(file_obj.name, ContentFile(file_obj.read()))
        # Call the import_employee_data function
        #try:
        path=default_storage.path(file_name)
        import_response = EmployeeDataImport(path=path,request=request).import_employee_data()
        if fileType =='products':
            res = ImportProducts(request,path,organisation).save_product()
            if fileType =='contacts':
               res = ImportContacts(request,path,organisation).save_contact()
        return Response({'message': import_response}, status=status.HTTP_201_CREATED)
        # except Exception as e:
        #     return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class EmployeeViewSet(viewsets.ModelViewSet):#cruds
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    #serializer_class = PersonalDataSerializer
    permission_classes=[IsAuthenticated]
    pagination_class = PageNumberPagination  # Enable pagination

    def get_queryset(self):
        queryset = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id',None)
        employement_type = self.request.query_params.getlist('employement_type', None)
        contract_start_date = self.request.query_params.get("contract_start_date", None)
        contract_end_date = self.request.query_params.get("contract_end_date", None)
        department_ids = self.request.query_params.getlist("department[]", None)
        region_ids = self.request.query_params.getlist("region[]", None)
        employee_ids = self.request.query_params.getlist("employee_ids[]", None)

        if branch_id:
           queryset = queryset.filter(branch__branch_id=branch_id)
        if not self.request.user.is_superuser:
            orgs=Bussiness.objects.filter(Q(owner=self.request.user)|Q(id=getattr(getattr(self.request.user, "employee", None), "organisation_id", None)))
            queryset = queryset.filter(Q(organisation__in=orgs)) 
        
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
        
        if department_ids:
            queryset = queryset.filter(hr_details__department_id__in=department_ids)
        if region_ids:
            queryset = queryset.filter(hr_details__region_id__in=region_ids)
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
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        deduction_id = request.query_params.get("deduction", None)
        emp_id = request.query_params.get("emp_id", None)

        # Apply filters dynamically
        deductions = self.get_queryset()
        if emp_id:
            deductions = deductions.filter(employee__id=emp_id)
        if department_ids:
            deductions = deductions.filter(employee__hr_details__department__id__in=department_ids)
        if region_ids:
            deductions = deductions.filter(employee__hr_details__region__id__in=region_ids)
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
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        earning_id = request.query_params.get("earning", None)
        emp_id = request.query_params.get("emp_id", None)

        # Apply filters dynamically
        earnings = self.get_queryset()
        if emp_id:
            earnings = earnings.filter(employee__id=emp_id)
        if department_ids:
            earnings = earnings.filter(employee__hr_details__department__id__in=department_ids)
        if region_ids:
            earnings = earnings.filter(employee__hr_details__region__id__in=region_ids)
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
        department_ids = request.query_params.getlist("department[]", None)
        region_ids = request.query_params.getlist("region[]", None)
        emp_id = request.query_params.get("emp_id", None)

        # Apply filters dynamically
        queryset = self.get_queryset()
        if emp_id:
            queryset = queryset.filter(employee__id=emp_id)
        if department_ids:
            queryset = queryset.filter(department__id__in=department_ids)
        if region_ids:
            queryset = queryset.filter(region__id__in=region_ids)
        
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

    @action(detail=True, methods=['patch'], url_path='renew')
    def renew(self, request, pk=None):
        """
        Renew an existing contract
        """
        contract = self.get_object()
        if contract.status == 'expired':
            new_end_date = datetime.now().date() + timedelta(days=int(request.data.get('days', 365)))  # Default renewal period is 1 year
            contract.contract_end_date = new_end_date
            contract.status = 'active'  # Renew the contract to active status
            contract.save()
            return Response({"status": f"Contract renewed until {new_end_date}."})
        return Response({"error": "Contract is not expired and cannot be renewed."}, status=status.HTTP_400_BAD_REQUEST)

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

class ContactDetailsViewSet(viewsets.ModelViewSet):
    queryset = ContactDetails.objects.all()
    serializer_class = ContactDetailsSerializer
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

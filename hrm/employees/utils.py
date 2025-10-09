import pandas as pd
from datetime import datetime, timedelta
from django.utils.timezone import make_aware
from authmanagement.models import CustomUser
from django.db import transaction
from django.db.models import Q

from business.models import *
from .models import Contract, Employee, SalaryDetails,HRDetails, ContactDetails, NextOfKin, JobTitle, EmployeeBankAccount
from core.models import *
from django.contrib.auth.models import Group
import re
import random

class EmployeeDataImport:
    def __init__(self,request,path,organisation) -> None:
        self.path=path
        self.request=request
        self.organisation=organisation

    def format_phone_number(self, phone):
        # Remove all non-digit characters
        phone = re.sub(r'\D', '', phone)
        
        # Check if the phone starts with '254' or '0', otherwise, prepend '254'
        if phone.startswith('0'):
            phone = '254' + phone[1:]
        elif not phone.startswith('254'):
            phone = '254' + phone
        
        # Ensure the phone number has 12 digits, add leading zeros if necessary
        if len(phone) == 12 and not phone.startswith("+"):
            return '+' + phone
        elif len(phone) < 12:
            # If phone number is shorter than 12 digits, pad with zeros
            return phone+("X"*(12-len(phone)))  # Pad the phone number to ensure it's 9 digits long after '254'
        
        # If the phone number has more than 12 digits, return an empty string or raise an error
        raise ValueError(f"Invalid phone number: {phone}")

    def format_date(self,date_str):
        try:
            # Attempt to parse the date
            date_obj = datetime.strptime(date_str, '%d/%m/%Y')
            # Format the date as YYYY-MM-DD
            formatted_date = date_obj.strftime('%Y-%m-%d')
            return formatted_date
        except Exception as e:
            # Handle invalid date format
            return str(f"Date Format Error:{e}")
        
    def contract_duration(self,duration):
        try:
            total_years=0.3
            if 'y' in str(duration):
                # Split the duration string into years and months parts
                parts = str(duration).split('y')
                years = int(parts[0]) if parts[0] else 0
                months = 0

                if len(parts) > 1:
                    # Extract the months part if present
                    months_str = parts[1].split('m')[0]
                    months = int(months_str) if months_str else 0
            else:
                # If only months are provided
                years = 0
                months_str = str(duration).split('m')[0]
                months = int(months_str) if months_str else 0
                total_years = years + months / 12
                # Convert the duration to years
            return float(f"{total_years:.1f}")  # Format to 1 decimal place
        except Exception as e:
            return str(f"Contact Duration extract error:{e}")
    # Function to map CSV type to employment_type_choices
    def map_employment_type(self,emp_type:str):
        # Normalize the input by removing spaces and converting to lowercase
        normalized_type = emp_type.replace(" ", "").replace("-", "").lower()
        
        # Map the normalized type to the choices
        if normalized_type == "regular(fixedterm)":
            return "regular-fixed"
        elif normalized_type == "regular(openended)":
            return "regular-open"
        elif normalized_type in ["intern", "probationary", "casual", "consultant"]:
            return normalized_type
        else:
            return None  
        
    def import_employee_data(self):
        try:
            with transaction.atomic():
                # Read the CSV/XLS/XLSX file into a pandas DataFrame
                if 'csv' not in self.path:
                    return "Please select a csv file!"
                
                df = pd.read_csv(self.path, dtype={'Emp. Date': str})       
                # Fill NaN values in 'Contract Exp.(Days)' column with 0
                df['Contract Exp.(Days)'].fillna(0, inplace=True)
                df['Date of Birth'].fillna(datetime.now()-timedelta(days=8760), inplace=True)#24yrs back
                df['Phone'].fillna("+254700000001",inplace=True)
                df['Gender'].fillna("other",inplace=True)
                df['Email(Personal)'].fillna(df['Email'].map(lambda x:str(x)+str(random.randint(0,100))), inplace=True)
                df['Email'].fillna(df['Name'].map(lambda x: str(x).lower().replace(" ","")+"@example.com"), inplace=True)                
                df['NHIF'].fillna("N/A",inplace=True)
                df['ID'].fillna(df['PIN'],inplace=True)
                df['NSSF'].fillna("N/A",inplace=True)
                df['Emp. Duration'].fillna("3m",inplace=True)
                # Convert 'Emp. Date' column to datetime format with the correct format
                df['Emp. Date'] = pd.to_datetime(df['Emp. Date'], format='%d/%m/%Y')
                # Extract date part only
                df['Emp. Date'] = df['Emp. Date'].dt.date
                # Calculate 'Contract Exp. Date' based on 'Emp. Date' and 'Contract Exp.(Days)'
                df['Contract Exp. Date'] = pd.to_datetime(datetime.now()) - pd.to_timedelta(df['Contract Exp.(Days)'], unit='D')
                df['Contract Exp. Date'] = pd.to_datetime(df['Contract Exp. Date'], format='%d/%m/%Y')
                # Remove commas from the basic pay column
                df['Basic Pay'] = df['Basic Pay'].str.replace(',', '')
                # Convert the Basic Pay column to floats
                df['Basic Pay'] = df['Basic Pay'].astype(float)
                print( df['Basic Pay'])
                df['Contract Exp.(Days)']=df['Contract Exp.(Days)'].astype(int)

                for index, row in df.iterrows():
                    try:
                        # Create or get CustomUser instance
                        first_name=""
                        last_name=""
                        middle_name=""
                        full_name=str(row['Name']).strip()
                        if len(full_name.split()) >=3:
                            first_name=full_name.split(" ")[0]
                            last_name=full_name.split(" ")[2]
                            middle_name=full_name.split(" ")[1]
                        else:
                            first_name=full_name.split(" ")[0]
                            last_name=full_name.split(" ")[1]
                            middle_name=""
                        email=row['Email']
                        if email !=None:
                            email=row['Email'] 
                        else:
                            email=first_name+str(index)+"@gmail.com"
                            row['Email(Personal)']=email
                        user, created= CustomUser.objects.update_or_create(
                            email=email,
                            defaults={
                            "password":"User@123",
                            "first_name":first_name,
                            "middle_name":middle_name,
                            "last_name":last_name,
                            "is_staff":True,
                            "is_active":True
                            })
                    except Exception as e:
                        print("user error:"+str(e))
                    try:
                        group,created=Group.objects.update_or_create(name="staff")
                        user.groups.add(group)
                        user.save()

                        # Create or update Employee instance
                        my_dob=pd.to_datetime(row['Date of Birth']).strftime("%d/%m/%Y")
                        dob=self.format_date(my_dob)
                        employee, _ = Employee.objects.update_or_create(
                        user=user,
                        organisation=self.organisation,
                        defaults={
                        "gender":row['Gender'],
                        "date_of_birth":dob,
                        "residential_status":'Resident',  # Fill with appropriate value
                        "national_id": str(row['ID']).strip(".0"),
                        "pin_no": row['PIN'],
                        "nhif_no":row['NHIF'],
                        "nssf_no": row['NSSF'],
                        })
                    except Exception as e:
                        print("employee create error:"+str(e))
                    # Create or update BankInstitution and BankBranches
                    bank_institution, created = BankInstitution.objects.update_or_create(
                        name=row['Bank'],
                        defaults={
                            "code": str(row['Bank Code'])[:3].upper(),
                            "short_code": str(row['Bank Code'])[:3].upper(),
                            "swift_code": f"{str(row['Bank'])[:4].upper()}KENA",
                            "country": "Kenya",
                            "is_active": True
                        }
                    )
                    
                    bank_branch, created = BankBranches.objects.update_or_create(
                        bank=bank_institution,
                        code=str(row['Bank Code'])[-2:],
                        defaults={
                            "name": row['Bank Branch'],
                            "address": "Nairobi CBD",
                            "phone": "+254700000000",
                            "email": f"nairobi@{row['Bank'].lower().replace(' ', '')}.com",
                            "is_active": True
                        }
                    )
                    try:
                      mobile_number=self.format_phone_number(str(row['Phone']).strip(".0"))
                    except Exception as e:
                        print("mobile number error:"+str(e))

                    # Create EmployeeBankAccount
                    employee_bank_account, created = EmployeeBankAccount.objects.update_or_create(
                        employee=employee,
                        bank_institution=bank_institution,
                        account_number=str(row['Bank Acc']).strip(".0"),
                        defaults={
                            'bank_branch': bank_branch,
                            'account_name': f"{first_name} {last_name}",
                            'account_type': 'savings',
                            'is_primary': True,
                            'status': 'active',
                            'is_verified': True,
                            'opened_date': datetime.now().date()
                        }
                    )

                    basic_salary=float(row['Basic Pay'])
                    salary_details, _ = SalaryDetails.objects.update_or_create(
                        employee=employee,
                        defaults={
                            'employment_type': self.map_employment_type(row['Type']),
                            'monthly_salary': basic_salary,
                            'pay_type': "gross",
                            'work_hours': 8,
                            'hourly_rate': None,
                            'daily_rate': None,
                            'income_tax': "primary",
                            'deduct_nssf': True,
                            'tax_excemption_amount': None,
                            'payment_type': "bank",
                            'bank_account': employee_bank_account,
                            'mobile_number': mobile_number
                        })
                    # Create or update HRDetails instance
                    try:
                       dept_title=str(row['Dept.']).strip()
                    except Exception as e:
                        print(row['Dept.']+" => "+str(e))
                    code=f"00{index+1}"
                    job_title=row['Job Title']
                    try:
                       region=str(row['Region']).strip()
                    except Exception as e:
                        print(str(row['Region'])+" => "+str(e))
                    region, created= Regions.objects.update_or_create(
                        defaults={"code":code},
                        name=row['Region'] if region !="nan" else "Head Office"
                        )
                    department, created = Departments.objects.update_or_create(
                        title=dept_title if dept_title !="nan" else "General",
                        defaults={
                        "parent_departyment":None,
                        "code":code,
                        })            
                    job_title,_= JobTitle.objects.update_or_create(
                        title=job_title,
                    )
                    emp_date=pd.to_datetime(row['Emp. Date']).strftime("%d/%m/%Y")
                    emp_date=self.format_date(emp_date)
                    end_date=pd.to_datetime(row['Contract Exp. Date']).strftime("%d/%m/%Y")
                    end_date=self.format_date(end_date)
                    duration=self.contract_duration(str(row['Emp. Duration']))
                    hr_details, created = HRDetails.objects.update_or_create(
                    employee=employee,
                    defaults={
                        'job_or_staff_number': re.sub(r'[^\w\s]', '', row['Staff No']),  # clean value
                        'job_title': job_title,
                        'department': department,
                        'head_of': None, 
                        'reports_to': None,  
                        'region': region,
                        'project': None, 
                        'date_of_employment': emp_date,
                        'board_director': False  
                    })
                    contract,created=Contract.objects.update_or_create(
                        employee=employee,
                        defaults={
                        'status': 'active' if datetime.strptime(end_date, '%Y-%m-%d')>datetime.now() else 'expired',
                        'contract_start_date': emp_date,
                        'contract_end_date': end_date,
                        'salary': basic_salary,
                        'pay_type': "gross",
                        'contract_duration': duration,
                    })
                    # Create or update ContactDetails instance
                    try:
                       mobile_phone=self.format_phone_number(str(row['Phone']).strip(".0"))
                       official_phone=self.format_phone_number(str(row['Phone']).strip(".0"))
                    except Exception as e:
                        print("contacts error:"+str(e))
                    print(mobile_phone,official_phone)
                    contact_details, created = ContactDetails.objects.update_or_create(
                        employee=employee,
                        defaults={
                            'personal_email': row['Email(Personal)'],
                            'country': 'KE',
                            'county': row['Region'], 
                            'city': row['Region'],
                            'zip': '00100',
                            'address': '1234 street', 
                            'mobile_phone': mobile_phone,
                            'official_phone':official_phone,
                        })
                    # Create or update NextOfKin instance
                    next_of_kin, created= NextOfKin.objects.update_or_create(employee=employee)
                    next_of_kin.name = f'kin {index+1}'  
                    next_of_kin.relation = 'relation' 
                    next_of_kin.phone = "+254700000001"  #
                    next_of_kin.email = 'kinemail'+str(index)+"@gmail.com" 
                    next_of_kin.save()
                    print(f"Successfully imported Employee {index}:{employee.user.email}")
                return f"Successfully imported {len(df)} employee records!"  # Return the number of records imported
        except Exception as e:
            return str(e)

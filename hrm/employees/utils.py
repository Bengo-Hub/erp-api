import pandas as pd
from datetime import datetime, timedelta
from django.utils.timezone import make_aware
from authmanagement.models import CustomUser
from django.db import transaction
from django.db.models import Q
from django.contrib.auth.models import Group

from business.models import *
from .models import Contract, Employee, SalaryDetails,HRDetails, ContactDetails, NextOfKin, JobTitle, EmployeeBankAccount
from core.models import *
from hrm.attendance.models import WorkShift
import re
import random
import calendar

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
            d = str(duration).strip().lower()
            if 'y' in d:
                # Split the duration string into years and months parts
                parts = d.split('y')
                years = int(parts[0]) if parts[0] else 0
                months = 0

                if len(parts) > 1:
                    # Extract the months part if present
                    months_str = parts[1].split('m')[0]
                    months = int(months_str) if months_str else 0
                total_years = years + months / 12
            else:
                # If only months are provided
                years = 0
                months_str = d.split('m')[0]
                months = int(months_str) if months_str else 0
                total_years = years + months / 12
                # Convert the duration to years
            return float(f"{total_years:.1f}")  # Format to 1 decimal place
        except Exception as e:
            return str(f"Contact Duration extract error:{e}")
    # Function to map CSV type to employment_type_choices
    def map_employment_type(self,emp_type:str):
        # Normalize the input by removing spaces and converting to lowercase
        if not emp_type:
            return None
        normalized_type = str(emp_type).strip().replace(" ", "").replace("-", "").lower()
        
        # Map the normalized type to the choices
        if normalized_type in ("regular(fixedterm)", "regularfixed", "regular-fixed"):
            return "regular-fixed"
        elif normalized_type in ("regular(openended)", "regularopen", "regular-open"):
            return "regular-open"
        elif normalized_type in ["intern", "probationary", "casual", "consultant"]:
            return normalized_type
        else:
            return None  

    def parse_duration_to_ym(self, duration: str):
        """Parse duration like '10y0m', '2y6m', '6m' into (years, months)."""
        try:
            if not duration:
                return 0, 0
            d = str(duration).strip().lower()
            years = 0
            months = 0
            if 'y' in d:
                parts = d.split('y')
                years = int(parts[0]) if parts[0] else 0
                if len(parts) > 1 and 'm' in parts[1]:
                    m = parts[1].split('m')[0]
                    months = int(m) if m else 0
            elif 'm' in d:
                months = int(d.split('m')[0] or 0)
            return years, months
        except Exception:
            return 0, 0

    def add_years_months(self, date_obj, years: int, months: int):
        """Add years and months to a date, clamping days to month-end when necessary."""
        try:
            total_months = date_obj.month - 1 + months + (years * 12)
            new_year = date_obj.year + total_months // 12
            new_month = (total_months % 12) + 1
            last_day = calendar.monthrange(new_year, new_month)[1]
            new_day = min(date_obj.day, last_day)
            return date_obj.replace(year=new_year, month=new_month, day=new_day)
        except Exception:
            # Fallback approximation
            return date_obj + timedelta(days=(years * 365) + (months * 30))

    def map_role_group_by_job_title(self, title: str) -> str:
        """
        Enhanced role mapping based on job title
        Maps job titles to appropriate RBAC groups for permission management
        """
        if not title:
            return 'staff'
        
        t = str(title).strip().lower()
        
        # Executive Level
        if any(x in t for x in ['chief executive', 'ceo', 'managing director', 'md']):
            return 'ceo'
        if any(x in t for x in ['chief financial', 'cfo', 'finance director']):
            return 'cfo'
        if any(x in t for x in ['chief technology', 'cto', 'it director']):
            return 'cto'
        if any(x in t for x in ['chief operating', 'coo', 'operations director']):
            return 'coo'
        
        # Management Level
        if 'manager' in t:
            if any(x in t for x in ['hr', 'human resource', 'people']):
                return 'hr_manager'
            if any(x in t for x in ['finance', 'accounting', 'accounts']):
                return 'finance_manager'
            if any(x in t for x in ['sales', 'business development']):
                return 'sales_manager'
            if any(x in t for x in ['procurement', 'purchasing', 'supply chain']):
                return 'procurement_manager'
            if any(x in t for x in ['ict', 'it', 'technology']):
                return 'ict_manager'
            if any(x in t for x in ['operations', 'production']):
                return 'operations_manager'
            return 'manager'  # Generic manager
        
        # Specialized Roles
        if any(x in t for x in ['accountant', 'accounts officer', 'finance officer']):
            return 'accountant'
        if any(x in t for x in ['hr officer', 'hr assistant', 'human resource officer']):
            return 'hr_officer'
        if any(x in t for x in ['procurement officer', 'purchasing officer']):
            return 'procurement_officer'
        if any(x in t for x in ['sales officer', 'sales executive', 'sales rep']):
            return 'sales_officer'
        if any(x in t for x in ['ict officer', 'it officer', 'system admin', 'developer']):
            return 'ict_officer'
        if any(x in t for x in ['receptionist', 'front desk']):
            return 'receptionist'
        if any(x in t for x in ['secretary', 'admin assistant', 'personal assistant']):
            return 'secretary'
        if any(x in t for x in ['driver', 'chauffeur']):
            return 'driver'
        if any(x in t for x in ['security', 'guard']):
            return 'security'
        if any(x in t for x in ['cleaner', 'janitor', 'housekeeper']):
            return 'support_staff'
        
        # Default
        return 'staff'
        
    def import_employee_data(self):
        try:
            with transaction.atomic():
                # Read the CSV/XLS/XLSX file into a pandas DataFrame
                path_lower = str(self.path).lower()
                if path_lower.endswith('.csv'):
                    df = pd.read_csv(self.path, dtype=str, keep_default_na=False, na_values=['', 'NA', 'NaN'])
                elif path_lower.endswith('.xlsx') or path_lower.endswith('.xls'):
                    try:
                        df = pd.read_excel(self.path, dtype=str)
                    except Exception as e:
                        return f"Excel import requires openpyxl/xlrd installed: {e}"
                else:
                    return "Unsupported file type. Please upload a .csv, .xls, or .xlsx file."

                # Normalize and coerce core columns
                df['Contract Exp.(Days)'] = pd.to_numeric(df.get('Contract Exp.(Days)', 0), errors='coerce').fillna(0).astype(int)

                # Dates
                df['Emp. Date'] = pd.to_datetime(df.get('Emp. Date'), format='%d/%m/%Y', errors='coerce')
                df['Date of Birth'] = pd.to_datetime(df.get('Date of Birth'), errors='coerce')
                default_dob = datetime.now() - timedelta(days=24 * 365)
                df['Date of Birth'] = df['Date of Birth'].fillna(default_dob)

                # Phones and emails
                df['Phone'] = df.get('Phone', '').fillna("+254700000001")
                df['Gender'] = df.get('Gender', '').fillna("other").map(lambda g: str(g).strip().lower() if g else 'other')
                df['Email'] = df.get('Email', '').fillna(df['Name'].map(lambda x: str(x).lower().replace(" ","") + "@example.com"))
                df['Email(Personal)'] = df.get('Email(Personal)', '').fillna(
                    df['Email'].map(lambda x: str(x).split('@')[0] + str(random.randint(0,100)) + "@example.com")
                )
                df['NHIF'] = df.get('NHIF', '').fillna("N/A")
                df['ID'] = df.get('ID', '').fillna(df.get('PIN', ''))
                df['NSSF'] = df.get('NSSF', '').fillna("N/A")
                df['Emp. Duration'] = df.get('Emp. Duration', '').fillna("3m")

                # Basic Pay: remove commas and coerce to float
                df['Basic Pay'] = pd.to_numeric(
                    df.get('Basic Pay', '0').astype(str).str.replace(',', ''),
                    errors='coerce'
                ).fillna(0.0)

                # Contract end date: prefer Emp. Date + Contract Exp.(Days); else will be computed later
                emp_date_series = df['Emp. Date'].fillna(datetime.now())
                df['Contract Exp. Date'] = emp_date_series + pd.to_timedelta(df['Contract Exp.(Days)'], unit='D')

                # Helper to normalize blank/nan-like strings
                def _is_blank(val):
                    try:
                        v = str(val).strip()
                    except Exception:
                        return True
                    vlow = v.lower()
                    return (v == '' or vlow in ('nan', 'none', 'null', '-', '--'))

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
                        email=row['Email'] if row['Email'] else (first_name+str(index)+"@example.com")
                        if not row['Email(Personal)']:
                            row['Email(Personal)']=email
                        user, created= CustomUser.objects.update_or_create(
                            email=email,
                            defaults={
                            "first_name":first_name,
                            "middle_name":middle_name,
                            "last_name":last_name,
                            "is_staff":True,
                            "is_active":True
                            })
                        try:
                            if created:
                                # Set default password and force password change on first login
                                user.set_password("ChangeMe123!")
                                user.must_change_password = True
                                user.save()
                                
                                # Send welcome email with credentials
                                from hrm.employees.services.ess_utils import send_welcome_email
                                send_welcome_email(employee, "ChangeMe123!")
                                print(f"✅ User account created for {user.email} with temporary password")
                        except Exception as e:
                            print(f"❌ Error setting password or sending email: {e}")
                    except Exception as e:
                        print("user error:"+str(e))
                    try:
                        # Assign role group based on job title; always include 'staff'
                        mapped_role = self.map_role_group_by_job_title(str(row['Job Title']))
                        role_group, _ = Group.objects.get_or_create(name=mapped_role)
                        staff_group, _ = Group.objects.get_or_create(name='staff')
                        user.groups.add(staff_group)
                        if role_group.name != 'staff':
                            user.groups.add(role_group)
                        user.save()

                        # Create or update Employee instance
                        dob_dt = pd.to_datetime(row['Date of Birth'], errors='coerce')
                        dob = dob_dt.date().isoformat() if pd.notna(dob_dt) else None
                        gender_val = str(row['Gender']).strip().lower() if row['Gender'] else 'other'
                        if gender_val not in ('male', 'female', 'other'):
                            gender_val = 'other'
                        employee, _ = Employee.objects.update_or_create(
                        user=user,
                        organisation=self.organisation,
                        defaults={
                        "gender":gender_val,
                        "date_of_birth":dob,
                        "residential_status":'Resident',  # Fill with appropriate value
                        "national_id": str(row['ID']).strip(),
                        "pin_no": row['PIN'],
                        "shif_or_nhif_number": row['NHIF'],
                        "nssf_no": row['NSSF'],
                        "allow_ess": True,
                        })
                    except Exception as e:
                        print("employee create error:"+str(e))
                    # Create or update BankInstitution and BankBranches
                    bank_name_raw = str(row.get('Bank','') or '').strip()
                    bank_code_raw = str(row.get('Bank Code','') or '').strip()
                    bank_name = '' if _is_blank(bank_name_raw) else bank_name_raw
                    bank_code_clean = '' if _is_blank(bank_code_raw) else bank_code_raw
                    # Prefer explicit code; else derive from bank name; else unique fallback
                    base_code = bank_code_clean[:3].upper() if bank_code_clean else (re.sub(r'[^A-Za-z0-9]', '', bank_name)[:3].upper() if bank_name else '')
                    derived_code = base_code if base_code else f"BNK{index+1:03d}"
                    bank_institution, created = BankInstitution.objects.update_or_create(
                        code=derived_code,
                        defaults={
                            "name": bank_name or f"Bank {derived_code}",
                            "short_code": derived_code,
                            "swift_code": f"{((bank_name[:4] if bank_name else derived_code[:4]) or 'BANK').upper()}KENA",
                            "country": "Kenya",
                            "is_active": True
                        }
                    )
                    
                    branch_code = (bank_code_clean[-2:] if len(bank_code_clean) >= 2 else f"{index+1:02d}")
                    branch_name_raw = str(row.get('Bank Branch','') or '').strip()
                    branch_name = branch_name_raw if not _is_blank(branch_name_raw) else 'Main'
                    bank_branch, created = BankBranches.objects.update_or_create(
                        bank=bank_institution,
                        code=branch_code,
                        defaults={
                            "name": branch_name,
                            "address": "Nairobi CBD",
                            "phone": "+254700000000",
                            "email": f"nairobi@{(bank_name or 'bank').lower().replace(' ', '')}.com",
                            "is_active": True
                        }
                    )
                    try:
                      mobile_number=self.format_phone_number(str(row['Phone']))
                    except Exception as e:
                        print("mobile number error:"+str(e))

                    # Create EmployeeBankAccount
                    account_number_clean = re.sub(r'\D', '', str(row.get('Bank Acc','') or ''))
                    employee_bank_account, created = EmployeeBankAccount.objects.update_or_create(
                        employee=employee,
                        bank_institution=bank_institution,
                        account_number=account_number_clean,
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

                    basic_salary=float(row['Basic Pay']) if row['Basic Pay'] is not None else 0.0
                    salary_details, _ = SalaryDetails.objects.update_or_create(
                        employee=employee,
                        defaults={
                            'employment_type': self.map_employment_type(row.get('Type','')),
                            'monthly_salary': basic_salary,
                            'pay_type': "gross",
                            'work_hours': 8,
                            # Assign Regular Shift by default
                            'work_shift': WorkShift.objects.get_or_create(
                                name='Regular Shift',
                                defaults={'grace_minutes': 15, 'total_hours_per_week': 40.00}
                            )[0],
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
                       dept_title=str(row.get('Dept.','') or '').strip()
                    except Exception as e:
                        print(str(row.get('Dept.',''))+" => "+str(e))
                    code=f"00{index+1}"
                    job_title=row.get('Job Title','Staff')
                    try:
                       region=str(row.get('Region','') or '').strip()
                    except Exception as e:
                        print(str(row.get('Region',''))+" => "+str(e))
                    region, created= Regions.objects.update_or_create(
                        defaults={"code":code},
                        name=row.get('Region') if region !="nan" else "Head Office"
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
                    # Determine employment and end dates
                    emp_date_dt = pd.to_datetime(row['Emp. Date'], errors='coerce')
                    emp_date = (emp_date_dt.date().isoformat() if pd.notna(emp_date_dt) else datetime.now().date().isoformat())
                    # Compute end date: prefer Emp. Date + Emp. Duration (years/months). Fallback to explicit exp date, then days.
                    end_date = None
                    if pd.notna(emp_date_dt):
                        y, m = self.parse_duration_to_ym(row.get('Emp. Duration', ''))
                        if y or m:
                            computed = self.add_years_months(emp_date_dt.date(), y, m)
                            end_date = computed.isoformat()
                    if not end_date:
                        exp_dt = pd.to_datetime(row.get('Contract Exp. Date'), errors='coerce')
                        if pd.notna(exp_dt):
                            end_date = exp_dt.date().isoformat()
                        else:
                            try:
                                end_date = (emp_date_dt + timedelta(days=int(row.get('Contract Exp.(Days)', 0) or 0))).date().isoformat()
                            except Exception:
                                end_date = (emp_date_dt + timedelta(days=90)).date().isoformat()
                    duration=self.contract_duration(str(row.get('Emp. Duration','3m')))
                    # Resolve a default branch for this organisation (main branch or first available)
                    try:
                        from business.models import Branch
                        main_branch = Branch.objects.filter(business=self.organisation, is_main_branch=True).first()
                        if main_branch is None:
                            main_branch = Branch.objects.filter(business=self.organisation).order_by('id').first()
                    except Exception:
                        main_branch = None
                    hr_details, created = HRDetails.objects.update_or_create(
                    employee=employee,
                    defaults={
                        'job_or_staff_number': re.sub(r'[^\w\s]', '', row['Staff No']),  # clean value
                        'job_title': job_title,
                        'department': department,
                        'head_of': None, 
                        'reports_to': None,  
                        'region': region,
                        'branch': main_branch,
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
                       mobile_phone=self.format_phone_number(str(row['Phone']))
                       official_phone=self.format_phone_number(str(row['Phone']))
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

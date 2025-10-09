import pandas as pd
from datetime import datetime
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import CustomerGroup, Contact, ContactAccount
from business.models import Branch,Bussiness
from decimal import Decimal
import re

User=get_user_model()

class ImportContacts:
    def __init__(self,request,filePath,business):
       self.filePath=filePath
       self.biz=business
       self.request=request
    
    def clean_money_cols(self,money_string:str):
        # Remove non-numeric characters from the money string
        if money_string =='No Limit':
            return None
        cleaned_money = money_string.strip().replace('KSh', '').replace(',', '')
        # Convert the cleaned money string to Decimal format
        decimal_money = Decimal(cleaned_money)
        return decimal_money
    
    def get_contact_name(self,name:str):
        account_type='Individual'
         #get contact name
        names=name.split(' ')
        fname=''
        lname=''
        designation=''
        if name.startswith('MR') or name.startswith('MRS') or name.startswith('MISS'):
            if len(names)>2:
                designation,fname,lname=names[0],names[1],names[2]
            elif len(names) ==2:
                 designation,fname=names[0],names[1]
            else:
                designation=names[0]
        else:
            account_type='Business'
            if len(names)>2:
                fname,lname=names[1],names[2]
            elif len(names) ==2:
                 fname,lname=names[0],names[1]
            else:
                fname=names[0]
        return account_type,designation,fname,lname
        

    def save_contact(self):
        try:
            df = pd.read_csv(self.filePath)
            customer_group=None
            business_name=None
            business_address=None
            for index, row in df.iterrows():
                name=row['Name'] if not pd.isnull(row['Name']) else row['Business Name']
                if pd.isnull(row['Contact ID']):
                    row['Contact ID'] = f'C{index+1:06d}'
                if pd.isnull(row['Name']):
                    print(type(row['Name']),row['Name'])
                    print(row['Business Name'])
                    print(row['Contact ID'])
                account_type,desig,fname,lname=self.get_contact_name(name)
                user, created = User.objects.update_or_create(
                    email=f"{fname}{lname}{index}@gmail.com",
                    username=f"{fname}{lname}{index}@gmail.com",
                    defaults={
                        'first_name': fname,   
                        'last_name':lname,
                        'phone': row['Mobile'],
                        'is_active': True  # Assuming all users are active
                    }
                )
                if account_type=='Business':
                    business_name=row['Business Name'] if not pd.isnull(row['Business Name']) else f'{fname} {lname}'
                    business_address=row['Business Address'] if not pd.isnull(row['Business Address']) else '1234 Street'
                if not pd.isnull(row['Customer Group']):
                    customer_group, created = CustomerGroup.objects.update_or_create(
                        group_name=row['Customer Group'],
                        defaults={
                            'dicount_calculation': 'Percentage',  # Default value
                            'amount': 0  # Default value
                        }
                    )

                contact, created = Contact.objects.update_or_create(
                    contact_id=row['Contact ID'],
                    contact_type=row['Contact Type'],
                    user=user,
                    defaults={
                        'designation': desig,
                        'customer_group': customer_group,
                        'account_type': account_type,
                        'tax_number': row['Tax Number'] if row['Tax Number'] != 'nan' else 'N/A',
                        'business_name': business_name,
                        'business_address': business_address,
                        'alternative_contact': row['Alternative Contact'] if row['Alternative Contact'] != 'nan' else 'N/A',
                        'phone': row['Mobile'] if row['Mobile'] != 'nan' else 'N/A',
                        'credit_limit': self.clean_money_cols(row['Credit Limit']) or 0,
                        'added_on': row['Added On'],
                        'is_deleted': False,
                        'created_by': self.request.user,
                    }
                )
                _, created = ContactAccount.objects.update_or_create(
                    contact=contact,
                    defaults={
                        'account_balance': self.clean_money_cols(row['Opening Balance']) or 0,
                        'advance_balance': self.clean_money_cols(row['Advance Balance']) or 0,
                        'total_sale_due': self.clean_money_cols(row['Total Sale Due']) or 0,
                        'total_sale_return_due': self.clean_money_cols(row['Total Sell Return Due']) or 0
                    }
                )
            return {'success': True, 'message': 'Contacts imported successfully'}
        except Exception as e:
            print(e)
            return {'success': False, 'error': str(e)}
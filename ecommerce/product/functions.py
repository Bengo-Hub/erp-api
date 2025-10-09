import pandas as pd
from decimal import Decimal
from django.utils import timezone
from ecommerce.stockinventory.models import *
from business.models import Bussiness,Branch
from .models import Category, ProductBrands, ProductImages, Products
import re
import os
from django.db import IntegrityError
from django.conf import settings
from django.contrib.auth import get_user_model
User=get_user_model()

class ImportProducts:
    def __init__(self,request,path,business):
       self.filePath=path
       self.request=request
       self.biz=business

    def clean_money_cols(self,money_string:str):
        # Remove non-numeric characters from the money string
        cleaned_money = money_string.strip().replace('KSh', '').replace(',', '')
        # Convert the cleaned money string to Decimal format
        decimal_money = Decimal(cleaned_money)
        return decimal_money
    
    def extract_stock_level(self,stock_string:str):
        # Split the string by space to separate the numeric part
        parts = stock_string.replace(',','').split()
        # Check if the string contains numeric part and return it as integer
        if len(parts) > 0:
            stock_level = int(parts[0])
            return stock_level
        else:
            return 0  # Return None if no numeric part found

    def save_product(self):
        try:
            if 'csv' in self.filePath:
                df = pd.read_csv(self.filePath)
            else:
                df=pd.read_excel(self.filePath)
            df.dropna(thresh=df.shape[1] - 3,inplace=True)
            df.fillna(0,inplace=True)
            #print(df.columns)
             # Get default image URL
            default_image_path = os.path.join(settings.MEDIA_ROOT, 'default.png')
            default_image_url='default.png'
            if os.path.exists(default_image_path):
                default_image_url = 'default.png'
            else:
                raise FileNotFoundError("Default image 'default.png' not found in media folder.")
            brand=None
            main_category=None
            for index, row in df.iterrows():
                if not pd.isnull(row['Category']):
                    main_category, created = Category.objects.update_or_create(
                        name=row['Category'],
                        status=1  
                    )
                if not pd.isnull(row['Brand']):
                    brand, created = ProductBrands.objects.update_or_create(
                        title=row['Brand'],
                    )
                try:
                    serial=f'{index:06d}'
                    sku=f'{index:46d}'
                    if row['SERIAL'] !='nan' or row['SERIAL'] is not None:
                        serial=row['SERIAL']
                    if row['SKU'] !='nan' or row['SKU'] is not None:
                        sku=row['SKU']
                    product, created= Products.objects.update_or_create(
                        serial=str(int(serial)),
                        sku=str(int(sku)),
                        defaults={
                            'category':main_category,
                             'brand':brand,
                            'title': row['Product'],
                            'description': '', 
                            'status': 1, 
                            'weight': '', 
                            'dimentions': '', 
                        }
                    )
                    # Link product to default image
                    print(default_image_url)
                    product_image, created= ProductImages.objects.update_or_create(
                        product=product,
                        image=default_image_url
                    )
                    # Create or update business branch
                    business_branch, created = Branch.objects.update_or_create(
                        name=f'Branch {index+1}',  # Default value
                        business=self.biz,  # Set business object accordingly
                        defaults={
                            'code':f'BNG{index+1:04d}',  # Default value with 3 leading zeros
                            'is_active': True
                        }
                    )
                    # Creating stock inventory
                    product_type=row['Product Type']
                    unit,created=Unit.objects.update_or_create(title='Piece(s)')
                    if row['Unit'] !="" or None or 'nan':
                        unit,created=Unit.objects.update_or_create(title=f"{row['Unit']}")
                    if row['Variation'] !="" or None or 'nan':
                        variation,created=Variations.objects.update_or_create(title=f"{row['Variation']}{row['Unit']}",sku=sku,serial=serial)
                    stock,created= StockInventory.objects.update_or_create(
                        product_type=str(product_type).lower(),  
                        product=product,
                        unit=unit,
                        variation=variation,
                        buying_price=float(row['Unit Purchase Price']),
                        selling_price=float(row['Selling Price']),
                        stock_level=int(row['Current stock']),  
                        branch=business_branch,
                        reorder_level=2, 
                        usage='New', 
                        availability='In Stock' if int(row['Current stock'])>0 else 'Out of Stock' 
                    )
                except Exception as ie:
                    print(ie)
            return {'success': True, 'message': 'Products imported successfully'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
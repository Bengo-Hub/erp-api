from procurement.purchases.models import *
from ecommerce.stockinventory.models import *
from finance.expenses.models import *
from django.db.models import Sum, F,Q
from django.utils import timezone
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Sum, F, Q
from datetime import timedelta, datetime
from django.utils import timezone
from .models import *
import random
import string


def calculate_profit(start_date, end_date=None, time_period='daily', branch_id=None):
    # Set end_date to today if not provided
    if end_date is None:
        end_date = timezone.now()
    if start_date is None:
        start_date=end_date-timedelta(hours=12)

    # Calculate start_date based on time_period
    if time_period == 'daily':
        pass
    elif time_period == 'weekly':
        start_date = end_date - timedelta(days=7)
    elif time_period == 'bi-weekly':
        start_date = end_date - timedelta(days=14)
    elif time_period == 'monthly':
        start_date = end_date - relativedelta(months=1)
    elif time_period == 'quarterly':
        start_date = end_date - relativedelta(months=3)
    elif time_period == 'yearly':
        start_date = end_date - relativedelta(years=1)

     # Get data for the specified date range
    sales = Sales.objects.filter(date_added__range=[start_date, end_date])
    sale_returns = SalesReturn.objects.filter(date_returned__range=[start_date, end_date])
    stock_transactions=StockTransaction.objects.all().order_by('-transaction_date')#filter(transaction_date__range=[start_date, end_date])
    #print(stock_transactions.filter(transaction_date__date__lte=end_date.date(),transaction_type='SALE').order_by('-transaction_date'))
    expenses= Expense.objects.filter(date_added__range=[start_date, end_date])
    purchases= Purchase.objects.filter(date_added__range=[start_date, end_date])
    purchase_returns=PurchaseReturn.objects.filter(date_returned__range=[start_date, end_date])
    stock_transfers=StockTransfer.objects.filter(transfrer_date__range=[start_date, end_date])
    stock_adjustments=StockAdjustment.objects.filter(adjusted_at__range=[start_date, end_date])
    shippings=Shipping.objects.filter(sale__date_added__range=[start_date, end_date])
    rewards= CustomerReward.objects.filter(date_created__range=[start_date, end_date])
    print(start_date,end_date)
    if branch_id is not None:
        sales=sales.filter(salesitems__stock_item__branch__branch_code=branch_id)
        sale_returns=sale_returns.filter(return_items__stock_item__branch__branch_code=branch_id)
        stock_transactions=stock_transactions.filter(branch__branch_id=branch_id)
        purchases=purchases.filter(purchaseitems__stock_item__branch__branch_code=branch_id)
        purchase_returns=purchase_returns.filter(return_items__stock_item__branch__branch_code=branch_id)
        expenses=expenses.filter(business_location__branch__branch_code=branch_id)
        stock_adjustments=stock_adjustments.filter(branch__branch_code=branch_id)
        stock_transfers=stock_transfers.filter(Q(location_from__branch_code=branch_id)|(Q(location_to__branch_code=branch_id)))
        shippings=shippings.filter(sale__salesitems__stock_item__branch__branch_code=branch_id)
        rewards=rewards.filter(sale__salesitems__stock_item__branch__branch_code=branch_id)

    # Get opening stock by purchase price and sale price
    opening_stock_by_purchase_price = stock_transactions.filter(transaction_type='INITIAL').aggregate(
        opening_stock_by_purchase_price=Sum(F('quantity') * F('stock_item__buying_price'))
    )['opening_stock_by_purchase_price'] or 0

    opening_stock_by_sale_price =stock_transactions.filter(transaction_type='INITIAL').aggregate(opening_stock_by_sale_price=Sum(F('quantity') * F('stock_item__selling_price')))['opening_stock_by_sale_price'] or 0
     # Get total expenses
    total_expenses =expenses.aggregate(total_expenses=Sum('total_amount'))['total_expenses'] or 0
    # Get total stock adjustment
    stock_adjustment_increase = stock_adjustments.filter(adjustment_type='increase').aggregate(stock_adjustment=Sum('total_amount'))['stock_adjustment'] or 0
    stock_adjustment_decrease = stock_adjustments.filter(adjustment_type='decrease').aggregate(stock_adjustment=Sum('total_amount'))['stock_adjustment'] or 0
    total_stock_adjustment=sum([stock_adjustment_increase,stock_adjustment_decrease])
    # Get total purchase (Exc. tax, Discount)
    total_purchases=purchases.aggregate(total_purchase=Sum('grand_total'))['total_purchase'] or 0
    # Get total purchase shipping charge
    total_purchase_shipping_charge = purchases.aggregate(total_purchase_shipping_charge=Sum('purchase_shipping_charge'))['total_purchase_shipping_charge'] or 0
    # Get purchase additional expenses
    total_purchase_additional_expenses = purchases.aggregate(total_purchase_additional_expenses=Sum('additional_expenses'))['total_purchase_additional_expenses'] or 0
    # Get total transfer shipping charge
    total_transfer_shipping_charge = stock_transfers.aggregate(total_transfer_shipping_charge=Sum('transfer_shipping_charge'))['total_transfer_shipping_charge'] or 0
    # Get total sell discount
    total_sell_discount = sales.aggregate(total_sell_discount=Sum('sale_discount'))['total_sell_discount'] or 0
    # Get total customer reward
    total_customer_reward =rewards.aggregate(total_customer_reward=Sum('amount'))['total_customer_reward'] or 0
    # Get total sell return
    total_sell_return =sale_returns.aggregate(total_sell_return=Sum('return_amount'))['total_sell_return'] or 0
    # Get closing stock by purchase price and sale price
    # Fetch relevant transactions
    stock_transactions=stock_transactions.filter(transaction_date__date__lte=end_date.date())
    # Calculate the sum of quantities for each transaction type
    adjustment_amount_b = stock_transactions.filter(transaction_type='ADJUSTMENT').aggregate(adjustment_amount=Sum(F('quantity') * F('stock_item__buying_price')))['adjustment_amount'] or 0
    purchase_amount_b = stock_transactions.filter(transaction_type='PURCHASE').aggregate(purchase_amount=Sum(F('quantity') * F('stock_item__buying_price')))['purchase_amount'] or 0
    sale_amount_b = stock_transactions.filter(transaction_type='SALE').aggregate(sale_amount=Sum(F('quantity') * F('stock_item__buying_price')))['sale_amount'] or 0
    sale_return_amount_b = stock_transactions.filter(transaction_type='SALE_RETURN').aggregate(sale_return_amount=Sum(F('quantity') * F('stock_item__buying_price')))['sale_return_amount'] or 0
    purchase_return_amount_b = stock_transactions.filter(transaction_type='PURCHASE_RETURN').aggregate(purchase_return_amount=Sum(F('quantity') * F('stock_item__buying_price')))['purchase_return_amount'] or 0
    # Calculate closing stock by subtracting purchase returns and sales
    closing_stock_by_purchase_price = opening_stock_by_purchase_price + (adjustment_amount_b + purchase_amount_b + sale_return_amount_b)-(purchase_return_amount_b+sale_amount_b)
    adjustment_amount_s = stock_transactions.filter(transaction_type='ADJUSTMENT').aggregate(adjustment_amount=Sum(F('quantity') * F('stock_item__selling_price')))['adjustment_amount'] or 0
    purchase_amount_s = stock_transactions.filter(transaction_type='PURCHASE').aggregate(purchase_amount=Sum(F('quantity') * F('stock_item__selling_price')))['purchase_amount'] or 0
    sale_amount_s = stock_transactions.filter(transaction_type='SALE').aggregate(sale_amount=Sum(F('quantity') * F('stock_item__selling_price')))['sale_amount'] or 0
    sale_return_amount_s = stock_transactions.filter(transaction_type='SALE_RETURN').aggregate(sale_return_amount=Sum(F('quantity') * F('stock_item__selling_price')))['sale_return_amount'] or 0
    purchase_return_amount_s = stock_transactions.filter(transaction_type='PURCHASE_RETURN').aggregate(purchase_return_amount=Sum(F('quantity') * F('stock_item__selling_price')))['purchase_return_amount'] or 0
    closing_stock_by_sale_price = opening_stock_by_sale_price + (adjustment_amount_s + purchase_amount_s + sale_return_amount_s)-(purchase_return_amount_s+sale_amount_s)
    # Calculate total sales by purchase price (Exc. tax, Discount)
    total_sale_by_purchase_price =sales.aggregate(total_purchase=Sum('salesitems__stock_item__buying_price'))['total_purchase'] or 0
    # Calculate total sales (Exc. tax, Discount)
    total_sales = sales.aggregate(total_sales=Sum('salesitems__stock_item__selling_price'))['total_sales'] or 0
    # Get total sell shipping charge
    total_sell_shipping_charge = shippings.aggregate(total_sell_shipping_charge=Sum('shipping_address__address__shipping_charge'))['total_sell_shipping_charge'] or 0
    # Get sell additional expenses
    total_sell_additional_expenses = sales.aggregate(total_sell_additional_expenses=Sum('additional_expenses'))['total_sell_additional_expenses'] or 0
    # Get total stock recovered
    total_stock_recovered = sale_returns.aggregate(total_stock_recovered=Sum(F('return_items__sub_total')))['total_stock_recovered'] or 0
    # Get total purchase return
    total_purchase_return = purchase_returns.aggregate(total_purchase_return=Sum('return_amount'))['total_purchase_return'] or 0
    # Get total purchase discount
    total_purchase_discount = purchases.aggregate(total_purchase_discount=Sum('purchase_discount'))['total_purchase_discount'] or 0

    """Gross Profit: (Total sell price - Total purchase price)
    Net Profit: Gross Profit + (Total sell shipping charge + Sell additional expenses + Total Stock Recovered + Total Purchase discount + Total sell round off )
    - ( Total Stock Adjustment + Total Expense + Total purchase shipping charge + Total transfer shipping charge + Purchase additional expenses + Total Sell discount + Total customer reward )
    """
    # Calculate gross profit
    total_sales-=total_sell_return
    total_purchases-=total_purchase_return
    gross_profit = total_sales - total_sale_by_purchase_price
    # Calculate net profit
    net_profit = gross_profit + (total_sell_shipping_charge + total_sell_additional_expenses + total_stock_recovered + total_purchase_discount)\
                - total_stock_adjustment-(total_expenses + total_purchase_shipping_charge + total_purchase_additional_expenses+ total_sell_discount + total_customer_reward)
    data = {
        "opening_stock_by_purchase_price": opening_stock_by_purchase_price,
        "opening_stock_by_sale_price": opening_stock_by_sale_price,
        "total_purchase_exc_tax_discount": total_purchases,
        "total_stock_adjustment": total_stock_adjustment,
        "total_expense": total_expenses,
        "total_purchase_shipping_charge": total_purchase_shipping_charge,
        "purchase_additional_expenses": total_purchase_additional_expenses,
        "total_transfer_shipping_charge": total_transfer_shipping_charge,
        "total_sell_discount": total_sell_discount,
        "total_customer_reward": total_customer_reward,
        "total_sell_return": total_sell_return,
        "closing_stock_by_purchase_price": closing_stock_by_purchase_price,
        "closing_stock_by_sale_price": closing_stock_by_sale_price,
        "total_sales_exc_tax_discount": total_sales,
        "total_sell_shipping_charge": total_sell_shipping_charge,
        "sell_additional_expenses": total_sell_additional_expenses,
        "total_stock_recovered": total_stock_recovered,
        "total_purchase_return": total_purchase_return,
        "total_purchase_discount": total_purchase_discount,
        "gross_profit": gross_profit,
        "net_profit": net_profit,
    }
    return data

def generate_suspended_sale_reference():
    """Generate a unique reference number for suspended sales."""
    timestamp = datetime.now().strftime('%Y%m%d%H%M')
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"SUSP-{timestamp}-{random_chars}"

class DashboardAPIView(APIView):
    def get(self, request, *args, **kwargs):
        # Extract query parameters
        start_date = request.query_params.get('start_date',None)
        end_date = request.query_params.get('end_date',None)
        location_filter = request.query_params.get('location')

        # Convert date strings to datetime objects
        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # 1. Stats for Total Sales, Net Sales, Invoice due, Total Sell Return, Total purchase, Purchase due, Total Purchase Return, Expense
        sales_query = Sales.objects.filter(status='Final')
        if start_date and end_date:
            sales_query = sales_query.filter(date_added__date__range=[start_date, end_date])
        if location_filter:
            sales_query = sales_query.filter(register__branch_id=location_filter)

        total_sales = sales_query.aggregate(total=Sum('grand_total'))['total'] or 0
        invoice_due = Sales.objects.filter(payment_status='Due').aggregate(total=Sum('balance_due'))['total'] or 0
        total_expenses = Register.objects.aggregate(total=Sum('total_expenses'))['total'] or 0
        net_sales = total_sales - invoice_due - total_expenses
        total_sell_return = SalesReturn.objects.aggregate(total=Sum('return_amount'))['total'] or 0
        total_purchase = StockTransaction.objects.filter(transaction_type='PURCHASE').aggregate(total=Sum(F('quantity') * F('stock_item__buying_price')))['total'] or 0
        purchase_due = 0  # Assuming no direct model for purchase due, adjust as per your models
        total_purchase_return = StockTransaction.objects.filter(transaction_type='PURCHASE_RETURN').aggregate(total=Sum(F('quantity') * F('stock_item__buying_price')))['total'] or 0
        total_expense = Register.objects.aggregate(total=Sum('total_expenses'))['total'] or 0

        stats = {
            'total_sales': total_sales,
            'net_sales': net_sales,
            'invoice_due': invoice_due,
            'total_sell_return': total_sell_return,
            'total_purchase': total_purchase,
            'purchase_due': purchase_due,
            'total_purchase_return': total_purchase_return,
            'total_expense': total_expense,
        }

        # 2. Graph data for sales last 30 days
        today = timezone.now().date()
        last_30_days = [today - timedelta(days=i) for i in range(30)]
        last_30_days.reverse()
        sales_last_30_days_data = {date.strftime('%Y-%m-%d'): 0 for date in last_30_days}

        sales_last_30_days_query = Sales.objects.filter(date_added__gte=last_30_days[0])
        if location_filter:
            sales_last_30_days_query = sales_last_30_days_query.filter(register__branch_id=location_filter)

        sales_last_30_days = sales_last_30_days_query.values('date_added__date').annotate(total=Sum('grand_total')).order_by('date_added__date')

        # Update the dictionary with actual sales data
        for sale in sales_last_30_days:
            if sale['date_added__date']:  # Check if date_added__date is not None
                date_str = sale['date_added__date'].strftime('%Y-%m-%d')
                sales_last_30_days_data[date_str] = sale['total']

        # 3. Graph data for Sales Current Financial Year
        current_year = timezone.now().year
        months_in_year = [datetime(current_year, month, 1).strftime('%Y-%m') for month in range(1, 13)]
        sales_current_year_data = {month: 0 for month in months_in_year}

        sales_current_year_query = Sales.objects.filter(date_added__year=current_year)
        if start_date and end_date:
            sales_current_year_query = sales_current_year_query.filter(date_added__date__range=[start_date, end_date])
        if location_filter:
            sales_current_year_query = sales_current_year_query.filter(register__branch_id=location_filter)

        sales_current_year = sales_current_year_query.values('date_added__month').annotate(total=Sum('grand_total')).order_by('date_added__month')
        for sale in sales_current_year:
            if sale['date_added__month']:  # Check if date_added__month is not None
                month_str = datetime(current_year, sale['date_added__month'], 1).strftime('%Y-%m')
                sales_current_year_data[month_str] = sale['total']

        # 4. Sales Payment Due (Customer, Invoice No., Due Amount) and allows filter by business location
        sales_payment_due_query = Sales.objects.filter(payment_status='Due')
        if start_date and end_date:
            sales_payment_due_query = sales_payment_due_query.filter(date_added__date__range=[start_date, end_date])
        if location_filter:
            sales_payment_due_query = sales_payment_due_query.filter(register__branch_id=location_filter)

        sales_payment_due_data = sales_payment_due_query.values('customer__user__first_name', 'sale_id', 'balance_due')

        # 5. Purchase Payment Due (Supplier, Reference No, Due Amount)
        purchase_payment_due_query = Purchase.objects.filter(payment_status='due')
        if start_date and end_date:
            purchase_payment_due_query = purchase_payment_due_query.filter(date_added__date__range=[start_date, end_date])
        if location_filter:
            purchase_payment_due_query = purchase_payment_due_query.filter(branch_id=location_filter)

        purchase_payment_due = purchase_payment_due_query.values('supplier', 'purchase_id', 'balance_overdue')

        # 6. Product Stock Alert (Product, Location, Current stock)
        product_stock_alert_query = StockInventory.objects.filter(stock_level__lte=F('reorder_level'))
        if location_filter:
            product_stock_alert_query = product_stock_alert_query.filter(branch_id=location_filter)

        product_stock_alert = product_stock_alert_query.values('product__title', 'branch__branch_name', 'stock_level')

        # 7. Sales Order(Date, Order No, Customer name, Contact Number, Location, Status, Shipping Status, Quantity Remaining, Added By)
        sales_orders_query = Sales.objects.all()
        if start_date and end_date:
            sales_orders_query = sales_orders_query.filter(date_added__date__range=[start_date, end_date])
        if location_filter:
            sales_orders_query = sales_orders_query.filter(register__branch_id=location_filter)

        sales_orders = sales_orders_query.values('date_added', 'sale_id', 'customer__user__first_name', 'customer__phone', 'register__location__location_name', 'status', 'shippings__status', 'attendant__username').annotate(quantity=Sum('salesitems__qty'))

        # 8. Pending Shipments(Date, Invoice No., Customer name, Contact Number, Location, Shipping Status, Payment Status)
        pending_shipments_query = Shipping.objects.filter(status='pending')
        if start_date and end_date:
            pending_shipments_query = pending_shipments_query.filter(created_at__date__range=[start_date, end_date])
        if location_filter:
            pending_shipments_query = pending_shipments_query.filter(sale__register__branch_id=location_filter)

        pending_shipments = pending_shipments_query.values('created_at', 'sale__sale_id', 'sale__customer__user__first_name', 'sale__customer__phone', 'sale__register__location__location_name', 'status', 'sale__payment_status')

        response_data = {
            'stats': stats,
            'sales_last_30_days': sales_last_30_days_data,
            'sales_current_year': sales_current_year_data,
            'sales_payment_due': list(sales_payment_due_data),
            'purchase_payment_due': list(purchase_payment_due),
            'product_stock_alert': list(product_stock_alert),
            'sales_orders': list(sales_orders),
            'pending_shipments': list(pending_shipments),
        }

        return Response(response_data, status=status.HTTP_200_OK)
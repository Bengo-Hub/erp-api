from datetime import datetime

#generate purchase order
def generate_purchase_order(start):
    return f"PO-{datetime.now().year}-{start:06d}"
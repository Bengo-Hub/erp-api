from ecommerce.stockinventory.models import StockInventory
from ecommerce.stockinventory.serializers import StockSerializer
import zoneinfo, sys

s = StockInventory.objects.select_related('product__business').first()
print('stock:', s)
if not s:
    print('no stock found')
    sys.exit(0)

b = s.product.business if s and s.product else None
print('business:', b)
print('business.timezone type:', type(getattr(b,'timezone',None)), 'value:', getattr(b,'timezone',None))

serializer = StockSerializer(s)
data = serializer.data

found = []

def find_zone(obj, path='root'):
    if isinstance(obj, zoneinfo.ZoneInfo):
        found.append((path, obj))
        print('Found ZoneInfo at', path, obj, type(obj))
        return True
    if isinstance(obj, dict):
        for k, v in obj.items():
            find_zone(v, path + '.' + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            find_zone(v, path + '[' + str(i) + ']')

find_zone(data)
print('found count:', len(found))
print('done')

from django.core.management.base import BaseCommand
import json
from zoneinfo import ZoneInfo


class Command(BaseCommand):
    help = 'Check serialized stock items for ZoneInfo objects and json-serializability'

    def handle(self, *args, **options):
        from ecommerce.stockinventory.models import StockInventory
        from ecommerce.stockinventory.serializers import StockSerializer

        s = StockInventory.objects.first()
        if not s:
            self.stdout.write(self.style.WARNING('No StockInventory items found'))
            return

        data = StockSerializer(s).data

        def find_zoneinfo(o, path=''):
            if isinstance(o, dict):
                for k, v in o.items():
                    res = find_zoneinfo(v, f"{path}.{k}" if path else k)
                    if res:
                        return res
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    res = find_zoneinfo(v, f"{path}[{i}]")
                    if res:
                        return res
            else:
                if isinstance(o, ZoneInfo):
                    return path, o
            return None

        found = find_zoneinfo(data)
        if found:
            self.stdout.write(self.style.ERROR(f'Found ZoneInfo in serialized data at {found[0]}: {found[1]}'))
        else:
            try:
                json.dumps(data)
                self.stdout.write(self.style.SUCCESS('Serialized stock data is JSON serializable'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'JSON dumps failed: {e}'))

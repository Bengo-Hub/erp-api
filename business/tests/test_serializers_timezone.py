from django.test import TestCase
from business.models import Bussiness
from business.serializers import BussinessSerializer


class BussinessSerializerTimezoneTest(TestCase):
    def test_timezone_serializes_to_string(self):
        b = Bussiness(name='TZTest', timezone='Africa/Nairobi')
        s = BussinessSerializer(b)
        tz = s.data.get('timezone')

        # Should be JSON-serializable string (not a ZoneInfo object)
        self.assertIsInstance(tz, str)
        self.assertIn('Africa', tz)

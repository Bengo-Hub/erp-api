import os
import sys
from ProcureProKEAPI.wsgi import application
from whitenoise import WhiteNoise


sys.path.insert(0, os.path.dirname(__file__))

environ = os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "ProcureProKEAPI.settings")

application = WhiteNoise(
    application, root="/home/gxyxuwub/public_html/ProcureProKEAPI/static/")

application.add_files(
    "/home/gxyxuwub/public_html/ProcureProKEAPI/static/", prefix="more-files/")
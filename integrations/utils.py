import os
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from core.models import AppSettings

class Crypto:
    def __init__(self,text:str,command:str):
        # Load environment variables from .env file
        load_dotenv()
        app_setting=AppSettings.objects.first()
        self.command=command
        self.text=text.strip()
        self.key=os.getenv('CYPHER_KEY')
        if app_setting is not None:
            self.key=app_setting.cypher_key.encode('utf-8')

    def encrypt(self):
        try:
            cipher = Fernet(self.key)
            # Encrypt data
            encrypted_data = cipher.encrypt(self.text.encode('utf-8'))
            return encrypted_data.decode('utf-8')
        except Exception as e:
            print(e)
            return str(e)
    
    def decrypt(self):
        try:
            # Decrypt data
            cipher = Fernet(self.key)
            decrypted_data = cipher.decrypt(self.text)
            return decrypted_data.decode('utf-8')
        except Exception as e:
            print(e)
            return str(e)
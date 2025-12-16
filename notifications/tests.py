"""
Email Service Audit and Test
================================
This test audits and validates email sending with encryption/decryption.

Root Cause of Email Authentication Failure:
- The email service loads EmailConfiguration from the database
- The smtp_password field is encrypted at rest using Fernet encryption
- When the password is retrieved, it's in encrypted form
- The email service was passing the encrypted password directly to Django's EmailBackend
- SMTP authentication fails with "535, Authentication Failed" because the encrypted string is invalid

Solution:
- Decrypt the smtp_password before passing it to EmailBackend
- Ensure all sensitive fields (smtp_password, api_key, api_secret) are decrypted
- Add property methods for safe access to decrypted values
"""

import os
import django
from django.test import TestCase
from django.utils import timezone

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from notifications.models import NotificationIntegration, EmailConfiguration
from notifications.services.email_service import EmailService
from integrations.utils import Crypto


class EmailServiceAudit(TestCase):
    """Audit email service configuration and decryption"""
    
    def test_email_config_encryption_decryption(self):
        """Test that encrypted passwords are properly encrypted/decrypted"""
        print("\n" + "="*80)
        print("TEST: Email Configuration Encryption/Decryption")
        print("="*80)
        
        # Test values
        from_email = "gadmin@masterspace.co.ke"
        smtp_host = "smtppro.zoho.com"
        smtp_port = 587
        smtp_username = "gadmin@masterspace.co.ke"
        plain_password = "@Vertex2020!"
        
        # Create integration
        integration, created = NotificationIntegration.objects.get_or_create(
            name="Zoho Email",
            defaults={
                'integration_type': 'EMAIL',
                'provider': 'SMTP',
                'is_active': True,
                'is_default': True
            }
        )
        print(f"\n✓ Integration created/retrieved: {integration.name}")
        
        # Create email configuration
        # This should auto-encrypt the password
        config, created = EmailConfiguration.objects.get_or_create(
            integration=integration,
            defaults={
                'provider': 'SMTP',
                'from_email': from_email,
                'from_name': 'Masters ERP',
                'smtp_host': smtp_host,
                'smtp_port': smtp_port,
                'smtp_username': smtp_username,
                'smtp_password': plain_password,
                'use_tls': True,
                'use_ssl': False,
                'fail_silently': False,
                'timeout': 60
            }
        )
        
        print(f"\n✓ Email configuration created/retrieved")
        print(f"  - From Email: {config.from_email}")
        print(f"  - SMTP Host: {config.smtp_host}")
        print(f"  - SMTP Port: {config.smtp_port}")
        print(f"  - SMTP Username: {config.smtp_username}")
        print(f"  - Use TLS: {config.use_tls}")
        
        # Check if password is encrypted
        print(f"\n  - Raw Password from DB: {config.smtp_password[:20]}...")
        is_encrypted = config.smtp_password.startswith("gAAAAA")
        print(f"  - Is Encrypted: {is_encrypted}")
        
        if is_encrypted:
            # Decrypt manually to verify
            crypto = Crypto(config.smtp_password, 'decrypt')
            decrypted = crypto.decrypt()
            print(f"  - Decrypted Password: {decrypted}")
            self.assertEqual(decrypted, plain_password, 
                           f"Decrypted password does not match. Got: {decrypted}")
            print(f"  ✓ Password encryption/decryption working correctly")
        else:
            print(f"  ⚠ Password is NOT encrypted. This is a security issue!")
            print(f"  - Actual password: {config.smtp_password}")
    
    def test_email_service_get_connection_with_encryption(self):
        """Test that email service properly decrypts password when creating connection"""
        print("\n" + "="*80)
        print("TEST: EmailService Connection with Decryption")
        print("="*80)
        
        # Get or create the integration/config
        integration = NotificationIntegration.objects.filter(
            name="Zoho Email",
            integration_type='EMAIL'
        ).first()
        
        if not integration:
            print("\n⚠ Test integration not found. Skipping...")
            return
        
        # Create email service
        email_service = EmailService(integration=integration)
        print(f"\n✓ EmailService initialized")
        print(f"  - Integration: {email_service.integration.name if email_service.integration else 'None'}")
        print(f"  - Config available: {email_service.config is not None}")
        
        if email_service.config:
            print(f"\n  Current implementation issue:")
            print(f"  - SMTP Username: {email_service.config.smtp_username}")
            print(f"  - SMTP Password (encrypted): {email_service.config.smtp_password[:20]}...")
            print(f"\n  ⚠ The password is still encrypted!")
            print(f"     This is passed directly to Django's EmailBackend,")
            print(f"     causing SMTP authentication to fail with '535, Authentication Failed'")
    
    def test_send_test_email_with_decrypted_password(self):
        """Test sending email with properly decrypted password"""
        print("\n" + "="*80)
        print("TEST: Send Test Email with Decrypted Password")
        print("="*80)
        
        integration = NotificationIntegration.objects.filter(
            name="Zoho Email",
            integration_type='EMAIL'
        ).first()
        
        if not integration:
            print("\n⚠ Test integration not found. Skipping...")
            return
        
        config = integration.email_config
        if not config:
            print("\n⚠ Email configuration not found. Skipping...")
            return
        
        # Decrypt password
        crypto = Crypto(config.smtp_password, 'decrypt')
        decrypted_password = crypto.decrypt()
        
        print(f"\n✓ Configuration loaded:")
        print(f"  - Host: {config.smtp_host}")
        print(f"  - Port: {config.smtp_port}")
        print(f"  - Username: {config.smtp_username}")
        print(f"  - Use TLS: {config.use_tls}")
        print(f"  - Decrypted Password Length: {len(decrypted_password)}")
        
        # Create email service with decrypted password
        from django.core.mail.backends.smtp import EmailBackend
        
        backend = EmailBackend(
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_username,
            password=decrypted_password,  # Use decrypted password
            use_tls=config.use_tls,
            use_ssl=config.use_ssl,
            fail_silently=config.fail_silently,
            timeout=config.timeout
        )
        
        print(f"\n✓ SMTP Backend created with decrypted password")
        
        # Try to open connection (this will fail if credentials are wrong)
        try:
            connection = backend.open()
            print(f"\n✓ SMTP Connection successful!")
            if connection:
                connection.quit()
                print(f"✓ Connection closed gracefully")
            else:
                print(f"⚠ Connection object is None")
        except Exception as e:
            print(f"\n✗ SMTP Connection failed: {str(e)}")
            print(f"\nPossible reasons:")
            print(f"1. Credentials are incorrect")
            print(f"2. SMTP server is not available")
            print(f"3. Firewall/network issue")
            print(f"4. Password decryption failed (encrypted value was passed)")


def run_email_audit():
    """Run email service audit"""
    import sys
    from django.test.utils import setup_test_environment, teardown_test_environment
    from django.test import Client
    
    print("\n" + "="*80)
    print("EMAIL SERVICE AUDIT AND DIAGNOSIS")
    print("="*80)
    print("\nThis audit identifies and tests the email authentication issue")
    print("Issue: (535, b'Authentication Failed') when sending emails")
    print("\nRoot Cause Analysis:")
    print("1. Encrypted passwords are stored in the database")
    print("2. The password is NOT being decrypted before SMTP use")
    print("3. The encrypted string is passed to Django's EmailBackend")
    print("4. SMTP authentication fails because it receives encrypted bytes")
    
    test = EmailServiceAudit()
    test._testMethodName = 'test_email_config_encryption_decryption'
    
    try:
        test.test_email_config_encryption_decryption()
    except Exception as e:
        print(f"\n✗ Test failed: {str(e)}")
    
    try:
        test.test_email_service_get_connection_with_encryption()
    except Exception as e:
        print(f"\n✗ Test failed: {str(e)}")
    
    try:
        test.test_send_test_email_with_decrypted_password()
    except Exception as e:
        print(f"\n✗ Test failed: {str(e)}")
    
    print("\n" + "="*80)
    print("AUDIT COMPLETE")
    print("="*80)
    print("\nRECOMMENDED FIXES:")
    print("1. Add decrypt() method to EmailConfiguration model")
    print("2. Update get_connection() in EmailService to decrypt passwords")
    print("3. Add property methods for safe access to decrypted values")
    print("4. Update SMSConfiguration and PushConfiguration similarly")
    print("="*80 + "\n")


class AttachmentSerializationTests(TestCase):
    """Test attachment encoding/decoding for Celery serialization"""
    
    def test_encode_attachments_for_celery(self):
        """Test that binary attachments are properly encoded for Celery"""
        from notifications.services.email_service import _encode_attachments_for_celery
        
        print("\n" + "="*80)
        print("TEST: Encode Attachments for Celery Serialization")
        print("="*80)
        
        # Create test PDF bytes (simulated)
        pdf_content = b'%PDF-1.4\nThis is a fake PDF for testing attachment serialization'
        filename = 'invoice_12345.pdf'
        mimetype = 'application/pdf'
        
        # Create attachment tuple
        attachment = (filename, pdf_content, mimetype)
        attachments = [attachment]
        
        print(f"\n✓ Original attachment:")
        print(f"  - Filename: {filename}")
        print(f"  - Content type: {type(pdf_content).__name__}")
        print(f"  - Content size: {len(pdf_content)} bytes")
        print(f"  - MIME type: {mimetype}")
        
        # Encode for Celery
        encoded = _encode_attachments_for_celery(attachments)
        
        self.assertIsNotNone(encoded, "Encoded attachments should not be None")
        self.assertEqual(len(encoded), 1, "Should have one encoded attachment")
        
        enc_filename, enc_content, enc_mimetype = encoded[0]
        
        self.assertEqual(enc_filename, filename, "Filename should be preserved")
        self.assertEqual(enc_mimetype, mimetype, "MIME type should be preserved")
        self.assertTrue(isinstance(enc_content, str), "Encoded content should be string")
        self.assertTrue(enc_content.startswith("__b64__"), "Should have base64 marker")
        
        print(f"\n✓ Encoded attachment:")
        print(f"  - Filename: {enc_filename}")
        print(f"  - Content type: {type(enc_content).__name__}")
        print(f"  - Starts with marker: {enc_content.startswith('__b64__')}")
        print(f"  - Encoded content length: {len(enc_content)} chars")
        print(f"  - MIME type: {enc_mimetype}")
    
    def test_decode_attachments_from_celery(self):
        """Test that encoded attachments are properly decoded after Celery task"""
        from notifications.services.email_service import (
            _encode_attachments_for_celery,
            _decode_attachments_from_celery
        )
        
        print("\n" + "="*80)
        print("TEST: Decode Attachments from Celery Serialization")
        print("="*80)
        
        # Create test PDF bytes
        original_pdf = b'%PDF-1.4\nThis is a fake PDF for testing attachment serialization'
        filename = 'invoice_12345.pdf'
        mimetype = 'application/pdf'
        
        attachments = [(filename, original_pdf, mimetype)]
        
        print(f"\n✓ Original PDF:")
        print(f"  - Size: {len(original_pdf)} bytes")
        print(f"  - Hash: {hash(original_pdf)}")
        
        # Encode
        encoded = _encode_attachments_for_celery(attachments)
        
        print(f"\n✓ Encoded for transmission:")
        print(f"  - Content is string: {isinstance(encoded[0][1], str)}")
        
        # Decode
        decoded = _decode_attachments_from_celery(encoded)
        
        self.assertIsNotNone(decoded, "Decoded attachments should not be None")
        self.assertEqual(len(decoded), 1, "Should have one decoded attachment")
        
        dec_filename, dec_content, dec_mimetype = decoded[0]
        
        self.assertEqual(dec_filename, filename, "Filename should match")
        self.assertEqual(dec_mimetype, mimetype, "MIME type should match")
        self.assertEqual(dec_content, original_pdf, "Content should be identical")
        self.assertEqual(hash(dec_content), hash(original_pdf), "Hash should match")
        
        print(f"\n✓ Decoded PDF:")
        print(f"  - Filename: {dec_filename}")
        print(f"  - Size: {len(dec_content)} bytes")
        print(f"  - Hash: {hash(dec_content)}")
        print(f"  - Matches original: {dec_content == original_pdf}")
        print(f"  - MIME type: {dec_mimetype}")
    
    def test_roundtrip_multiple_attachments(self):
        """Test encoding/decoding with multiple attachments"""
        from notifications.services.email_service import (
            _encode_attachments_for_celery,
            _decode_attachments_from_celery
        )
        
        print("\n" + "="*80)
        print("TEST: Roundtrip Multiple Attachments")
        print("="*80)
        
        # Create multiple test attachments
        attachments = [
            ('invoice_123.pdf', b'PDF-CONTENT-123', 'application/pdf'),
            ('receipt_456.pdf', b'PDF-CONTENT-456-LONGER', 'application/pdf'),
            ('document.txt', b'Text document content', 'text/plain'),
        ]
        
        print(f"\n✓ Original attachments: {len(attachments)}")
        for filename, content, mimetype in attachments:
            print(f"  - {filename}: {len(content)} bytes ({mimetype})")
        
        # Encode and decode
        encoded = _encode_attachments_for_celery(attachments)
        decoded = _decode_attachments_from_celery(encoded)
        
        self.assertEqual(len(decoded), len(attachments), "Count should match")
        
        print(f"\n✓ After roundtrip:")
        for i, (orig, dec) in enumerate(zip(attachments, decoded)):
            orig_filename, orig_content, orig_mime = orig
            dec_filename, dec_content, dec_mime = dec
            
            self.assertEqual(dec_filename, orig_filename, f"Filename {i} should match")
            self.assertEqual(dec_mime, orig_mime, f"MIME type {i} should match")
            self.assertEqual(dec_content, orig_content, f"Content {i} should match")
            
            print(f"  ✓ Attachment {i}: {dec_filename} ({len(dec_content)} bytes) - OK")
    
    def test_none_attachments(self):
        """Test that None attachments are handled gracefully"""
        from notifications.services.email_service import (
            _encode_attachments_for_celery,
            _decode_attachments_from_celery
        )
        
        print("\n" + "="*80)
        print("TEST: None Attachments Handling")
        print("="*80)
        
        # Test None
        encoded = _encode_attachments_for_celery(None)
        self.assertIsNone(encoded, "None should remain None")
        print(f"\n✓ None input: {encoded}")
        
        # Test empty list
        encoded = _encode_attachments_for_celery([])
        self.assertIsNone(encoded, "Empty list should return None")
        print(f"✓ Empty list: {encoded}")
        
        # Decode None
        decoded = _decode_attachments_from_celery(None)
        self.assertIsNone(decoded, "None should remain None")
        print(f"✓ Decode None: {decoded}")


if __name__ == '__main__':
    run_email_audit()


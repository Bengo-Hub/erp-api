"""
File security utilities for Bengo ERP.
Provides file validation, virus scanning, and security checks for uploaded files.
"""

import io
import logging
from typing import Optional, Tuple, List, Dict, Any
from django.core.files.uploadedfile import UploadedFile
from django.core.exceptions import ValidationError
from PIL import Image

logger = logging.getLogger(__name__)


class FileSecurityError(Exception):
    """Exception raised for file security violations."""
    pass


class FileSecurityScanner:
    """
    Comprehensive file security scanner for uploaded files.
    
    Performs:
    - MIME type validation via magic bytes
    - File extension validation
    - File size validation
    - Image-specific validation (for image files)
    - Optional ClamAV virus scanning (if available)
    """
    
    # Magic bytes for common file types
    MAGIC_BYTES = {
        'image/jpeg': [(0, b'\xff\xd8\xff')],
        'image/png': [(0, b'\x89PNG\r\n\x1a\n')],
        'image/gif': [(0, b'GIF87a'), (0, b'GIF89a')],
        'image/webp': [(0, b'RIFF'), (8, b'WEBP')],
        'image/bmp': [(0, b'BM')],
        'image/tiff': [(0, b'II*\x00'), (0, b'MM\x00*')],
        'application/pdf': [(0, b'%PDF')],
        'application/zip': [(0, b'PK\x03\x04'), (0, b'PK\x05\x06'), (0, b'PK\x07\x08')],
        'text/plain': [],  # No specific magic bytes for text
    }
    
    # Allowed extensions by category
    ALLOWED_EXTENSIONS = {
        'image': ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'],
        'document': ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.csv'],
        'signature': ['.png', '.jpg', '.jpeg', '.webp'],  # Signatures should be images
        'stamp': ['.png', '.jpg', '.jpeg', '.webp'],  # Stamps should be images
    }
    
    # Default size limits (in bytes)
    SIZE_LIMITS = {
        'signature': 2 * 1024 * 1024,  # 2MB for signatures
        'stamp': 5 * 1024 * 1024,      # 5MB for stamps
        'profile_pic': 5 * 1024 * 1024, # 5MB for profile pictures
        'document': 50 * 1024 * 1024,   # 50MB for documents
        'image': 10 * 1024 * 1024,      # 10MB for general images
        'default': 10 * 1024 * 1024,    # 10MB default
    }
    
    # Dangerous patterns to detect in file content
    DANGEROUS_PATTERNS = [
        b'<?php',
        b'<%',
        b'<script',
        b'javascript:',
        b'eval(',
        b'exec(',
        b'system(',
        b'shell_exec',
        b'passthru',
        b'os.system',
        b'subprocess',
    ]
    
    def __init__(self, use_clamav: bool = False, clamav_host: str = 'localhost', clamav_port: int = 3310):
        """
        Initialize the file security scanner.
        
        Args:
            use_clamav: Whether to use ClamAV for virus scanning
            clamav_host: ClamAV daemon host
            clamav_port: ClamAV daemon port
        """
        self.use_clamav = use_clamav
        self.clamav_host = clamav_host
        self.clamav_port = clamav_port
        self._clamav_client = None
        
        if use_clamav:
            self._init_clamav()
    
    def _init_clamav(self):
        """Initialize ClamAV client if available."""
        try:
            import pyclamd
            self._clamav_client = pyclamd.ClamdNetworkSocket(
                host=self.clamav_host,
                port=self.clamav_port
            )
            if not self._clamav_client.ping():
                logger.warning("ClamAV daemon not responding, virus scanning disabled")
                self._clamav_client = None
        except ImportError:
            logger.info("pyclamd not installed, ClamAV scanning disabled")
            self._clamav_client = None
        except Exception as e:
            logger.warning(f"Failed to connect to ClamAV: {e}")
            self._clamav_client = None
    
    def get_file_content(self, file: UploadedFile) -> bytes:
        """Get file content as bytes."""
        file.seek(0)
        content = file.read()
        file.seek(0)
        return content
    
    def validate_magic_bytes(self, content: bytes, expected_mime: str) -> bool:
        """
        Validate file magic bytes match expected MIME type.
        
        Args:
            content: File content as bytes
            expected_mime: Expected MIME type
        
        Returns:
            True if magic bytes match, False otherwise
        """
        if expected_mime not in self.MAGIC_BYTES:
            return True  # No magic bytes defined for this type
        
        patterns = self.MAGIC_BYTES[expected_mime]
        if not patterns:
            return True  # No patterns to check
        
        for offset, pattern in patterns:
            if content[offset:offset + len(pattern)] == pattern:
                return True
        
        return False
    
    def detect_mime_from_magic(self, content: bytes) -> Optional[str]:
        """
        Detect MIME type from magic bytes.
        
        Args:
            content: File content as bytes
        
        Returns:
            Detected MIME type or None
        """
        for mime_type, patterns in self.MAGIC_BYTES.items():
            if not patterns:
                continue
            for offset, pattern in patterns:
                if len(content) > offset + len(pattern):
                    if content[offset:offset + len(pattern)] == pattern:
                        return mime_type
        return None
    
    def validate_extension(self, filename: str, category: str = 'image') -> bool:
        """
        Validate file extension is in allowed list.
        
        Args:
            filename: Original filename
            category: File category (image, document, signature, stamp)
        
        Returns:
            True if extension is allowed, False otherwise
        """
        if not filename:
            return False
        
        ext = '.' + filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
        allowed = self.ALLOWED_EXTENSIONS.get(category, self.ALLOWED_EXTENSIONS['image'])
        return ext in allowed
    
    def validate_file_size(self, file: UploadedFile, category: str = 'default') -> Tuple[bool, int]:
        """
        Validate file size is within limits.
        
        Args:
            file: Uploaded file
            category: File category for size limit lookup
        
        Returns:
            Tuple of (is_valid, actual_size)
        """
        size_limit = self.SIZE_LIMITS.get(category, self.SIZE_LIMITS['default'])
        actual_size = file.size if hasattr(file, 'size') else len(self.get_file_content(file))
        return actual_size <= size_limit, actual_size
    
    def check_dangerous_patterns(self, content: bytes) -> List[str]:
        """
        Check for dangerous patterns in file content.
        
        Args:
            content: File content as bytes
        
        Returns:
            List of detected dangerous patterns
        """
        detected = []
        content_lower = content.lower()
        
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern.lower() in content_lower:
                detected.append(pattern.decode('utf-8', errors='ignore'))
        
        return detected
    
    def validate_image(self, file: UploadedFile) -> Tuple[bool, Optional[str]]:
        """
        Validate image file is a valid image.
        
        Args:
            file: Uploaded file
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            content = self.get_file_content(file)
            img = Image.open(io.BytesIO(content))
            img.verify()  # Verify it's a valid image
            
            # Re-open after verify (verify() can only be called once)
            img = Image.open(io.BytesIO(content))
            
            # Check image dimensions are reasonable
            width, height = img.size
            if width > 10000 or height > 10000:
                return False, "Image dimensions too large (max 10000x10000)"
            if width < 10 or height < 10:
                return False, "Image dimensions too small (min 10x10)"
            
            return True, None
        except Exception as e:
            return False, f"Invalid image file: {str(e)}"
    
    def scan_for_viruses(self, content: bytes) -> Tuple[bool, Optional[str]]:
        """
        Scan file content for viruses using ClamAV.
        
        Args:
            content: File content as bytes
        
        Returns:
            Tuple of (is_clean, virus_name if infected)
        """
        if not self._clamav_client:
            return True, None  # No scanner available, assume clean
        
        try:
            result = self._clamav_client.scan_stream(content)
            if result is None:
                return True, None  # Clean
            else:
                # Result contains virus info
                return False, str(result)
        except Exception as e:
            logger.error(f"ClamAV scan error: {e}")
            return True, None  # Fail open on error
    
    def scan_file(
        self,
        file: UploadedFile,
        category: str = 'image',
        strict: bool = True
    ) -> Dict[str, Any]:
        """
        Perform comprehensive security scan on uploaded file.
        
        Args:
            file: Uploaded file to scan
            category: File category for validation rules
            strict: Whether to fail on any warning
        
        Returns:
            Dict with scan results:
            {
                'is_safe': bool,
                'errors': list of error messages,
                'warnings': list of warning messages,
                'detected_mime': detected MIME type,
                'file_size': file size in bytes
            }
        """
        result = {
            'is_safe': True,
            'errors': [],
            'warnings': [],
            'detected_mime': None,
            'file_size': 0
        }
        
        try:
            content = self.get_file_content(file)
            result['file_size'] = len(content)
            
            # 1. Validate file size
            size_valid, actual_size = self.validate_file_size(file, category)
            if not size_valid:
                limit = self.SIZE_LIMITS.get(category, self.SIZE_LIMITS['default'])
                result['errors'].append(
                    f"File too large: {actual_size / 1024 / 1024:.2f}MB (max {limit / 1024 / 1024:.2f}MB)"
                )
                result['is_safe'] = False
            
            # 2. Validate extension
            filename = getattr(file, 'name', '') or ''
            if not self.validate_extension(filename, category):
                allowed = ', '.join(self.ALLOWED_EXTENSIONS.get(category, []))
                result['errors'].append(f"Invalid file extension. Allowed: {allowed}")
                result['is_safe'] = False
            
            # 3. Detect MIME type from magic bytes
            detected_mime = self.detect_mime_from_magic(content)
            result['detected_mime'] = detected_mime
            
            # 4. Check for MIME type mismatch
            claimed_mime = getattr(file, 'content_type', None)
            if claimed_mime and detected_mime and claimed_mime != detected_mime:
                if detected_mime.startswith('image/') and claimed_mime.startswith('image/'):
                    result['warnings'].append(
                        f"MIME type mismatch: claimed {claimed_mime}, detected {detected_mime}"
                    )
                else:
                    result['errors'].append(
                        f"MIME type mismatch: claimed {claimed_mime}, detected {detected_mime}"
                    )
                    result['is_safe'] = False
            
            # 5. Validate image if it's an image category
            if category in ['image', 'signature', 'stamp', 'profile_pic']:
                img_valid, img_error = self.validate_image(file)
                if not img_valid:
                    result['errors'].append(img_error)
                    result['is_safe'] = False
            
            # 6. Check for dangerous patterns
            dangerous = self.check_dangerous_patterns(content)
            if dangerous:
                result['errors'].append(f"Dangerous content detected: {', '.join(dangerous[:3])}")
                result['is_safe'] = False
            
            # 7. Virus scan (if available)
            is_clean, virus_name = self.scan_for_viruses(content)
            if not is_clean:
                result['errors'].append(f"Virus detected: {virus_name}")
                result['is_safe'] = False
            
            # 8. In strict mode, warnings become errors
            if strict and result['warnings']:
                result['errors'].extend(result['warnings'])
                result['warnings'] = []
                result['is_safe'] = False
        
        except Exception as e:
            logger.exception(f"Error scanning file: {e}")
            result['errors'].append(f"Scan error: {str(e)}")
            result['is_safe'] = False
        
        return result


# Convenience functions for common use cases

def scan_signature_file(file: UploadedFile, strict: bool = True) -> Dict[str, Any]:
    """
    Scan a signature file for security issues.
    
    Args:
        file: Uploaded signature file
        strict: Whether to fail on warnings
    
    Returns:
        Scan result dictionary
    """
    scanner = FileSecurityScanner()
    return scanner.scan_file(file, category='signature', strict=strict)


def scan_stamp_file(file: UploadedFile, strict: bool = True) -> Dict[str, Any]:
    """
    Scan a business stamp file for security issues.
    
    Args:
        file: Uploaded stamp file
        strict: Whether to fail on warnings
    
    Returns:
        Scan result dictionary
    """
    scanner = FileSecurityScanner()
    return scanner.scan_file(file, category='stamp', strict=strict)


def scan_profile_image(file: UploadedFile, strict: bool = True) -> Dict[str, Any]:
    """
    Scan a profile image for security issues.
    
    Args:
        file: Uploaded profile image
        strict: Whether to fail on warnings
    
    Returns:
        Scan result dictionary
    """
    scanner = FileSecurityScanner()
    return scanner.scan_file(file, category='profile_pic', strict=strict)


def validate_uploaded_file(
    file: UploadedFile,
    category: str = 'image',
    raise_exception: bool = True
) -> Dict[str, Any]:
    """
    Validate and scan an uploaded file.
    
    Args:
        file: Uploaded file to validate
        category: File category (image, signature, stamp, document)
        raise_exception: Whether to raise ValidationError on failure
    
    Returns:
        Scan result dictionary
    
    Raises:
        ValidationError: If raise_exception=True and file is unsafe
    """
    scanner = FileSecurityScanner()
    result = scanner.scan_file(file, category=category)
    
    if raise_exception and not result['is_safe']:
        raise ValidationError('; '.join(result['errors']))
    
    return result

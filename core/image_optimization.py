"""
Image optimization utilities for Bengo ERP.
Handles image resizing, compression, format conversion, and CDN integration.
"""

import os
import logging
from PIL import Image, ImageOps
from django.conf import settings
from django.core.files import File
from django.core.files.temp import NamedTemporaryFile
from django.core.files.storage import default_storage
from django.utils import timezone
import hashlib
import mimetypes
from typing import Tuple, Optional, Dict, Any
import io

logger = logging.getLogger(__name__)

class ImageOptimizer:
    """Handles image optimization, resizing, and format conversion"""
    
    def __init__(self):
        self.config = getattr(settings, 'IMAGE_OPTIMIZATION', {})
        self.cdn_config = getattr(settings, 'CDN_CONFIG', {})
        self.supported_formats = self.config.get('FORMATS', ['JPEG', 'JPG', 'PNG', 'WEBP'])
        self.quality = self.config.get('QUALITY', 85)
        self.sizes = self.config.get('SIZES', {})
        self.compression = self.config.get('COMPRESSION', {})
    
    def optimize_image(self, image_file, size_name='medium', format_name=None, quality=None):
        """
        Optimize an image file with specified size and format
        
        Args:
            image_file: File object or path to image
            size_name: Size preset name (thumbnail, small, medium, large, original)
            format_name: Output format (JPEG, PNG, WEBP)
            quality: Compression quality (1-100)
        
        Returns:
            Optimized image file path
        """
        try:
            # Open image
            if isinstance(image_file, str):
                image = Image.open(image_file)
            else:
                image = Image.open(image_file)
            
            # Convert to RGB if necessary
            if image.mode in ('RGBA', 'LA', 'P'):
                # Create white background for transparent images
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = background
            elif image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Resize image
            target_size = self.sizes.get(size_name)
            if target_size and target_size != (None, None):
                image = self._resize_image(image, target_size)
            
            # Determine output format
            if not format_name:
                format_name = self._get_best_format(image, size_name)
            
            # Set quality
            if not quality:
                quality = self.quality
            
            # Optimize image
            optimized_image = self._compress_image(image, format_name, quality)
            
            # Save to temporary file
            temp_file = NamedTemporaryFile(delete=False, suffix=f'.{format_name.lower()}')
            optimized_image.save(temp_file.name, format=format_name, **self._get_compression_options(format_name, quality))
            
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Error optimizing image: {str(e)}")
            return None
    
    def _resize_image(self, image: Image.Image, target_size: Tuple[int, int]) -> Image.Image:
        """Resize image maintaining aspect ratio"""
        if not target_size or target_size == (None, None):
            return image
        
        # Calculate new size maintaining aspect ratio
        original_width, original_height = image.size
        target_width, target_height = target_size
        
        if target_width and target_height:
            # Both dimensions specified
            ratio = min(target_width / original_width, target_height / original_height)
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
        elif target_width:
            # Only width specified
            ratio = target_width / original_width
            new_width = target_width
            new_height = int(original_height * ratio)
        else:
            # Only height specified
            ratio = target_height / original_height
            new_width = int(original_width * ratio)
            new_height = target_height
        
        return image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    def _get_best_format(self, image: Image.Image, size_name: str) -> str:
        """Determine the best format for the image based on content and size"""
        # For thumbnails and small images, prefer JPEG for better compression
        if size_name in ['thumbnail', 'small']:
            return 'JPEG'
        
        # For images with transparency, prefer PNG
        if image.mode == 'RGBA':
            return 'PNG'
        
        # For larger images, prefer WebP if supported
        if 'WEBP' in self.supported_formats:
            return 'WEBP'
        
        # Default to JPEG
        return 'JPEG'
    
    def _compress_image(self, image: Image.Image, format_name: str, quality: int) -> Image.Image:
        """Apply compression to image"""
        # Apply additional optimizations based on format
        if format_name == 'JPEG':
            # Optimize JPEG
            image = ImageOps.exif_transpose(image)  # Fix orientation
        elif format_name == 'PNG':
            # Optimize PNG
            pass  # PIL handles PNG optimization automatically
        
        return image
    
    def _get_compression_options(self, format_name: str, quality: int) -> Dict[str, Any]:
        """Get compression options for specific format"""
        options = {}
        
        if format_name == 'JPEG':
            options.update({
                'quality': quality,
                'progressive': self.compression.get('JPEG', {}).get('progressive', True),
                'optimize': True,
            })
        elif format_name == 'PNG':
            options.update({
                'optimize': self.compression.get('PNG', {}).get('optimize', True),
            })
        elif format_name == 'WEBP':
            options.update({
                'quality': quality,
                'lossless': self.compression.get('WEBP', {}).get('lossless', False),
            })
        
        return options
    
    def generate_responsive_images(self, image_file, base_name=None):
        """
        Generate multiple sizes of an image for responsive design
        
        Args:
            image_file: Original image file
            base_name: Base name for generated files
        
        Returns:
            Dict of size_name: file_path
        """
        if not base_name:
            base_name = f"img_{int(timezone.now().timestamp())}"
        
        responsive_images = {}
        
        for size_name in self.sizes.keys():
            if size_name == 'original':
                continue
                
            optimized_path = self.optimize_image(image_file, size_name)
            if optimized_path:
                # Generate unique filename
                file_hash = self._generate_file_hash(optimized_path)
                filename = f"{base_name}_{size_name}_{file_hash}.{self._get_file_extension(optimized_path)}"
                
                # Save to storage
                with open(optimized_path, 'rb') as f:
                    file_path = default_storage.save(f"optimized/{filename}", File(f))
                    responsive_images[size_name] = file_path
                
                # Clean up temporary file
                os.unlink(optimized_path)
        
        return responsive_images
    
    def _generate_file_hash(self, file_path: str) -> str:
        """Generate hash for file content"""
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()[:8]
    
    def _get_file_extension(self, file_path: str) -> str:
        """Get file extension from path"""
        return os.path.splitext(file_path)[1][1:].lower()


class CDNManager:
    """Manages CDN integration and URL generation"""
    
    def __init__(self):
        self.config = getattr(settings, 'CDN_CONFIG', {})
        self.enabled = self.config.get('ENABLED', False)
        self.domain = self.config.get('DOMAIN', '')
        self.secure = self.config.get('SECURE', True)
        self.provider = self.config.get('PROVIDER', 'cloudfront')
    
    def get_cdn_url(self, file_path: str, size_name: str = None) -> str:
        """
        Generate CDN URL for a file
        
        Args:
            file_path: Path to the file
            size_name: Size variant name (optional)
        
        Returns:
            CDN URL
        """
        if not self.enabled or not self.domain:
            return file_path
        
        # Remove leading slash if present
        if file_path.startswith('/'):
            file_path = file_path[1:]
        
        # Add size suffix if provided
        if size_name and size_name != 'original':
            base_name, ext = os.path.splitext(file_path)
            file_path = f"{base_name}_{size_name}{ext}"
        
        protocol = 'https' if self.secure else 'http'
        return f"{protocol}://{self.domain}/{file_path}"
    
    def get_responsive_image_urls(self, base_path: str, sizes: list = None) -> Dict[str, str]:
        """
        Generate responsive image URLs for different sizes
        
        Args:
            base_path: Base path to the image
            sizes: List of size names to generate URLs for
        
        Returns:
            Dict of size_name: cdn_url
        """
        if sizes is None:
            sizes = ['thumbnail', 'small', 'medium', 'large']
        
        urls = {}
        for size in sizes:
            urls[size] = self.get_cdn_url(base_path, size)
        
        return urls
    
    def invalidate_cache(self, file_paths: list) -> bool:
        """
        Invalidate CDN cache for specified files
        
        Args:
            file_paths: List of file paths to invalidate
        
        Returns:
            Success status
        """
        if not self.enabled:
            return False
        
        try:
            if self.provider == 'cloudfront':
                return self._invalidate_cloudfront(file_paths)
            elif self.provider == 'cloudinary':
                return self._invalidate_cloudinary(file_paths)
            else:
                logger.warning(f"CDN provider {self.provider} not supported for cache invalidation")
                return False
        except Exception as e:
            logger.error(f"Error invalidating CDN cache: {str(e)}")
            return False
    
    def _invalidate_cloudfront(self, file_paths: list) -> bool:
        """Invalidate CloudFront cache"""
        try:
            import boto3
            from botocore.exceptions import ClientError
            
            cloudfront = boto3.client('cloudfront')
            
            # Prepare invalidation paths
            invalidation_paths = []
            for path in file_paths:
                if path.startswith('/'):
                    path = path[1:]
                invalidation_paths.append(f"/{path}")
            
            # Create invalidation
            response = cloudfront.create_invalidation(
                DistributionId=settings.CLOUDFRONT_DISTRIBUTION_ID,
                InvalidationBatch={
                    'Paths': {
                        'Quantity': len(invalidation_paths),
                        'Items': invalidation_paths
                    },
                    'CallerReference': f"bengo-erp-{int(timezone.now().timestamp())}"
                }
            )
            
            logger.info(f"CloudFront invalidation created: {response['Invalidation']['Id']}")
            return True
            
        except ImportError:
            logger.error("boto3 not installed for CloudFront invalidation")
            return False
        except Exception as e:
            logger.error(f"CloudFront invalidation error: {str(e)}")
            return False
    
    def _invalidate_cloudinary(self, file_paths: list) -> bool:
        """Invalidate Cloudinary cache"""
        try:
            import cloudinary
            import cloudinary.api
            
            # Configure Cloudinary
            cloudinary.config(
                cloud_name=settings.CLOUDINARY_CLOUD_NAME,
                api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET
            )
            
            # Invalidate each file
            for path in file_paths:
                public_id = os.path.splitext(path)[0]  # Remove extension
                cloudinary.api.delete_resources([public_id], type='upload')
            
            return True
            
        except ImportError:
            logger.error("cloudinary not installed for Cloudinary invalidation")
            return False
        except Exception as e:
            logger.error(f"Cloudinary invalidation error: {str(e)}")
            return False


# Global instances
image_optimizer = ImageOptimizer()
cdn_manager = CDNManager()


def optimize_and_upload_image(image_file, size_name='medium', format_name=None, quality=None):
    """
    Optimize image and upload to storage
    
    Args:
        image_file: Image file to optimize
        size_name: Size preset name
        format_name: Output format
        quality: Compression quality
    
    Returns:
        Uploaded file path
    """
    try:
        # Optimize image
        optimized_path = image_optimizer.optimize_image(image_file, size_name, format_name, quality)
        if not optimized_path:
            return None
        
        # Generate filename
        timestamp = int(timezone.now().timestamp())
        file_hash = image_optimizer._generate_file_hash(optimized_path)
        extension = image_optimizer._get_file_extension(optimized_path)
        filename = f"optimized_{timestamp}_{file_hash}.{extension}"
        
        # Upload to storage
        with open(optimized_path, 'rb') as f:
            file_path = default_storage.save(f"optimized/{filename}", File(f))
        
        # Clean up temporary file
        os.unlink(optimized_path)
        
        return file_path
        
    except Exception as e:
        logger.error(f"Error optimizing and uploading image: {str(e)}")
        return None


def get_responsive_image_urls(base_path: str, sizes: list = None) -> Dict[str, str]:
    """
    Get responsive image URLs for different sizes
    
    Args:
        base_path: Base path to the image
        sizes: List of size names
    
    Returns:
        Dict of size_name: url
    """
    if sizes is None:
        sizes = ['thumbnail', 'small', 'medium', 'large']
    return cdn_manager.get_responsive_image_urls(base_path, sizes)


def get_cdn_url(file_path: str, size_name: str = None) -> str:
    """
    Get CDN URL for a file
    
    Args:
        file_path: Path to the file
        size_name: Size variant name
    
    Returns:
        CDN URL
    """
    return cdn_manager.get_cdn_url(file_path, size_name)


# Background Removal Utilities

def remove_background_simple(image_file, threshold: int = 240, margin: int = 5) -> Optional[bytes]:
    """
    Remove white/light background from an image using simple thresholding.
    Best for signatures and stamps with clean white backgrounds.
    
    Args:
        image_file: File object or path to image
        threshold: Brightness threshold for transparency (0-255, higher = more aggressive)
        margin: Fuzziness margin for threshold
    
    Returns:
        PNG image bytes with transparent background, or None on error
    """
    try:
        if isinstance(image_file, str):
            img = Image.open(image_file)
        else:
            image_file.seek(0)
            img = Image.open(image_file)
        
        # Convert to RGBA if needed
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Get image data
        data = img.getdata()
        
        new_data = []
        for item in data:
            # Check if pixel is close to white (above threshold)
            r, g, b = item[0], item[1], item[2]
            # Calculate brightness
            brightness = (r + g + b) / 3
            
            if brightness >= threshold - margin:
                # Make transparent (keep RGB, set alpha to 0)
                new_data.append((r, g, b, 0))
            else:
                # Keep original with full opacity
                new_data.append((r, g, b, 255))
        
        img.putdata(new_data)
        
        # Save to bytes
        output = io.BytesIO()
        img.save(output, format='PNG', optimize=True)
        return output.getvalue()
        
    except Exception as e:
        logger.error(f"Error removing background: {e}")
        return None


def remove_background_edge_aware(image_file, tolerance: int = 30) -> Optional[bytes]:
    """
    Remove background using edge-aware flood fill from corners.
    Better for signatures with varying ink colors.
    
    Args:
        image_file: File object or path to image
        tolerance: Color tolerance for flood fill (0-255)
    
    Returns:
        PNG image bytes with transparent background, or None on error
    """
    try:
        if isinstance(image_file, str):
            img = Image.open(image_file)
        else:
            image_file.seek(0)
            img = Image.open(image_file)
        
        # Convert to RGBA
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        width, height = img.size
        data = list(img.getdata())
        
        def get_pixel(x, y):
            if 0 <= x < width and 0 <= y < height:
                return data[y * width + x]
            return None
        
        def set_pixel(x, y, value):
            if 0 <= x < width and 0 <= y < height:
                data[y * width + x] = value
        
        def color_distance(c1, c2):
            return abs(c1[0] - c2[0]) + abs(c1[1] - c2[1]) + abs(c1[2] - c2[2])
        
        # Get background color from corners (sample multiple points)
        corner_samples = [
            get_pixel(0, 0), get_pixel(width-1, 0),
            get_pixel(0, height-1), get_pixel(width-1, height-1),
            get_pixel(5, 5), get_pixel(width-6, 5),
            get_pixel(5, height-6), get_pixel(width-6, height-6)
        ]
        corner_samples = [c for c in corner_samples if c]
        
        if not corner_samples:
            return None
        
        # Average corner colors
        avg_r = sum(c[0] for c in corner_samples) // len(corner_samples)
        avg_g = sum(c[1] for c in corner_samples) // len(corner_samples)
        avg_b = sum(c[2] for c in corner_samples) // len(corner_samples)
        bg_color = (avg_r, avg_g, avg_b)
        
        # Flood fill from corners
        visited = set()
        stack = [(0, 0), (width-1, 0), (0, height-1), (width-1, height-1)]
        
        while stack:
            x, y = stack.pop()
            if (x, y) in visited:
                continue
            if x < 0 or x >= width or y < 0 or y >= height:
                continue
            
            pixel = get_pixel(x, y)
            if not pixel:
                continue
            
            if color_distance(pixel[:3], bg_color) <= tolerance * 3:
                visited.add((x, y))
                # Make transparent
                set_pixel(x, y, (pixel[0], pixel[1], pixel[2], 0))
                # Add neighbors
                stack.extend([(x+1, y), (x-1, y), (x, y+1), (x, y-1)])
        
        # Create new image with processed data
        img.putdata(data)
        
        # Save to bytes
        output = io.BytesIO()
        img.save(output, format='PNG', optimize=True)
        return output.getvalue()
        
    except Exception as e:
        logger.error(f"Error removing background (edge-aware): {e}")
        return None


def remove_background_advanced(image_file) -> Optional[bytes]:
    """
    Remove background using rembg library (AI-based).
    Best quality but requires rembg package.
    
    Args:
        image_file: File object or path to image
    
    Returns:
        PNG image bytes with transparent background, or None on error
    """
    try:
        from rembg import remove
        
        if isinstance(image_file, str):
            with open(image_file, 'rb') as f:
                input_data = f.read()
        else:
            image_file.seek(0)
            input_data = image_file.read()
        
        # Remove background using AI
        output_data = remove(input_data)
        return output_data
        
    except ImportError:
        logger.info("rembg not installed, falling back to simple removal")
        return remove_background_simple(image_file)
    except Exception as e:
        logger.error(f"Error removing background (advanced): {e}")
        return None


def remove_signature_background(image_file, method: str = 'auto') -> Optional[bytes]:
    """
    Remove background from a signature image.
    
    Args:
        image_file: File object or path to signature image
        method: 'simple' (threshold), 'edge' (flood fill), 'advanced' (AI/rembg), or 'auto'
    
    Returns:
        PNG image bytes with transparent background, or None on error
    """
    if method == 'auto':
        # Try advanced first, fall back to simple
        result = remove_background_advanced(image_file)
        if result:
            return result
        return remove_background_simple(image_file)
    elif method == 'simple':
        return remove_background_simple(image_file)
    elif method == 'edge':
        return remove_background_edge_aware(image_file)
    elif method == 'advanced':
        return remove_background_advanced(image_file)
    else:
        return remove_background_simple(image_file)


def remove_stamp_background(image_file, method: str = 'auto') -> Optional[bytes]:
    """
    Remove background from a business stamp image.
    
    Args:
        image_file: File object or path to stamp image
        method: 'simple' (threshold), 'edge' (flood fill), 'advanced' (AI/rembg), or 'auto'
    
    Returns:
        PNG image bytes with transparent background, or None on error
    """
    # Stamps typically have cleaner edges, so edge-aware works well
    if method == 'auto':
        result = remove_background_edge_aware(image_file, tolerance=40)
        if result:
            return result
        return remove_background_simple(image_file, threshold=235)
    elif method == 'simple':
        return remove_background_simple(image_file, threshold=235)
    elif method == 'edge':
        return remove_background_edge_aware(image_file, tolerance=40)
    elif method == 'advanced':
        return remove_background_advanced(image_file)
    else:
        return remove_background_simple(image_file)


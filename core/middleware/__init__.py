"""
Core middleware modules for the ERP application.
"""
import sys
import importlib.util
from pathlib import Path

# Lazy import to avoid AppRegistryNotReady errors during ASGI initialization
# CoreMiddleware is only loaded when explicitly accessed, not at module import time
_CoreMiddleware = None
_CoreMiddleware_module = None

def __getattr__(name):
    """Lazy loader for CoreMiddleware to avoid early Django model imports."""
    if name == 'CoreMiddleware':
        global _CoreMiddleware
        if _CoreMiddleware is None:
            _file_path = Path(__file__).parent.parent / 'middleware.py'
            if _file_path.exists():
                spec = importlib.util.spec_from_file_location('core.middleware_file', _file_path)
                middleware_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(middleware_module)
                _CoreMiddleware = getattr(middleware_module, 'CoreMiddleware')
            else:
                raise ImportError("core/middleware.py file not found")
        return _CoreMiddleware
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = ['CoreMiddleware']


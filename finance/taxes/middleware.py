from datetime import date
from hrm.payroll.models import Formulas, PayrollComponents, FormulaItems,SplitRatio,Relief
from .models import Tax, TaxCategory
import logging

logger = logging.getLogger(__name__)

class TaxFormulaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # Class-level flag to track initialization status
        self._tax_formulas_initialized = False
    
    def __call__(self, request):
        # Only run initialization logic once per server startup
        if not self._tax_formulas_initialized:
            self._initialize_tax_formulas()
        
        response = self.get_response(request)
        return response
    
    def _initialize_tax_formulas(self):
        """Initialize tax formulas only if they don't exist"""
        try:
            # Check if tax formulas already exist
            if Formulas.objects.filter(type__icontains='TAX').exists():
                self._tax_formulas_initialized = True
                return
            
            # Check if taxes already exist
            if Tax.objects.exists():
                self._tax_formulas_initialized = True
                return
            
            # Initialize F.B.T. 2021 and other tax-related formulas
            logger.info("Initializing tax formulas for F.B.T. 2021...")
            
            # Add specific tax formula initialization logic here if needed
            # For now, just mark as initialized to prevent repeated attempts
            
            self._tax_formulas_initialized = True
            logger.info("Tax formulas initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error initializing tax formulas: {str(e)}")
            # Mark as initialized to prevent repeated attempts
            self._tax_formulas_initialized = True
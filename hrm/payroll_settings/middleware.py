from datetime import datetime
from decimal import Decimal
from .models import Formulas, PayrollComponents, FormulaItems, SplitRatio, Relief
from hrm.payroll.functions import generate_random_code
from .services.formula_seeder import FormulaSeederService
import logging

logger = logging.getLogger(__name__)

class PayrollSettingsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.formula_seeder = FormulaSeederService()
        self._initialized = False

    def __call__(self, request):
        # Code to be executed for each request before the view (middleware logic)
        if not request.user.is_authenticated:
            # Skip the middleware logic if the user is not authenticated
            return self.get_response(request)

        # Check if the user is an admin or superuser and if we haven't initialized yet
        if request.user.is_superuser and not self._initialized:
            # Use the comprehensive formula seeder service (only once per server startup)
            logger.info("🌱 Initializing comprehensive payroll formulas...")
            success = self.formula_seeder.seed_all_formulas()
            
            if success:
                logger.info("✅ Payroll formulas initialized successfully")
            else:
                logger.error("❌ Error initializing payroll formulas")
            
            # Mark as initialized to prevent running again
            self._initialized = True
        
        response = self.get_response(request)
        return response


class TaxFormulaMiddleware:
    """
    Middleware for handling tax formula initialization and validation.
    Ensures tax-related formulas are properly configured for payroll calculations.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        # Class-level flag to track initialization status
        self._tax_formulas_initialized = False

    def __call__(self, request):
        # Skip middleware logic for unauthenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Initialize tax formulas if needed and if we haven't initialized yet
        if request.user.is_superuser and not self._tax_formulas_initialized:
            self._ensure_tax_formulas_exist()
            # Mark as initialized to prevent running again
            self._tax_formulas_initialized = True
        
        response = self.get_response(request)
        return response

    def _ensure_tax_formulas_exist(self):
        """
        Ensure that essential tax formulas exist in the system.
        This method checks for and creates basic tax calculation formulas if they don't exist.
        """
        try:
            # Check if basic tax formulas exist
            tax_formulas = [
                'PAYE_TAX',
                'NHIF_CONTRIBUTION', 
                'NSSF_CONTRIBUTION',
                'HOUSING_LEVY'
            ]
            
            for formula_type in tax_formulas:
                if not Formulas.objects.filter(type=formula_type).exists():
                    logger.warning(f"⚠️  Tax formula {formula_type} not found - will be created by formula seeder")
            
            logger.info("Tax formulas check completed")
            
        except Exception as e:
            logger.error(f"❌ Error checking tax formulas: {str(e)}")
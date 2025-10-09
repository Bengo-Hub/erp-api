from datetime import datetime
from decimal import Decimal
from .models import Formulas, PayrollComponents, FormulaItems,SplitRatio,Relief
from .functions import generate_random_code
from hrm.payroll_settings.services.formula_seeder import FormulaSeederService
import logging

logger = logging.getLogger(__name__)

class PayrollFormulaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.formula_seeder = FormulaSeederService()
        # Class-level flag to track initialization status
        self._formulas_initialized = False

    def __call__(self, request):
        # Code to be executed for each request before the view (middleware logic)
        if not request.user.is_authenticated:
            # Skip the middleware logic if the user is not authenticated
            return self.get_response(request)

        # Check if the user is an admin or superuser and if we haven't initialized yet
        if request.user.is_superuser and not self._formulas_initialized:
            # Use the comprehensive formula seeder service (only once per server startup)
            logger.info("🌱 Initializing comprehensive payroll formulas...")
            success = self.formula_seeder.seed_all_formulas()
            
            if success:
                logger.info("✅ Payroll formulas initialized successfully")
            else:
                logger.error("❌ Error initializing payroll formulas")
            
            # Mark as initialized to prevent running again
            self._formulas_initialized = True
        
        response = self.get_response(request)
        return response
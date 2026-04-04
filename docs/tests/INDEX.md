# Module Documentation Index

This directory contains comprehensive documentation for all modules in the Bengo ERP API system.

## Documentation Files

### System-Level Documentation
1. **01_CODEBASE_AUDIT.md** - Comprehensive audit of entire codebase
2. **02_MODULE_DOCUMENTATION.md** - Detailed analysis of each module
3. **03_DELIVERY_NOTE_ENHANCEMENT.md** - Delivery note improvements
4. **04_WORKFLOW_IMPLEMENTATION.md** - Workflow patterns and state machines
5. **05_TESTING_GUIDE.md** - Testing strategy and test suite
6. **06_API_ENDPOINTS.md** - API endpoint documentation
7. **07_DEPLOYMENT_GUIDE.md** - Deployment and operations guide
8. **08_GAPS_AND_FIXES.md** - Identified gaps and recommended fixes

### Quick Reference
- [Module Overview](#module-overview)
- [Setup Instructions](#setup-instructions)
- [Common Tasks](#common-tasks)

## Module Overview

### Finance Module 💰
- Invoicing, payments, accounting, budgeting
- **Status**: ⭐⭐⭐⭐⭐ Mature
- **Coverage**: ~40%
- **Key Files**: invoicing/, payment/, accounts/

### Procurement Module 📦
- Purchase orders, requisitions, supplier management
- **Status**: ⭐⭐⭐⭐ Good
- **Coverage**: ~25%
- **Key Files**: orders/, purchases/, requisitions/

### HRM Module 👥
- Employee management, payroll, leave, recruitment
- **Status**: ⭐⭐⭐⭐ Good
- **Coverage**: ~20%
- **Key Files**: employees/, payroll/, leave/

### Core Module 🔧
- Base classes, utilities, shared services
- **Status**: ⭐⭐⭐⭐ Excellent
- **Coverage**: ~50%
- **Key Files**: base_viewsets.py, models.py, utils.py

### Auth Module 🔐
- Authentication, authorization, security
- **Status**: ⭐⭐⭐⭐⭐ Secure
- **Coverage**: ~70%
- **Key Files**: backends.py, security.py, middleware.py

### CRM Module 📋
- Contact management, relationships
- **Status**: ⭐⭐⭐ Basic
- **Coverage**: ~30%
- **Key Files**: contacts/

## Setup Instructions

```bash
# 1. Clone repository
git clone https://github.com/Bengo-Hub/bengobox-erp-api.git
cd erp-api

# 2. Create virtual environment
python -m venv env
source env/bin/activate  # Windows: env\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. Set up environment
cp .env.example .env
# Edit .env with your settings

# 5. Database setup
python manage.py migrate

# 6. Run tests
pytest

# 7. Start development server
python manage.py runserver
```

## Common Tasks

### Run All Tests
```bash
pytest
pytest --cov=.  # With coverage
pytest -v       # Verbose output
```

### Generate API Documentation
```bash
python manage.py spectacular --file schema.yml
```

### Create Superuser
```bash
python manage.py createsuperuser
```

### Load Demo Data
```bash
python manage.py seed_all
```

## Documentation Navigation

Each module documentation file (02_MODULE_DOCUMENTATION.md onwards) contains:
- Module architecture and structure
- Model definitions and relationships
- API endpoints and serializers
- Workflow and state transitions
- Common operations and patterns
- Known issues and gaps
- Testing strategy
- Performance considerations

---

**Last Updated**: March 1, 2026

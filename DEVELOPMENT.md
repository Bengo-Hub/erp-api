# Development Guide

This guide covers local development setup, common workflows, and troubleshooting.

---

## Local Development Setup

### Prerequisites
- Python 3.11+
- PostgreSQL 12+ (or Docker)
- Redis (or Docker)
- Git
- Virtual environment manager (venv or virtualenv)

### Step 1: Clone & Setup Environment

```bash
# Clone repository
git clone https://github.com/Bengo-Hub/bengobox-erp-api.git
cd bengobox-erp-api

# Create virtual environment
python -m venv env
source env/bin/activate  # Windows: env\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Development tools
```

### Step 2: Database Setup

#### Option A: PostgreSQL Local
```bash
# Create database
createdb bengobox_erp

# Create database user
createuser bengobox_user
# Set password when prompted
```

#### Option B: PostgreSQL Docker
```bash
docker run --name bengobox-db \
  -e POSTGRES_DB=bengobox_erp \
  -e POSTGRES_USER=bengobox_user \
  -e POSTGRES_PASSWORD=secure_password \
  -p 5432:5432 \
  -d postgres:15
```

#### Option C: Redis Docker
```bash
docker run --name bengobox-redis \
  -p 6379:6379 \
  -d redis:7
```

### Step 3: Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit with your settings
# Key variables to set:
# - DATABASE_URL=postgresql://bengobox_user:password@localhost/bengobox_erp
# - REDIS_URL=redis://localhost:6379
# - SECRET_KEY=your-django-secret-key
# - DEBUG=True (for development only)
```

### Step 4: Database Migrations

```bash
# Run migrations
python manage.py migrate

# Verify migrations applied
python manage.py showmigrations

# Create superuser
python manage.py createsuperuser

# Load demo data (optional)
python manage.py seed_all
```

### Step 5: Start Development Server

```bash
# Terminal 1: Django server
python manage.py runserver

# Terminal 2: Celery worker (for async tasks)
celery -A ProcureProKEAPI worker -l info

# Terminal 3: Celery beat (for scheduled tasks)
celery -A ProcureProKEAPI beat -l info
```

Access API at: `http://localhost:8000/api/v1/`  
Admin panel at: `http://localhost:8000/admin/`  
Swagger docs at: `http://localhost:8000/api/schema/swagger/`

---

## Common Development Tasks

### Creating a New App

```bash
# Create Django app
python manage.py startapp new_feature

# Add to INSTALLED_APPS in settings.py
INSTALLED_APPS = [
    # ...
    'new_feature',
]

# Create basic structure
mkdir -p new_feature/tests
touch new_feature/__init__.py
touch new_feature/models.py
touch new_feature/serializers.py
touch new_feature/views.py
touch new_feature/urls.py
touch new_feature/tests/__init__.py
touch new_feature/tests/test_models.py
touch new_feature/tests/test_views.py
```

### Creating Models

```python
# new_feature/models.py
from django.db import models
from core.models import BaseModel  # Inherits id, created_at, updated_at

class MyModel(BaseModel):
    """Brief description of model"""
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    class Meta:
        verbose_name = "My Model"
        verbose_name_plural = "My Models"
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
```

### Creating Serializers

```python
# new_feature/serializers.py
from rest_framework import serializers
from .models import MyModel

class MyModelSerializer(serializers.ModelSerializer):
    """Serialize MyModel"""
    
    class Meta:
        model = MyModel
        fields = ['id', 'name', 'description', 'created_at']
        read_only_fields = ['id', 'created_at']
```

### Creating ViewSets

```python
# new_feature/views.py
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from core.base_viewsets import BaseModelViewSet
from .models import MyModel
from .serializers import MyModelSerializer

class MyModelViewSet(BaseModelViewSet):
    """Create, list, and manage MyModel instances"""
    queryset = MyModel.objects.all()
    serializer_class = MyModelSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ['name']
    ordering_fields = ['created_at']
```

### Registering URLs

```python
# new_feature/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MyModelViewSet

router = DefaultRouter()
router.register(r'my-models', MyModelViewSet, basename='my-model')

urlpatterns = [
    path('', include(router.urls)),
]

# Then add to ProcureProKEAPI/urls.py
urlpatterns = [
    # ...
    path('api/v1/new-feature/', include('new_feature.urls')),
]
```

### Creating Migrations

```bash
# Detect model changes
python manage.py makemigrations

# Review migration file
# Modify if needed (e.g., data migrations)

# Apply migrations
python manage.py migrate

# Rollback if needed
python manage.py migrate new_feature 0001  # Specify last working migration
```

### Writing Tests

```python
# new_feature/tests/test_models.py
from django.test import TestCase
from new_feature.models import MyModel

class MyModelTests(TestCase):
    def setUp(self):
        self.model = MyModel.objects.create(name="Test")
    
    def test_string_representation(self):
        self.assertEqual(str(self.model), "Test")

# new_feature/tests/test_views.py
from rest_framework.test import APITestCase
from rest_framework import status
from new_feature.models import MyModel
from django.contrib.auth import get_user_model

User = get_user_model()

class MyModelAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='test@example.com')
        self.client.force_authenticate(user=self.user)
    
    def test_list_models(self):
        MyModel.objects.create(name="Test1")
        response = self.client.get('/api/v1/new-feature/my-models/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific module
pytest new_feature/tests/

# Run with coverage
pytest --cov=new_feature

# Run specific test
pytest new_feature/tests/test_models.py::MyModelTests::test_string_representation

# Run failing tests only
pytest --lf
```

---

## Code Quality Tools

### Code Formatting (Black)

```bash
# Format all Python files
black .

# Format specific directories
black new_feature/

# Check without formatting
black --check .
```

### Import Sorting (isort)

```bash
# Sort imports
isort .

# Check without sorting
isort --check .
```

### Linting (Flake8)

```bash
# Check code style
flake8 .

# Check specific directory
flake8 new_feature/

# Ignore specific rules
flake8 --ignore=E501,W503 .
```

### Pre-commit Hooks (Optional)

```bash
# Install pre-commit
pip install pre-commit

# Setup hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

---

## Database Management

### Creating Fixtures for Tests

```bash
# Export data to JSON
python manage.py dumpdata auth.user > fixtures/users.json

# Load fixtures in tests
from django.test import TestCase
from django.test.utils import setup_test_environment

class MyTests(TestCase):
    fixtures = ['users.json']
```

### Inspecting Database

```bash
# Shell with Django context
python manage.py shell
>>> from new_feature.models import MyModel
>>> MyModel.objects.all()

# Database client
psql -d bengobox_erp -U bengobox_user
```

### Resetting Database

```bash
# Drop and recreate (careful!)
python manage.py flush --no-input
python manage.py migrate
python manage.py seed_all
```

---

## Troubleshooting

### Issue: "No module named 'collections.abc.MutableMapping'"

**Solution:**
```bash
pip install --upgrade apns2
# or uninstall if not needed
pip uninstall apns2
```

### Issue: PostgreSQL connection refused

**Solution:**
```bash
# Check if PostgreSQL is running
psql -l

# Start PostgreSQL (macOS)
brew services start postgresql

# Start Docker container
docker start bengobox-db

# Check .env DATABASE_URL is correct
```

### Issue: Redis connection error

**Solution:**
```bash
# Check Redis is running
redis-cli ping

# Start Docker container
docker start bengobox-redis

# Check REDIS_URL in .env
```

### Issue: Migration errors

**Solution:**
```bash
# Check migration status
python manage.py showmigrations
python manage.py showmigrations app_name

# Undo last migration
python manage.py migrate app_name 0001

# Create empty migration for manual data changes
python manage.py makemigrations --empty app_name --name fix_data
```

### Issue: Tests failing

**Solution:**
```bash
# Reset test database
python manage.py flush --no-input

# Run with verbose output
pytest -v

# Run specific test for debugging
pytest -v -s new_feature/tests/test_models.py::TestCase::test_method

# Check test database is separate
pytest --ds=your_test_settings
```

---

## IDE Setup

### VS Code
```json
{
  "python.formatting.provider": "black",
  "python.linting.flake8Enabled": true,
  "python.linting.flake8Args": ["--ignore=E501"],
  "python.testing.pytestEnabled": true,
  "[python]": {
    "editor.formatOnSave": true,
    "editor.defaultFormatter": "ms-python.python"
  }
}
```

### PyCharm
- Settings → Project → Python Interpreter → Select venv
- Settings → Tools → Python Integrated Tools → Testing → Pytest
- Settings → Code Style → Import arrangement → Enable isort

---

## Git Workflow

### Starting a Feature

```bash
# Create feature branch
git checkout -b feature/my-feature

# Make changes and test
# ...

# Commit changes (follow commit message guidelines)
git add .
git commit -m "feat(module): description of changes"

# Push to remote
git push origin feature/my-feature

# Create Pull Request
# Fix any CI/CD issues
# Request code review
```

### Keeping Updated

```bash
# Fetch latest changes
git fetch origin

# Rebase on main (if working on feature)
git rebase origin/main

# Merge if conflicts
git mergetool  # or manual merge
```

---

## Performance Tips

1. **Use select_related/prefetch_related** for queries with relations
2. **Add database indexes** for frequently filtered fields
3. **Use caching** for expensive operations via Redis
4. **Batch operations** with bulk_create/bulk_update
5. **Monitor query count** with django-debug-toolbar
6. **Use async tasks** for slow operations via Celery

---

## Security Checklist

- [ ] Never commit `.env` or secrets
- [ ] Use environment variables for configuration
- [ ] Validate user input in serializers
- [ ] Check permissions in views
- [ ] Use `@transaction.atomic` for critical operations
- [ ] Add CSRF protection to forms
- [ ] Use HTTPS in production
- [ ] Keep dependencies updated
- [ ] Review security advisories

---

**Need help?** Check the main [README.md](./README.md) or open an issue on GitHub.

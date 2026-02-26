# Contributing to Bengobox ERP API

Welcome! We're excited that you're interested in contributing. This document provides guidelines and instructions for contributing to the project.

---

## Code of Conduct

Please be respectful and professional. We enforce a zero-tolerance policy for harassment, discrimination, or any form of disrespect.

---

## How to Contribute

### 1. Reporting Bugs

**Before creating a bug report, please check the issue list** as you might find out that you don't need to create one.

**How Do I Submit A Good Bug Report?**
Explain the problem and include additional details:
- **Use a clear and descriptive title**
- **Describe the exact steps which reproduce the problem**
- **Provide specific examples to demonstrate the steps**
- **Describe the behavior you observed after following the steps**
- **Explain which behavior you expected to see instead and why**
- **Include screenshots if possible**
- **Include your environment details:**
  - OS and version
  - Python version
  - Django version
  - Any relevant package versions

### 2. Suggesting Enhancements

**Use a clear and descriptive title**
**Provide a step-by-step description of the suggested enhancement**
**Explain why this enhancement would be useful**
**List similar features in other applications if applicable**

### 3. Pull Requests

#### Before You Start
1. **Check existing PRs** to avoid duplicate work
2. **Create an issue** first if there isn't one already
3. **Get feedback** from maintainers before starting major work

#### Making Changes

1. **Fork the repository:**
```bash
git clone https://github.com/Bengo-Hub/bengobox-erp-api.git
cd bengobox-erp-api
```

2. **Create a feature branch:**
```bash
git checkout -b feature/short-description
```
Branch naming convention:
- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation
- `refactor/description` - Code refactoring
- `test/description` - Adding tests

3. **Make your changes:**
- Follow the [Code Style Guidelines](#code-style-guidelines)
- Write clear, readable code
- Add comments for complex logic
- Keep commits atomic and focused

4. **Write or update tests:**
- Add unit tests for new features
- Update tests if changing existing functionality
- Ensure all tests pass locally:
```bash
pytest
pytest authmanagement/tests/  # For specific module
```

5. **Update documentation:**
- Update applicable `.md` files
- Update docstrings
- Update CHANGELOG.md with your changes
- Add comments for complex logic

6. **Commit your changes:**
```bash
git add .
git commit -m "feat(module): clear description of changes"
```
See [Commit Message Format](#commit-message-format)

7. **Push to your fork:**
```bash
git push origin feature/short-description
```

8. **Create a Pull Request:**
- Link to related issues
- Provide a clear description of changes
- Include any breaking changes
- Reference relevant documentation

#### Pull Request Checklist
- [ ] Change follows project code style
- [ ] All tests pass locally (`pytest`)
- [ ] Added tests for new functionality
- [ ] Updated documentation (if needed)
- [ ] Updated CHANGELOG.md
- [ ] No console errors or warnings
- [ ] Commits are clear and descriptive

---

## Code Style Guidelines

### Python Code Style

We follow **PEP 8** with these tools:

#### Black (Code Formatting)
```bash
# Auto-format files
black authmanagement/serializers.py

# Check if files are formatted
black --check .
```

#### Flake8 (Linting)
```bash
# Check for style issues
flake8 authmanagement/

# Exclude certain checks
flake8 --ignore=E501,W503 .
```

#### isort (Import Ordering)
```bash
# Auto-sort imports
isort authmanagement/views.py

# Check if imports are sorted
isort --check .
```

### Django & DRF Conventions

1. **Model Fields:**
```python
# Good
class Invoice(models.Model):
    invoice_number = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        help_text="Auto-generated invoice number"
    )
    
    class Meta:
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        ordering = ["-created_at"]
```

2. **Serializers:**
```python
# Good
class InvoiceSerializer(serializers.ModelSerializer):
    """Serialize Invoice model with validation"""
    customer_details = ContactSerializer(source='customer', read_only=True)
    
    class Meta:
        model = Invoice
        fields = ['id', 'invoice_number', 'customer_details', ...]
        read_only_fields = ['invoice_number', 'created_at']
    
    def validate_payment_terms(self, value):
        """Validate payment terms"""
        if value not in ['due_on_receipt', 'net_30']:
            raise serializers.ValidationError("Invalid payment terms")
        return value
```

3. **Views:**
```python
# Good
class InvoiceViewSet(BaseModelViewSet):
    """Create, list, and manage invoices"""
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['status', 'invoice_date']
    search_fields = ['invoice_number', 'customer__business_name']
```

4. **Comments & Docstrings:**
```python
def create_invoice_from_quotation(quotation, user):
    """
    Create an invoice from an existing quotation.
    
    This function:
    1. Clones quotation details to invoice
    2. Generates unique invoice number
    3. Sets payment terms
    4. Creates audit log
    
    Args:
        quotation: Quotation instance to convert
        user: User creating the invoice
    
    Returns:
        Invoice: Newly created invoice instance
    
    Raises:
        ValueError: If quotation has invalid status
        IntegrityError: If invoice number generation fails
    """
    # Implementation...
```

---

## Commit Message Format

Follow the conventional commit format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Format Rules

**Type:** One of
- `feat` - A new feature
- `fix` - A bug fix
- `docs` - Documentation changes
- `style` - Code style changes (Black, isort)
- `refactor` - Code refactoring without feature changes
- `test` - Adding or updating tests
- `chore` - Maintenance tasks, dependency updates

**Scope:** The module affected (auth, finance, hrm, etc.)

**Subject:**
- Use imperative mood ("add" not "added")
- Don't capitalize first letter
- No period (.) at the end
- Limit to 50 characters

**Body:** (Optional)
- Explain what and why, not how
- Wrap at 72 characters
- Separate from subject with blank line

**Footer:** (Optional)
- Reference issues: `Fixes #123`
- Breaking changes: `BREAKING CHANGE: description`

### Examples

```
feat(auth): add two-factor authentication support
fix(invoicing): correct tax calculation for net amounts
docs(readme): add deployment instructions
refactor(core): simplify audit logging
test(auth): add tests for user creation with groups
```

---

## Testing Guidelines

### Writing Tests

```python
# Location: module/tests/test_feature.py

from django.test import TestCase
from rest_framework.test import APIClient
from module.models import Model

class ModelTests(TestCase):
    """Tests for Model functionality"""
    
    def setUp(self):
        """Setup test fixtures"""
        self.model = Model.objects.create(name="Test")
    
    def test_model_creation(self):
        """Test that model is created correctly"""
        self.assertEqual(self.model.name, "Test")
        self.assertTrue(self.model.id)
    
    def test_model_validation(self):
        """Test model field validation"""
        with self.assertRaises(ValidationError):
            Model.objects.create(name="")  # Required field

class APIEndpointTests(TestCase):
    """Tests for API endpoints"""
    
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@example.com')
        self.client.force_authenticate(user=self.user)
    
    def test_list_endpoint(self):
        """Test GET list endpoint"""
        response = self.client.get('/api/models/')
        self.assertEqual(response.status_code, 200)
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest authmanagement/tests/test_user_creation.py

# Run specific test class
pytest authmanagement/tests/test_user_creation.py::TestUserCreation

# Run specific test method
pytest authmanagement/tests/test_user_creation.py::TestUserCreation::test_create_user

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=. --cov-report=html

# Run only failed tests
pytest --lf
```

---

## Documentation Guidelines

### Markdown Files

- Use clear, descriptive headings
- Keep lines under 100 characters
- Use code blocks for examples
- Link to related documentation
- Update .md files alongside code changes

### API Documentation

- Use Black for Python code examples
- Include request and response examples
- Document error responses
- Include example curl commands

### Docstrings

Use Google-style docstrings:
```python
def function_name(param1, param2):
    """Brief description.
    
    Longer description if needed. Explain what the function does
    and any important details about its behavior.
    
    Args:
        param1 (str): Description of param1
        param2 (int): Description of param2
    
    Returns:
        dict: Description of return value
    
    Raises:
        ValueError: When condition X occurs
        KeyError: When key not found
    
    Example:
        >>> result = function_name("test", 42)
        >>> print(result)
        {'status': 'success'}
    """
```

---

## Review Process

### What Reviewers Look For

1. **Code Quality**
   - Follows project style guidelines
   - No syntax errors
   - Readable and maintainable
   
2. **Functionality**
   - Solves the stated problem
   - No regressions
   - Handles edge cases
   
3. **Testing**
   - Adequate test coverage
   - Tests pass locally
   - Tests are meaningful
   
4. **Documentation**
   - Code is well documented
   - README/docs updated
   - CHANGELOG updated

### Addressing Review Comments

- Thank reviewers for feedback
- Respond to all comments
- Make requested changes
- Push new commits (don't force push)
- Re-request review when ready

---

## Development Workflow

### Setup Development Environment

```bash
# Clone and setup venv
git clone https://github.com/Bengo-Hub/bengobox-erp-api.git
cd bengobox-erp-api
python -m venv env
source env/bin/activate  # Windows: env\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Setup pre-commit hooks (optional but recommended)
pre-commit install

# Create .env file
cp .env.example .env
```

### Running Development Server

```bash
# Apply migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Load demo data (optional)
python manage.py seed_all

# Start server
python manage.py runserver
```

Access at: `http://localhost:8000`

### Before Committing

```bash
# Format code
black .
isort .

# Check code style
flake8 .

# Run tests
pytest

# Check migrations
python manage.py makemigrations --check
```

---

## Need Help?

- **Questions:** Open a discussion on GitHub
- **Issues:** Create an issue with details
- **Documentation:** Check docs/ folder
- **Email:** support@bengobox.co.ke

---

**Thank you for contributing to Bengobox ERP API!** 🎉

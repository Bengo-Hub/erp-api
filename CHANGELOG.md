# Changelog

All notable changes to the Bengobox ERP API project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added - Features
- Enhanced DeliveryNote creation serializer supporting standalone DN creation with customer/branch/items
- Explicit delivery note to invoice linking endpoint (`/api/delivery-notes/{id}/link-to-invoice/`)
- Status synchronization rules for Invoice and DeliveryNote documents
- Comprehensive invoice and delivery note workflow analysis documentation

### Fixed - Bug Fixes
- **[CRITICAL]** Fixed user creation M2M error: "CustomUser needs to have a value for field id" (#243)
  - Added `@transaction.atomic` decorator to `UserSerializer.create()`
  - Fixed double-save issue that caused transaction isolation problems
  - Extracted `_assign_groups_to_user()` helper method
  - Improved error handling with proper rollback on failure
  - Added comprehensive validation for groups, password, email
  
- Fixed apns2 package compatibility issue with Python 3.11+ (MutableMapping not in collections)
- Fixed POS.Sales date fields using fixed defaults instead of `timezone.now`
- Fixed payroll_settings M2M field warnings (removed ineffective null=True)
- Fixed seed script business_details owner_id constraint violation
- Improved seed script error handling and warnings reporting

### Changed - Breaking Changes
- None

### Deprecated - Deprecations
- None

### Removed - Removed Features
- Removed jsmin from requirements.txt (package incompatible with Python 3.11+)

### Security - Security Fixes
- Added password validation against PasswordPolicy in user creation
- Added email uniqueness validation (case-insensitive)
- Added transaction atomicity for user creation to prevent partial data
- Improved error messages to not leak sensitive information

---

## [1.0.0] - 2024-01-15

### Added - Features (Initial Release)
- Core ERP modules: Financial, HRM, Procurement, Inventory
- JWT-based authentication with role-based access control
- Multi-tenant support with branch-level organization
- Invoice management with approval workflows
- Complete API documentation with Swagger/OpenAPI
- Comprehensive test coverage for all modules
- Docker and Kubernetes deployment configs
- Database migration system for PostgreSQL
- Audit logging for all transactions
- Email integration for notifications
- PDF generation for documents

### Fixed - Bug Fixes (Initial Release)
- Resolved PostgreSQL connection pooling issues
- Fixed timezone handling across modules
- Corrected decimal field precision in financial calculations
- Fixed search functionality with special characters

### Added - Documentation
- README.md with project overview
- CONTRIBUTING.md with contribution guidelines
- Setup documentation for development
- API endpoint reference
- Database schema documentation
- Deployment guides for Docker/Kubernetes

---

## Version Format

```
## [Version] - YYYY-MM-DD

### Added - Features
- ...

### Fixed - Bug Fixes
- ...

### Changed - Breaking Changes
- ...

### Deprecated - Deprecations
- ...

### Removed - Removed Features
- ...

### Security - Security Fixes
- ...
```

---

## Guidelines for Maintainers

### When to Update Changelog

Update the changelog when:
- Adding new features
- Fixing bugs (especially critical ones)
- Deprecating functionality
- Making breaking changes
- Fixing security issues
- Updating major dependencies

Do NOT update for:
- Trivial code refactoring
- Comment/docstring updates
- Test-only changes
- CI/CD configuration changes

### Changelog Principles

1. **User-Focused:** Write for end users, not developers
2. **Organized:** Group related changes together
3. **Searchable:** Include issue numbers and clear descriptions
4. **Honest:** Describe actual impact, not just code changes
5. **Actionable:** Migration paths for breaking changes
6. **Dated:** Always include dates in YYYY-MM-DD format

### Example Entry

```markdown
### Fixed - Bug Fixes
- Fixed user creation error when assigning groups (#243)
  - Added transaction atomicity
  - User M2M operations now safe
  - Improves stability when bulk creating users
```

---

## Release Process

1. **Update CHANGELOG.md** with all unreleased changes
2. **Update version** in ProcureProKEAPI/settings.py
3. **Create git tag**: `git tag v1.0.1`
4. **Push tag**: `git push origin v1.0.1`
5. **Build Docker image** with new tag
6. **Deploy** to staging, then production

---

## Past Releases

See [GitHub Releases](https://github.com/Bengo-Hub/bengobox-erp-api/releases) for past versions and detailed release notes.

---

**Last Updated:** February 26, 2024

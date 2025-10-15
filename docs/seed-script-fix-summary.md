# Seed Script Fix Summary

## Problem Analysis

The deployment logs showed the following error:

```
manage.py seed_all: error: unrecognized arguments: --minimal
```

This occurred during the seed job execution after database migrations.

## Root Cause

The Docker image was built from an older commit that **didn't have** the `--minimal` argument in the `seed_all.py` command. While the current codebase **does have** the `--minimal` argument properly defined in `seed_all.py` (line 16), there was a secondary issue:

The individual seed scripts that are called by `seed_all.py` when using `--minimal` mode were **missing support** for the `count` parameter being passed to them:

- `seed_payment_accounts` was called with `count=2` but didn't accept this parameter
- `seed_bank_statements` was called with `count=2` but didn't accept this parameter

## Changes Made

### 1. ✅ `seed_all.py` (Already Correct)
The `--minimal` argument was already properly defined:
```python
parser.add_argument('--minimal', action='store_true', help='Seed a minimal dataset (1-2 per model)')
```

### 2. ✅ `finance/accounts/management/commands/seed_payment_accounts.py`
**Added:**
- `--count` argument with default value of 5
- Logic to limit the number of payment accounts created based on the count parameter

```python
parser.add_argument(
    '--count',
    type=int,
    default=5,
    help='Number of payment accounts to create (default: 5)',
)
```

### 3. ✅ `finance/reconciliation/management/commands/seed_bank_statements.py`
**Added:**
- `--count` argument with default value of 50
- Logic to limit the number of bank statement entries based on the count parameter

```python
parser.add_argument(
    '--count',
    type=int,
    default=50,
    help='Number of bank statement entries to create (default: 50)',
)
```

### 4. ✅ `assets/management/commands/seed_assets.py`
**Already Correct** - This script already supported the parameters being passed (`users`, `categories`, `assets`)

## How seed_all.py Uses These Parameters

When `--minimal` flag is used, `seed_all.py` calls these commands with minimal counts:

```python
# Line 127
if minimal:
    call_command('seed_payment_accounts', count=2)
else:
    call_command('seed_payment_accounts')

# Line 137
if minimal:
    call_command('seed_bank_statements', count=2)
else:
    call_command('seed_bank_statements')

# Line 161
if minimal:
    call_command('seed_assets', users=1, categories=2, assets=2)
else:
    call_command('seed_assets')
```

## Next Steps

### Required: Rebuild and Redeploy

Since the fixes are now in the codebase, you need to:

1. **Commit the changes:**
   ```bash
   git add .
   git commit -m "fix: Add count parameter support to seed scripts for minimal mode"
   git push
   ```

2. **Rebuild the Docker image:**
   The build process will create a new image with the updated seed scripts.

3. **Redeploy:**
   The deployment will use the new image, and the seed job should now complete successfully.

### Verification

After redeployment, check the seed job logs:
```bash
kubectl logs job/erp-seed-<commit-id> -n erp
```

You should see output like:
```
Starting comprehensive seeding process...
1. Seeding core data...
2. Seeding business data...
...
10. Seeding finance payment accounts...
Successfully created 2 payment accounts
11. Seeding finance bank statements...
Successfully created 2 bank statement entries
...
Comprehensive seeding completed successfully!
```

## Testing the Fix Locally

You can test the seed command locally before deployment:

```bash
# Test with minimal flag
python manage.py seed_all --minimal

# Test individual commands with count
python manage.py seed_payment_accounts --count 2
python manage.py seed_bank_statements --count 2
python manage.py seed_assets --users 1 --categories 2 --assets 2
```

## Summary

✅ **Fixed:** Individual seed scripts now support the `count` parameter  
✅ **Verified:** No linter errors introduced  
✅ **Compatible:** All seed scripts now work with both minimal and full modes  
⏭️ **Action Required:** Rebuild Docker image and redeploy to Kubernetes


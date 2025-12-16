# Branch/Business FK Migration Checklist

This checklist enumerates recommended model changes that should be applied with Django migrations once code changes are final. Do NOT create migrations here; generate them with `makemigrations` and run `migrate` in your environment after review and backups.

1) finance.payment.Payment
   - Add: `branch = models.ForeignKey('business.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')`
   - Rationale: many payment queries need direct branch lookup to simplify reporting and avoid joining to BillingDocument/Order.
   - Backfill: Use existing `document__branch`, `sale__register__branch` or related objects to populate Payment.branch via a data migration.

2) finance.accounts.Transaction / TransactionPayment
   - Add: `branch` to allow direct accounting reports by branch.
   - Rationale: simplifies tracing money in/out per branch.
   - Backfill: infer from linked payment->document->branch or payment.sale.register.branch.

3) analytics/reporting tables (if applicable)
   - Add branch and business columns where missing to speed up queries and enable partitioning.

4) procurement models (where missing)
   - Ensure `Purchase`, `PurchaseOrder` have `branch` (many already do). Add where absent.
   - Backfill: infer from linked `purchaseitems__stock_item__branch` or PO context.

5) POS / sales
   - Confirm `Sales` has branch via `register.branch`. Consider denormalizing to `branch` on `Sales` for faster filtering/reporting.
   - Backfill: set `sales.branch = sales.register.branch` in migration.

6) HRM / employees
   - Employees use `hr_details.branch` relations; no immediate changes required.

7) Backfill strategy
   - Create reversible data migrations that set the new `branch` fields by inferring from existing relationships, and leave null where inference is impossible.
   - After a stabilization window, mark `null=False` if desired and add `default` or require manual assignment for remaining records.

8) Testing & Rollout
   - Run migrations in a staging environment and validate reporting, payments, and checkout flows.
   - Add unit tests that verify branch filtering works directly on the new fields.

---

If you want, I can prepare the exact Django `makemigrations` commands and data migration templates (but I will not create migration files until you confirm).
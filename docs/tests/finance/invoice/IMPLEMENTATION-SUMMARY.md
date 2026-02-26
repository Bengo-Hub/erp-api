# Invoice & Delivery Note Workflow - Quick Reference & Action Items

**Target Audience:** Project managers, development team leads, QA  
**Urgency:** Medium (enables advanced invoice workflows)  
**Last Updated:** 2024

---

## Executive Summary

The Bengobox ERP Invoice/Delivery Note module currently supports the traditional **invoice-first workflow** but lacks support for:
- **Pre-invoice delivery notes** (ASN pattern used in manufacturing/wholesale)
- **Standalone delivery note creation** (with customer/branch/items)
- **Explicit DN→Invoice linking** (for post-creation association)
- **Status synchronization rules** (prevents contradictory document states)

This document provides a roadmap to implement these features in 2-3 sprints with minimal risk.

---

## Current State Assessment

### ✅ What Works (Invoice-First Workflow)
```
User Flow:
1. Create Invoice → 2. Send to customer → 3. Create DN from invoice → 4. Mark delivered
Result: Normal B2B workflow - works well
```

**All components functional:**
- Invoice creation, approval, payment tracking
- Automatic status updates (draft → sent → viewed → paid/overdue)
- PDF generation and email sending
- Payment gateway integration
- Recurring invoices

### ⚠️ What's Incomplete
```
User Flow:
1. Create DN → 2. Create Invoice → 3. Link DN to invoice
Result: Partially works - many manual steps required
```

**Known Issues:**
| Issue | Impact | Effort to Fix | Priority |
|-------|--------|---------------|----------|
| Can't create standalone DN with customer/branch/items via API | Blocks pre-invoice workflows | Medium | P2.1 |
| No explicit endpoint to link pre-created DN to invoice | Requires manual DB updates | Low | P2.2 |
| No status sync between Invoice and DN | Risk of contradictory states | High | P3.1 |
| Email not implemented for DN | Can't send ASN to customer | Medium | P3.2 |

---

## Recommended Roadmap

### Sprint 1: Enable Parallel Invoice & DN Creation (2-3 days)

**Task P2.1: Enhance DeliveryNoteCreateSerializer**

**What:**
- Expose `customer_id` and `branch_id` fields in DeliveryNoteCreateSerializer
- Allow `items` array to be specified during DN creation
- Add validation to require customer/branch for standalone DNs

**Why:**
- Enables warehouse teams to create DNs independently
- Prerequisite for pre-invoice flows

**Where:**
- File: `finance/invoicing/serializers.py`
- File: `finance/invoicing/views.py`
- No database migrations needed

**Test:**
```bash
curl -X POST http://localhost:8000/api/delivery-notes/ \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": 123,
    "branch_id": 456,
    "delivery_address": "123 Main St",
    "driver_name": "John Doe",
    "items": [
      {"name": "Item A", "quantity": 5, "unit_price": 100}
    ]
  }'
```

**Acceptance Criteria:**
- [ ] DN created with customer/branch/items in single request
- [ ] Validation prevents DN without customer (if no source doc)
- [ ] Items are properly linked to DN
- [ ] Existing invoice-from-DN endpoint still works

**Effort:** 16 hours (2 days)  
**Risk:** LOW (serializer-only changes, no DB migrations)

---

**Task P2.2: Add link-to-invoice Endpoint**

**What:**
- New action endpoint: `POST /api/delivery-notes/{id}/link-to-invoice/`
- Validates customer matches, items compatible
- Creates audit log of linking action

**Why:**
- Allows retroactive DN→Invoice association
- Supports workflows where DN created before invoice

**Where:**
- File: `finance/invoicing/views.py`
- Add @action to DeliveryNoteViewSet

**Test:**
```bash
curl -X POST http://localhost:8000/api/delivery-notes/200/link-to-invoice/ \
  -d '{"invoice_id": 100}'
```

**Acceptance Criteria:**
- [ ] DN linked to invoice with validation
- [ ] Cannot link if customers don't match
- [ ] Audit trail recorded
- [ ] Can unlink if needed

**Effort:** 8 hours (1 day)  
**Risk:** LOW (new endpoint, doesn't affect existing flows)

---

### Sprint 2: Add Status Synchronization (3-5 days)

**Task P3.1: Implement Workflow Rules**

**What:**
- Add `finance/invoicing/workflow.py` with business rules
- Validate status transitions (draft→sent→viewed→paid, etc.)
- Cascade status changes (cancel invoice → cancel DNs)
- Prevent payment without delivery confirmation

**Why:**
- Prevents contradictory states (e.g., paid invoice with cancelled DN)
- Enforces real-world business logic
- Basis for future compliance (audit, tax reporting)

**Where:**
- File: `finance/invoicing/workflow.py` (new)
- File: `finance/invoicing/models.py` (signal handlers)

**Acceptance Criteria:**
- [ ] Cannot mark invoice paid without delivered DN
- [ ] Cancelling invoice cascades to DNs
- [ ] Status transitions validated
- [ ] Audit trail of rule violations
- [ ] All existing workflows still work

**Effort:** 24 hours (3 days)  
**Risk:** MEDIUM (complex business logic, needs thorough testing)

---

### Sprint 3: Email Automation (3-4 days, Optional)

**Task P3.2: Implement Email Notifications**

**What:**
- Celery task to email DN to customer (ASN notification)
- Celery task to email invoice after DN delivered
- Email templates for DN

**Why:**
- Notifies customer of shipment before invoice
- Drives pre-invoice workflow

**Where:**
- File: `finance/invoicing/tasks.py` (new)
- File: `templates/finance/emails/delivery_note.html` (new)

**Acceptance Criteria:**
- [ ] DN email sent when DN created/marked in_transit
- [ ] Invoice email sent when DN marked delivered
- [ ] Email templates match brand
- [ ] Celery tasks execute without errors

**Effort:** 20 hours (2.5 days)  
**Risk:** LOW (email is async, failures don't block API)

---

## Real-World Scenarios Addressed

| Scenario | Current | With P2 | With P3 | Example |
|----------|---------|---------|---------|---------|
| Invoice-first (create INV, then DN) | ✅ | ✅ | ✅ | Normal B2B |
| Parallel (create INV and DN together) | ❌ | ✅ | ✅ | Fast-moving retail |
| Pre-invoice (DN before INV) | ❌ | ⚠️ | ✅ | Wholesale distribution |
| Multiple DNs → 1 Invoice | ❌ | ⚠️ | ✅ | Phased shipments |

---

## Dependencies & Prerequisites

### Already in Place ✅
- Django REST Framework (DRF) with ModelViewSet
- Celery for async tasks
- Email templates infrastructure
- Audit trail system (AuditTrail)
- PaymentGateway integration
- PDF generation (reportlab)

### Needed for Full Implementation
- [ ] Email SMTP configuration (for P3.2)
- [ ] Celery workers running (for P3.2)
- [ ] Staging environment for testing

---

## Risk Assessment

### P2.1 Risk: **LOW** ✅
- Serializer-only changes
- No database migrations
- Backward compatible (old calls still work)
- Can rollback instantly by reverting code

### P2.2 Risk: **LOW** ✅
- New endpoint, doesn't modify existing
- Standard DRF pattern
- No database changes

### P3.1 Risk: **MEDIUM** ⚠️
- Complex business logic
- Signal handlers can be error-prone
- Requires comprehensive testing
- Potential for cascading effects (cancel invoice cascades to DNs)
- **Mitigation:** Feature flag to disable rules if issues found

### P3.2 Risk: **LOW** ✅
- Async email, failures don't block API
- Standard Celery pattern
- Email failures non-critical

---

## Success Metrics

After implementation, teams should be able to:

1. **Create delivery notes independently** (not tied to invoice)
2. **Link/unlink DNs to invoices** via explicit API endpoints
3. **Prevent invalid state transitions** (e.g., pay without delivery)
4. **Email customers** at different workflow stages
5. **Support wholesale ASN workflows** (DN before invoice)

### Before & After Comparison

```
BEFORE (Current):
P1: warehouser@acme.com creates DN from invoice
    ↓
P2: Must create invoice first (1-2 day process)
    ↓
Result: Cannot send ASN before invoice

AFTER (With P2+P3):
P1: warehouser@acme.com creates standalone DN
    ↓
P2: DN sent to customer as ASN (automatic email)
    ↓
P3: Goods arrive, customer confirms in DN
    ↓
P4: Accountant creates invoice (reference DN)
    ↓
P5: Invoice automatically sent after DN confirmation
    ↓
Result: Customer notified at each stage ✅
```

---

## Testing Strategy

### Unit Tests (Per Task)
- DeliveryNoteCreateSerializer: 10 tests
- Link endpoint: 8 tests
- Workflow rules: 15 tests
- Email tasks: 6 tests
**Total:** ~40 unit tests

### Integration Tests
- Pre-invoice workflow: 1 complete scenario
- Parallel workflow: 1 complete scenario
**Total:** 2 integration tests

### Manual Testing
- Create DN in Postman before invoice exists ✓
- Link DN to invoice after creation ✓
- Verify email sent at each stage ✓
- Check audit logs ✓

### Performance Testing
- Create 1000 DNs with items (bulk API)
- Status update 500 invoices simultaneously
- Email 100 DNs in batch

---

## Estimate & Staffing

### Development
- **P2.1 (Serializer):** 1 developer, 2 days
- **P2.2 (Linking endpoint):** 1 developer, 1 day
- **P3.1 (Workflow rules):** 1 senior developer, 3 days
- **P3.2 (Email):** 1 developer, 2.5 days
- **Total:** ~1.5 weeks, 1-2 developers

### QA
- **P2.1:** 1 day (parallel with dev)
- **P2.2:** 0.5 day
- **P3.1:** 2 days (needs thorough testing)
- **P3.2:** 1 day
- **Total:** ~4.5 days, 1 QA engineer

### Timeline
```
Sprint 1 (Week 1):    P2.1 + P2.2 (enables basic pre-invoice flows)
Sprint 2 (Week 2-3):  P3.1 (adds safety/compliance)
Sprint 3 (Week 3):    P3.2 (adds customer notifications) [optional]
```

---

## Deployment Plan

### Deployment Sequence
1. **P2.1 → Staging** (code review + unit tests)
2. **P2.1 → Production** (if staging tests pass, low risk)
3. **P2.2 → Staging + Production** (same day, low risk)
4. **P3.1 → Staging** (needs integration testing)
5. **P3.1 → Production** (after 48h staging validation)
6. **P3.2 → Staging + Production** (if emails needed immediately)

### Database Migrations
- **P2.1:** None
- **P2.2:** None
- **P3.1:** None (uses existing models)
- **P3.2:** None (new file only)

**Important:** No database migrations required for any phase!

---

## Rollback Procedure

### If P2.1 breaks production:
1. Revert commit
2. Restart Django servers
3. Done (no DB migration to undo)

### If P3.1 causes status issues:
1. Comment out signal handlers in models.py
2. Restart servers
3. Investigate offline
4. Deploy fix

### If P3.2 emails fail:
1. Disable Celery tasks (no API impact)
2. Investigate email configuration
3. Restart Celery workers

**Estimated rollback time:** 5-15 minutes for all phases

---

## Sign-Off Checklist

Before starting implementation:

- [ ] Product manager approves invoice workflow changes
- [ ] QA reviews test plan
- [ ] DevOps confirms Celery/email ready for P3.2
- [ ] Tech lead reviews code structure
- [ ] Database team confirms no migrations needed

Before deployments:

- [ ] All unit tests passing
- [ ] Integration tests in staging
- [ ] Security review (authentication/permissions)
- [ ] Performance testing complete
- [ ] Rollback plan documented and tested

---

## FAQ

**Q: Can we do P2 without P3?**  
Yes. P2 enables basic pre-invoice flows. P3 adds safety rails and email automation.

**Q: Will this break existing invoice-first workflows?**  
No. All changes are backward compatible. Existing code paths unchanged.

**Q: What if we need pre-invoice DNs urgently?**  
Deploy P2.1 immediately (2 days). Gives you 80% of what's needed.

**Q: Can users still create DNs from invoices?**  
Yes. All existing endpoints (create-from-invoice, create-from-purchase-order) still work.

**Q: Will status rules prevent legitimate workflows?**  
Possibly - that's why P3.1 needs thorough testing. Can add exceptions if needed.

---

## Related Documentation

See also:
- [delivery-note-workflow-analysis.md](delivery-note-workflow-analysis.md) — Complete technical analysis
- [implementation-guide.md](implementation-guide.md) — Detailed code examples and tests
- [finance/invoicing/models.py](../../finance/invoicing/models.py) — Current Invoice/DN models
- [finance/invoicing/serializers.py](../../finance/invoicing/serializers.py) — Current serializers

---

## Contact & Questions

For questions about:
- **Product requirements:** Product Manager
- **Technical approach:** Tech Lead / Architect
- **Implementation:** Lead Developer
- **Testing:** QA Lead
- **Deployment:** DevOps/Release Manager

---

**Document Status:** Draft Ready for Review  
**Next Step:** Schedule implementation planning meeting

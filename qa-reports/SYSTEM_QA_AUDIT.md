# Bengo ERP (erp-api) Full System QA Audit

## 🛠️ Environmental & Runtime State
* **Date of Log Capture:** July 6, 2026
* **Host Environment:** Ubuntu Linux (HP EliteBook 840 G4)
* **Backend Runtime:** Go v1.26.0
* **Target Gateway Listening Port:** `0.0.0.0:4000`

---

## 🛑 Discovered System Defects & Risk Analysis

### [BUG-001]: Database SASL Authentication Failure in Critical Background Chronology Engines
* **Severity:** 🔴 **Critical** (Blocks calculations, automatic snapshots, and multi-tenant persistence)
* **Target Source Paths:** * `internal/modules/backup/scheduler.go`
  * `internal/modules/leave/cron.go`
  * `internal/modules/fx/cron.go`

#### A. Execution Steps to Trigger Failure
1. Spin up the underlying docker infrastructure (`hr-postgres`).
2. Run the server command string from the directory root:
   ```bash
   go run ./cmd/server/main.go
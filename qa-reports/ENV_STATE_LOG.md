# Environmental Configuration State Log
* **Capture Timestamp:** July 6, 2026 - 12:19 PM EAT
* **Target System:** Bengo ERP Core Engine (`erp-api`)

---

## 💻 1. Host Machine Specifications
* **OS:** Ubuntu 24.04 LTS (Noble Numbat)
* **Hardware:** HP EliteBook 840 G4
* **Go Compiler Version:** `go 1.26.0 linux/amd64`

---

## 🐳 2. Active Infrastructure Container Grid (`docker ps`)
The following structural dependencies were active and healthy during runtime evaluation:

| Container ID | Image Name | Exposed Ports | Network Service Name | Status |
| :--- | :--- | :--- | :--- | :--- |
| `0adbd3296c1c` | `confluentinc/cp-schema-registry:7.6.1` | `8081->8081/tcp` | `hr-schema-registry` | Up ~1 Hour |
| `5b028a1a21c7` | `postgres:16-alpine` | `5432->5432/tcp` | `hr-postgres` | Up ~1 Hour (Healthy) |
| `df918236d7de` | `confluentinc/cp-kafka:7.6.1` | `9092->9092/tcp` | `hr-kafka` | Up ~1 Hour (Healthy) |
| `b96bf2b96326` | `redis:7-alpine` | `6379->6379/tcp` | `hr-redis` | Up ~1 Hour (Healthy) |
| `4e12252df2cd` | `quay.io/keycloak/keycloak:24.0` | `8080->8080/tcp` | `hr-keycloak` | Up ~1 Hour |

---

## 🔑 3. Environment Signatures Verification
* **`.env` File Detection:** 🚫 **None Detected** in project root folder.
* **Fallback Settings:** System runtime defaulting to standard out-of-the-box configuration properties.
* **Authentication Method:** SASL protocol requested by database broker hook.

---

## 📡 4. Network Binding Assertions
* **Server Target Allocation:** `0.0.0.0:4000`
* **Local Loopback Target:** `http://localhost:4000`
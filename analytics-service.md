# NutraTenant Analytics & Reporting Microservice System Design

This document details the architectural blueprint for the **NutraTenant Analytics & Reporting Service**. This microservice asynchronously ingests operational tenant data, aggregates specialized nutritional telemetry, enforces absolute multi-tenant data isolation, and delivers long-running structured compliance reports.

---

## 1. System Requirements

### Functional Requirements
- **Tenant Dashboard Aggregations:** Compute live and historical macro-level tenant insights (e.g., total active clients, aggregate weight management trajectories, active meal plan completion rates).
- **Nutritional Telemetry Analytics:** Process granular diet tracking metrics across daily, weekly, and monthly intervals (e.g., average caloric deficits, macronutrient ratios ($Carbohydrates:Protein:Fat$), and micronutrient deficiency indexing).
- **Asynchronous Export Pipeline:** Allow clinical admins and nutritionists to trigger bulk historical reports (e.g., Client Progress Overviews, Compliance Audits, Meal Plan Adherence Sheets) exported to CSV, Excel, and print-ready PDFs.
- **Automated Distributions:** Support cron-style scheduling to send periodic progress reports directly to staff dashboards, external webhooks, or the primary user notification pipeline.

### Non-Functional Requirements
- **Strict Multi-Tenant Isolation:** Enforce absolute data isolation at the storage layer; analytic queries executed by one tenant organization must never traverse or accidentally aggregate metadata belonging to a neighboring tenant.
- **OLTP/OLAP Decoupling:** Prevent heavy analytical queries from degrading the performance of the core transactional application database (`NutraTenant` primary operational DB). All analytics must utilize a read-optimized replica or a dedicated analytical datastore.
- **Asynchronous Background Processing:** Offload heavy file generation tasks (PDF compilation, massive CSV streams) to out-of-band background workers to guarantee sub-second HTTP API responses for the UI.

---

## 2. Core Architecture Diagram

The service decouples event consumption from reporting execution via an event-driven architecture using message brokers:

[ Primary NutraTenant Services ] (Client Management, Meal Planner, Tracker)
│
▼ (Asynchronous Event Streams: e.g., 'LogMeal', 'UpdateWeight')
┌────────────────────────────────────────────────────────┐
│                  DISTRIBUTED MESSAGE BROKER            │
│              (Apache Kafka / RabbitMQ Clusters)        │
└──────────────────────────┬─────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────┐
│             ANALYTICS INGESTION WORKER POOL            │
│  - Captures raw telemetry events                       │
│  - Formats, normalizes, and appends Tenant Context     │
└──────────────────────────┬─────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────┐
│             READ-OPTIMIZED COLUMNAR DATABASE           │
│         (ClickHouse / PostgreSQL Read Replica)         │
│  ┌──────────────────────────────────────────────────┐  │
│  │  - Partitioned by Tenant ID                      │  │
│  │  - Continuous pre-aggregation Materialized Views │  │
└──────────────────────────┬─────────────────────────────┘
│
▼
┌────────────────────────────────────────────────────────┐
│              ANALYTICS & REPORTING CORE API            │
│  ┌─────────────────────────┐  ┌─────────────────────┐  │
│  │  Query Execution Engine │  │ Async Report Job Mgr│  │
│  └────────────┬────────────┘  └──────────┬──────────┘  │
└───────────────┼──────────────────────────┼─────────────┘
│                          │
▼                          ▼ (Pushes long-running exports)
[Frontend Dashboards]     ┌────────────────────────┐
(REST / GraphQL JSON)     │  BACKGROUND WORKERS    │
│ (Celery / BullMQ Pools)│
└─────────┬──────────────┘
│
▼ (Pushes file output)
┌────────────────────────┐
│   BLOB OBJECT STORE    │
│     (AWS S3 / MinIO)   │
└────────────────────────┘


---

## 3. Data Models & Schema Design (OLAP)

To achieve fast range-scans without data leakage, schemas inside the analytical datastore append structural partitioning markers.

### Raw Tenant Telemetry Log (`tenant_nutrition_logs`)
Designed for write-heavy append actions capturing tracking activity.

| Column Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `log_id` | `UUID` | `PRIMARY KEY` | Unique record identity identifier |
| `tenant_id` | `VARCHAR(64)` | `INDEX` / `PARTITION KEY` | Target business enterprise scope identifier |
| `client_id` | `VARCHAR(64)` | `INDEX` | Unique client ID within the tenant |
| `calories_consumed`| `INT` | `NOT NULL` | Total raw energy metric input ($kcal$) |
| `protein_g` | `DECIMAL(5,2)`| `NOT NULL` | Contributed macronutrient protein grams |
| `carbs_g` | `DECIMAL(5,2)`| `NOT NULL` | Contributed macronutrient carbohydrate grams |
| `fat_g` | `DECIMAL(5,2)`| `NOT NULL` | Contributed macronutrient fat grams |
| `logged_at` | `TIMESTAMP` | `DEFAULT NOW()` | Exact epoch generation timestamp |

### Generated Reports Job Registry (`report_jobs`)
Tracks asynchronous generation state metrics.

| Column Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `job_id` | `UUID` | `PRIMARY KEY` | Unique worker tracing handle |
| `tenant_id` | `VARCHAR(64)` | `NOT NULL` | Requesting organizational tenant link |
| `report_type` | `VARCHAR(32)` | `NOT NULL` | Enum representation (`COMPLIANCE`, `PROGRESS`) |
| `status` | `VARCHAR(16)` | `DEFAULT 'PENDING'` | Status trace (`PENDING`, `PROCESSING`, `SUCCESS`, `FAILED`) |
| `file_url` | `TEXT` | `NULL` | Pre-signed S3 download URL location path |
| `error_reason` | `TEXT` | `NULL` | Debug stack string tracking worker failures |

---

## 4. Component Deep Dive

## 4. Component Deep Dive

### 4.1 Strict Multi-Tenant Isolation
The service protects medical and dietary profiles via a two-layer validation strategy:
1. **Context-Aware Middleware:** The API Gateway intercepts incoming requests and decodes the JWT identities. It then injects a secure execution context containing the verified `tenant_id` variable into the request lifecycle.
2. **Enforced Row-Level Scope Injection:** Every generated SQL query or database call is forced programmatically to contain an explicit tenant boundary clause. This prevents any analytical request from accidentally crossing boundaries:
   ```sql
   SELECT * FROM tenant_nutrition_logs 
   WHERE tenant_id = :current_tenant_id AND logged_at >= :start_date;
   ```
   
### 4.2 Materialized Aggregate Views

Calculating cumulative statistics on raw nutritional entries for millions of tracking items can cause high CPU utilization spikes. To circumvent this, the database automatically pre-aggregates target windows using rolling daily summaries:

Daily Caloric Mean = Sum(calories_consumed) / Total Unique Clients

The client application directly queries these lightweight, pre-compiled data tables instead of running heavy on-the-fly math, delivering immediate interface renders and dashboard updates.

### 4.3 Asynchronous Report Compilation Circuit
When an admin nutritionist requests an export (e.g., **"Export 6-Month Client Progress History"**):

* **Immediate Acknowledgment:** The Core API writes a registration record inside the `report_jobs` table set to `PENDING` and instantly returns a `202 Accepted` status token back to the UI.
* **Queueing:** The compilation context and parameters are placed inside an isolated background execution queue.
* **Out-of-Band Compilation:** An isolated background task runner captures the item from the queue, builds the analytical dataset, converts the output into the final structural layout (e.g., using a high-performance streaming spreadsheet worker or a headless HTML-to-PDF print context), and offloads the compiled binary structure into a secure Object Store container.
* **State Transition:** The database is updated with a status of `SUCCESS` and the file destination link, signaling the client dashboard via polling or web sockets to render an active **"Download Ready"** button.

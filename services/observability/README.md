# Observability Service

**Project:** NutraTenant IAM

**Domain:** Platform Infrastructure

**Service Type:** Shared Platform Service

**Priority:** Critical

**Architecture Style:** Multi-Tenant SaaS IAM

**Cost Target:** $0 Open Source Stack

---

# Purpose

The Observability Service provides centralized monitoring, logging, tracing, auditing, and security visibility across the NutraTenant platform.

The platform must provide visibility for:

* Authentication
* Authorization
* Tenant Resolution
* Workspace Discovery
* Policy Evaluation
* User Management
* Session Management
* API Gateway
* Security Events
* Infrastructure Health
* Business Metrics

---

# Multi-Tenant Requirements

Every telemetry event MUST include:

```json
{
  "organization_id": "org_apple",
  "tenant_id": "tenant_prod",
  "workspace_slug": "apple-corp",
  "user_id": "usr_001",
  "request_id": "req_123",
  "trace_id": "trace_456"
}
```

This enables:

* Tenant-specific dashboards
* Tenant-specific alerting
* Security investigations
* Audit compliance
* Cost attribution

---

# Architecture

```text
FastAPI Services
        │
        ▼
OpenTelemetry SDK
        │
        ▼
OpenTelemetry Collector
        │
        ├───────────── Metrics
        │                  │
        │                  ▼
        │            Prometheus
        │
        ├───────────── Logs
        │                  │
        │                  ▼
        │                Loki
        │
        ├───────────── Traces
        │                  │
        │                  ▼
        │               Tempo
        │
        ▼
Grafana
        │
        ▼
AlertManager
        │
        ▼
Email / Discord / Slack
```

---

# Open Source Stack ($0)

```text
OpenTelemetry
Prometheus
Grafana
Loki
Tempo
AlertManager
Node Exporter
Cadvisor
Postgres Exporter
Redis Exporter
```

---

# Services To Instrument

```text
gateway-service
auth-service
tenant-service
organization-service
iam-service
policy-service
audit-service
notification-service
```

---

# Structured Logging

Format:

```json
{
  "timestamp": "2026-01-01T10:00:00Z",
  "level": "INFO",
  "service": "auth-service",
  "organization_id": "org_apple",
  "tenant_id": "tenant_prod",
  "user_id": "usr_001",
  "request_id": "req_123",
  "message": "User login successful"
}
```

---

# Correlation IDs

Every request must contain:

```http
X-Request-ID
```

Every trace must contain:

```http
traceparent
```

---

# Distributed Tracing

Trace:

```text
Browser
   │
   ▼
API Gateway
   │
   ▼
Auth Service
   │
   ▼
Tenant Service
   │
   ▼
Policy Service
   │
   ▼
PostgreSQL
```

Trace must show:

* Service latency
* Database latency
* Policy evaluation latency
* Authentication latency

---

# Authentication Metrics

```text
login_attempts_total
login_success_total
login_failure_total
mfa_success_total
mfa_failure_total
password_reset_total
password_reset_failure_total
active_sessions_total
```

---

# Authorization Metrics

```text
authorization_requests_total
authorization_allow_total
authorization_deny_total
policy_evaluation_total
policy_evaluation_errors_total
```

Labels:

```text
organization
tenant
policy
decision
```

---

# Tenant Metrics

```text
tenants_total
active_tenants_total
inactive_tenants_total
tenant_switch_total
tenant_resolution_total
tenant_resolution_failure_total
```

---

# User Metrics

```text
users_total
active_users_total
disabled_users_total
users_invited_total
users_registered_total
```

---

# Role Metrics

```text
roles_total
role_assignments_total
role_changes_total
```

---

# Policy Metrics

```text
policies_total
policies_created_total
policies_updated_total
policies_deleted_total
```

---

# Security Metrics

```text
failed_logins_total
account_lockouts_total
mfa_failures_total
suspicious_activity_total
token_validation_failures_total
jwt_expired_total
jwt_invalid_total
permission_denied_total
```

---

# Audit Metrics

```text
audit_events_total
audit_events_failed_total
audit_storage_size_bytes
```

---

# API Metrics

Golden Signals

## Latency

```text
http_request_duration_seconds
```

Track:

```text
P50
P95
P99
```

---

## Traffic

```text
http_requests_total
```

Labels:

```text
service
method
endpoint
tenant
```

---

## Errors

```text
http_errors_total
```

Labels:

```text
4xx
5xx
```

---

## Saturation

```text
cpu_usage_percent
memory_usage_percent
disk_usage_percent
db_connection_usage_percent
```

---

# Business Metrics

## Organizations

```text
organizations_total
organizations_created_total
organizations_deleted_total
```

## Tenants

```text
tenants_created_total
tenants_deleted_total
```

## IAM

```text
users_created_total
users_deleted_total
roles_created_total
permissions_assigned_total
```

---

# Audit Logging

All security-sensitive actions must be audited.

Examples:

```text
LOGIN_SUCCESS
LOGIN_FAILURE
PASSWORD_RESET
ROLE_ASSIGNED
ROLE_REMOVED
USER_CREATED
USER_DELETED
TENANT_CREATED
TENANT_DELETED
POLICY_CREATED
POLICY_UPDATED
POLICY_DELETED
```

Audit Event:

```json
{
  "event_type": "ROLE_ASSIGNED",
  "actor_id": "usr_admin_001",
  "target_user_id": "usr_member_001",
  "organization_id": "org_apple",
  "tenant_id": "tenant_prod",
  "timestamp": "2026-01-01T10:00:00Z"
}
```

---

# Health Checks

Every service must expose:

```http
GET /health
```

Response:

```json
{
  "status": "healthy"
}
```

Readiness:

```http
GET /ready
```

Liveness:

```http
GET /live
```

---

# Observability APIs

## Metrics

```http
GET /metrics
```

Prometheus endpoint.

---

## Service Health

```http
GET /api/v1/health
```

Returns:

```json
{
  "service": "auth-service",
  "status": "healthy"
}
```

---

## Trace Lookup

```http
GET /api/v1/traces/{trace_id}
```

---

## Audit Search

```http
GET /api/v1/audit/events
```

Filters:

```text
organization_id
tenant_id
user_id
event_type
date_from
date_to
```

---

# Grafana Dashboards

## Executive Dashboard

```text
Organizations
Tenants
Users
Logins
Security Events
```

## Operations Dashboard

```text
Latency
Errors
Traffic
Infrastructure
```

## Security Dashboard

```text
Failed Logins
Account Lockouts
Permission Denials
MFA Failures
```

## Tenant Dashboard

```text
Tenant Activity
Tenant Usage
Tenant Errors
Tenant Growth
```

---

# Alerting

## P1 Critical

```text
Auth Service Down
Database Down
JWT Validation Failure Spike
```

## P2 Major

```text
High Login Failure Rate
High Error Rate
Tenant Resolution Failures
```

## P3 Minor

```text
Disk Usage > 80%
Memory Usage > 80%
```

---

# Retention

Logs:

```text
30 Days
```

Metrics:

```text
90 Days
```

Traces:

```text
14 Days
```

Audit Events:

```text
365 Days
```

---

# Kubernetes Namespace

```text
nutratenant-observability
```

---

# Components

```text
grafana
prometheus
loki
tempo
alertmanager
otel-collector
node-exporter
cadvisor
postgres-exporter
redis-exporter
```

---

# Future Enhancements

```text
SIEM Integration
Anomaly Detection
Tenant Cost Analytics
Security Analytics
Behavior Analytics
Open Policy Agent Telemetry
ML-based Threat Detection
```

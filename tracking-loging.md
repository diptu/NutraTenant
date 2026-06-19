# Tracking & Logging Service

## Overview

The Tracking & Logging Service provides centralized observability, auditing, analytics, and security monitoring across the NutraTenant platform.

It captures:

* User activities
* API requests
* Authentication events
* Subscription events
* Tenant operations
* Business workflows
* Background tasks
* Security incidents
* System performance metrics

The service is designed to support:

* Multi-tenancy
* Compliance requirements
* Product analytics
* Debugging
* Fraud detection
* Billing usage metering
* Operational monitoring

---

# Goals

## Functional Goals

* Track all user activities
* Generate immutable audit logs
* Capture API access logs
* Record authentication events
* Monitor subscription changes
* Measure feature usage
* Support business analytics
* Track background job execution

## Non-Functional Goals

* High throughput
* Event-driven
* Horizontally scalable
* Tenant isolated
* GDPR compliant
* Near real-time processing

---

# High-Level Architecture

```text
┌─────────────────────────┐
│      Frontend Apps      │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│       API Gateway       │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│     Event Publisher     │
└────────────┬────────────┘
             │
             ▼
        Message Bus
      (Kafka/RabbitMQ)
             │
 ┌───────────┼────────────┐
 ▼           ▼            ▼

Tracking   Audit      Analytics
Worker     Worker      Worker

 ▼           ▼            ▼

TrackingDB AuditDB AnalyticsDB
```

---

# Event Categories

## 1. Authentication Events

Examples:

* Login
* Logout
* Registration
* Password Reset
* MFA Enabled
* MFA Verification
* Account Lockout

Example:

```json
{
  "event_type": "auth.login",
  "user_id": "usr_123",
  "tenant_id": "tenant_1",
  "ip": "192.168.1.1",
  "device": "Chrome",
  "status": "success"
}
```

---

## 2. User Activity Events

Examples:

* Create profile
* Update profile
* Upload file
* Export report
* Delete resource

```json
{
  "event_type": "user.profile.updated",
  "user_id": "usr_123"
}
```

---

## 3. Tenant Events

Examples:

* Tenant created
* Tenant archived
* Domain verified
* Member invited
* Member removed

```json
{
  "event_type": "tenant.member.invited",
  "tenant_id": "tenant_1"
}
```

---

## 4. Subscription Events

Examples:

* Trial Started
* Trial Expired
* Subscription Created
* Subscription Renewed
* Subscription Cancelled
* Invoice Generated

```json
{
  "event_type": "subscription.created",
  "subscription_id": "sub_123"
}
```

---

## 5. Billing Usage Events

Examples:

* API request consumed
* AI token usage
* Report generation
* Storage increase

```json
{
  "event_type": "usage.ai.tokens",
  "quantity": 5000
}
```

---

## 6. System Events

Examples:

* Service started
* Service stopped
* Deployment completed
* Database migration

```json
{
  "event_type": "system.deployment.completed"
}
```

---

## 7. Security Events

Examples:

* Suspicious login
* Multiple failed logins
* Permission escalation
* Token abuse

```json
{
  "event_type": "security.suspicious_activity"
}
```

---

# Event Model

## Tracking Event

```text
TrackingEvent
```

| Field      | Type     |
| ---------- | -------- |
| id         | UUID     |
| tenant_id  | UUID     |
| user_id    | UUID     |
| event_type | String   |
| source     | String   |
| timestamp  | Datetime |
| metadata   | JSONB    |

---

# Audit Logging

## Purpose

Audit logs provide an immutable record of critical operations.

Examples:

* User deletion
* Role changes
* Subscription changes
* Billing modifications
* Domain ownership updates

---

## Audit Log Model

```text
AuditLog
```

| Field         | Type      |
| ------------- | --------- |
| id            | UUID      |
| tenant_id     | UUID      |
| actor_id      | UUID      |
| resource_type | String    |
| resource_id   | UUID      |
| action        | String    |
| before_state  | JSONB     |
| after_state   | JSONB     |
| created_at    | Timestamp |

---

# API Access Logging

## Request Data

Capture:

* Method
* Endpoint
* Status Code
* Response Time
* Tenant
* User

Example:

```json
{
  "path": "/api/v1/users",
  "method": "GET",
  "status": 200,
  "duration_ms": 78
}
```

---

# Usage Metering

Used by Billing Service.

Examples:

* API Calls
* AI Requests
* Storage
* Exports
* Active Members

---

## Usage Record

```text
UsageRecord
```

| Field     | Type      |
| --------- | --------- |
| id        | UUID      |
| tenant_id | UUID      |
| metric    | String    |
| quantity  | Decimal   |
| timestamp | Timestamp |

---

# Analytics Pipeline

Raw events are transformed into analytics data.

Examples:

* DAU
* WAU
* MAU
* Retention
* Churn
* Feature adoption

---

## Analytics Warehouse

Possible options:

* PostgreSQL
* ClickHouse
* BigQuery
* Snowflake

Recommended:

```text
PostgreSQL → ClickHouse
```

for large-scale analytics.

---

# OpenTelemetry Integration

Adopt OpenTelemetry across all services.

Capture:

* Traces
* Metrics
* Logs

Benefits:

* Distributed tracing
* Root-cause analysis
* Service dependency mapping

---

# Correlation IDs

Every request should have:

```text
X-Correlation-ID
```

Example:

```text
req_abc123
```

Used across:

* API Gateway
* Billing Service
* IAM Service
* Notification Service

---

# Structured Logging

Never log plain text.

Use JSON.

Example:

```json
{
  "timestamp": "2026-06-19T12:00:00Z",
  "level": "INFO",
  "service": "billing-service",
  "tenant_id": "tenant_1",
  "message": "Invoice generated"
}
```

---

# Log Storage Strategy

## Hot Storage

Retention:

```text
30 Days
```

Technology:

```text
Elasticsearch/OpenSearch
```

---

## Warm Storage

Retention:

```text
1 Year
```

Technology:

```text
S3 / Azure Blob Storage
```

---

## Cold Storage

Retention:

```text
7 Years
```

Technology:

```text
Archive Storage
```

---

# Observability Dashboard

Key metrics:

## API Metrics

* Requests/sec
* Error rate
* Latency

## User Metrics

* Active users
* New signups
* Churn

## Subscription Metrics

* MRR
* ARR
* Trial conversion

## Billing Metrics

* Revenue
* Failed payments
* Outstanding invoices

---

# Alerting

Use:

* Prometheus
* Grafana
* AlertManager

Alerts:

## Critical

* Service Down
* Payment Processing Failure
* Database Unavailable

## Warning

* High Error Rate
* Slow Queries
* Failed Webhooks

---

# Data Privacy

Never log:

* Passwords
* Access Tokens
* Refresh Tokens
* Credit Card Data
* CVV

Mask sensitive information.

Example:

```json
{
  "email": "na*****@gmail.com"
}
```

---

# Multi-Tenant Isolation

Every record must contain:

```text
tenant_id
```

Partition strategy:

```text
tenant_id + timestamp
```

Benefits:

* Faster queries
* Easier archiving
* Better isolation

---

# Service APIs

## Track Event

```http
POST /events
```

Request:

```json
{
  "event_type": "subscription.created",
  "tenant_id": "tenant_1"
}
```

---

## Fetch Audit Logs

```http
GET /audit-logs
```

Filters:

* tenant_id
* actor_id
* date_range
* action

---

## Usage Metrics

```http
GET /usage
```

Returns:

```json
{
  "api_calls": 100000,
  "storage_gb": 45
}
```

---

# Recommended Technology Stack

## Backend

* FastAPI

## Database

* PostgreSQL

## Analytics

* ClickHouse

## Queue

* RabbitMQ
* Kafka

## Logging

* OpenSearch

## Metrics

* Prometheus

## Dashboards

* Grafana

## Tracing

* OpenTelemetry

## Storage

* Azure Blob Storage

---

# Implementation Roadmap

## Phase 1

Foundation

* Structured logging
* Correlation IDs
* Audit logging
* API request logging

---

## Phase 2

Tracking

* Event bus
* Tracking service
* Usage metering
* Subscription events

---

## Phase 3

Observability

* OpenTelemetry
* Prometheus
* Grafana dashboards
* Alerts

---

## Phase 4

Analytics

* ClickHouse
* Product analytics
* Retention analysis
* Revenue analytics

---

# Success Criteria

The platform should support:

* Millions of events/day
* Tenant-isolated tracking
* Full auditability
* Real-time monitoring
* Billing usage metering
* Compliance reporting
* Scalable analytics
* Distributed tracing

```
```

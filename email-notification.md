# High-Availability Email Notification Service System Design

This document details the architectural blueprint for an enterprise-grade, high-availability **Email Notification Service** capable of sending transactional, manual, and scheduled email payloads at scale. The design focuses on eliminating single points of failure (SPOF), handling rate limiting, utilizing decoupled queue architectures, and providing real-time event analytics.

---

## 1. System Requirements

### Functional Requirements
- **Payload Processing:** Dynamically build and customize emails based on predefined HTML/Text templates using dynamic variables (e.g., transaction data, user handles).
- **Multi-Trigger Modalities:** Support three core execution flows: Automatic/Transactional (e.g., order confirmations), Scheduled (e.g., daily digests), and Manual (e.g., marketing updates).
- **User Preferences:** Honor granular user settings, including explicit opt-outs, channel preferences, and delivery throttling (e.g., capping max notifications per day).
- **Delivery Analytics:** Provide end-to-end telemetry on the lifecycle of each message (`Pending` ➔ `Sent/Failed` ➔ `Delivered` ➔ `Opened/Clicked/Spam`).

### Non-Functional Requirements
- **High Availability & Scalability:** System components must be distributed and horizontally scalable to prevent single points of failure (SPOF).
- **Low Latency:** Emails must process into queues and be offloaded to third-party providers with minimum execution overhead.
- **Reliability & Fault Tolerance:** At-least-once delivery guarantees enforced through idempotent operations, persistent logging, and backoff-driven retry mechanisms.
- **Security:** Ensure incoming upstream requests are authenticated, and rate limits are placed at the entry layer to protect downstream resources from noisy neighbors or internal bugs.

---

## 2. Core Architecture Diagram

The system operates asynchronously, separating ingestion from delivery via message brokers:

```
[ Upstream Microservices ] (Order, Auth, Marketing, etc.)
            │
            ▼
┌────────────────────────────────────────────────────────┐
│               NOTIFICATION API GATEWAY                 │
│  ┌──────────────────┐          ┌────────────────────┐  │
│  │ Auth & Validation│          │    Rate Limiter    │  │
│  └────────┬─────────┘          └─────────┬──────────┘  │
└───────────┼──────────────────────────────┼─────────────┘
            ▼                              ▼
┌────────────────────────────────────────────────────────┐
│               NOTIFICATION SYSTEM CORE                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │               Message Body Builder               │  │
│  └───────┬────────────────────┬─────────────────┬───┘  │
└──────────┼────────────────────┼─────────────────┼──────┘
           │                    │                 │
           ▼                    ▼                 ▼
 ┌──────────────────┐  ┌────────────────┐  ┌──────────────┐
 │ User Prefs Cache │  │ Template Cache │  │  User DB     │
 │  (Redis/Memcached)│ │(Redis/Memcached)│ │ (PostgreSQL) │
 └──────────────────┘  └────────────────┘  └──────────────┘
           │
           ▼
┌────────────────────────────────────────────────────────┐
│                   DISTRIBUTED BROKER                   │
│  ┌──────────────────────────────────────────────────┐  │
│  │                Email Message Queue               │  │
│  │              (RabbitMQ / Apache Kafka)           │  │
│  └────────────────────────┬─────────────────────────┘  │
└───────────────────────────┼────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│                    WORKER POOL LAYER                   │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Email Worker Instances              │  │
│  └────────┬────────────────────┬───────────────┬────┘  │
└───────────┼────────────────────┼───────────────┼──────┘
            │                    │               │
            ▼                    ▼                 ▼
 ┌──────────────────┐  ┌────────────────┐  ┌──────────────┐
 │ Notification Log │  │ Analytics Engine│ │ Third-Party  │
 │    (DynamoDB)    │  │ (Clickhouse/ELK)│ │ Providers    │
 └──────────────────┘  └────────────────┘  │ (SendGrid,   │
                                           │  Mailchimp)  │
                                           └──────────────┘
```

---

## 3. Data Models

To track delivery paths and validate dynamic content quickly, data is normalized across relational setups for core identity, while transactional delivery statuses use distributed schemas.

### User Directory Table (`users`)
Maintains core identity metadata.

| Column Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `user_id` | `VARCHAR(64)` | `PRIMARY KEY` | Globally Unique Identifier |
| `email` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL` | Destination routing address |
| `phone` | `VARCHAR(20)` | `NULL` | Fallback routing attribute |
| `country` | `VARCHAR(5)` | `NOT NULL` | Localization & compliance tracking |
| `created_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` | Signup epoch baseline |

### User Preferences Table (`user_preferences`)
Enforces opt-outs, notification frequency caps, and channel locks.

| Column Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `user_id` | `VARCHAR(64)` | `FOREIGN KEY` | Maps to `users.user_id` |
| `allow_marketing` | `BOOLEAN` | `DEFAULT TRUE` | Global promo preference flag |
| `max_emails_per_day`| `INT` | `DEFAULT 10` | Frequency cap value for rate limit validation |

### Notification Audit Log Schema (`notification_logs`)
Designed for write-heavy append operations (e.g., using NoSQL systems like AWS DynamoDB or Cassandra) to capture raw delivery status and trace failures.

- `notification_id` (UUID, Primary Partition Key)
- `user_id` (String, Global Secondary Index Key)
- `template_id` (String)
- `status` (Enum: `PENDING`, `SENT_TO_PROVIDER`, `DELIVERED`, `FAILED`, `BOUNCED`)
- `retry_count` (Integer)
- `error_payload` (String / JSON Nullable)
- `updated_at` (Timestamp)

---

## 4. Component Deep Dive

### 4.1 Ingestion & Gateway Layer
- **API Gateways:** Distributed edge reverse proxies intercepting payload requests. They manage JWT/OAuth authorization verification checks before payloads touch processing routines.
- **Rate Limiter:** Token Bucket or Leaky Bucket algorithms deployed at edge caches (e.g., Redis) prevent misconfigured internal systems or upstream anomalies from bombarding internal buffers.

### 4.2 Message Body Builder & Cache Mechanics
- When an execution request clears validation, the system reads the core configuration profile.
- Instead of hitting the relational `users` database for every trigger, **Redis/Memcached clusters cache User Objects and HTML Templates**.
- The `Message Body Builder` pulls the target template markup, merges structural JSON inputs into placeholder tokens, compiles the string layout, and assigns a lifecycle `notification_id` tracking code.

### 4.3 Decoupled Message Queues
- Directly forwarding requests to external systems creates tight execution coupling and scalability blockages. If an external service latency increases, upstream threads lock up.
- The architecture isolates workloads into **Dedicated Email Message Queues**. This strategy prevents bursts in high-volume, low-priority flows (like marketing emails) from delaying critical, low-volume flows (like multi-factor authentication tokens).

### 4.4 Worker Pool Layer & Resiliency Strategies
- Horizontal scaling groups of independent application processes (`Email Workers`) subscribe to the delivery broker queues.
- **Idempotency Execution Strategy:** Upstream services append a unique `idempotency_key` onto transactions. The building layer registers this handle inside a shared storage lock to guarantee duplicate network retries do not send duplicate emails to users.
- **Failover Handling:** If a primary third-party vendor (e.g., SendGrid) returns a `5xx` error code or trips internal circuit breakers, the worker logs the exception details, increments the message profile retry counters, and routes the tracking payload to a **Failover Retry Queue** with Exponential Backoff schedules.

### 4.5 Closed-Loop Feedback & Analytics Engine
- **Event Trackers:** Webhooks exposed via the API Gateway capture callbacks from third-party delivery vendors when users interact with messages (e.g., opens, links clicked, or spam reports).
- These events dump into low-latency analytical data stores (such as ClickHouse or Apache Kafka streams) to feed real-time monitoring dashboards, helping detect immediate drops in domain reputation or platform performance.

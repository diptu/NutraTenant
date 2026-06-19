# High-Availability Telegram Notification Service System Design Extension

This document serves as an architectural extension to the enterprise-grade **Notification Service System Design**. It details the design, integration patterns, and components required to support **Telegram Channel and Direct Notification Delivery** alongside the existing Email infrastructure.

---

## 1. Architectural Strategy & Common Component Replay

To avoid building an entirely separate silo for Telegram notifications, the system utilizes a **Unified Notification Ingestion & Routing Strategy**. The core components from the Email Notification System Design are extended rather than duplicated.

### Reused Components
1. **Notification API Gateway:** Remains the single entry point for all upstream microservices. It continues to handle uniform JWT/OAuth authentication, request validation, and top-level edge rate-limiting.
2. **User DB & Preferences (PostgreSQL):** Extended with schemas to handle Telegram delivery attributes, opt-ins, and routing locks.
3. **Caching Layer (Redis):** Caches Telegram user sessions, chat ID mappings, and localized message templates to eliminate relational database bottlenecks.
4. **Analytics Engine (ClickHouse/ELK):** Real-time webhooks or polling updates from Telegram are streamed into the same data platform to maintain a single comprehensive operational dashboard.

---

## 2. System Architecture Diagram

The system decouples multi-channel processing early. Upstream systems pass a unified notification request, and the **Notification System Core** forks or routes payloads across channel-specific messaging brokers:

```
[ Upstream Microservices ] (Order, Auth, Marketing, System Alerts)
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
│  │ Channel Router & Payload Orchestrator            │  │
│  └───────┬────────────────────┬─────────────────┬───┘  │
└──────────┼────────────────────┼─────────────────┼──────┘
            │                    │                 │
            ▼                    ▼                 ▼
 ┌──────────────────┐  ┌────────────────┐  ┌──────────────┐
 │ User Prefs Cache │  │ Template Cache │  │   User DB    │
 │   (Redis Cluster)│  │ (Redis Cluster)│  │ (PostgreSQL) │
 └──────────────────┘  └────────────────┘  └──────────────┘
            │
            ├──────────────────────────────────────┐
            ▼ (Email Path)                         ▼ (Telegram Path)
┌────────────────────────┐             ┌────────────────────────┐
│   DISTRIBUTED BROKER   │             │   DISTRIBUTED BROKER   │
│ ┌────────────────────┐ │             │ ┌────────────────────┐ │
│ │Email Message Queue │ │             │ │Telegram Msg Queue  │ │
│ └─────────┬──────────┘ │             │ └─────────┬──────────┘ │
└───────────┼────────────┘             └───────────┼────────────┘
            ▼                                      ▼
┌────────────────────────┐             ┌────────────────────────┐
│   WORKER POOL LAYER    │             │   WORKER POOL LAYER    │
│ ┌────────────────────┐ │             │ ┌────────────────────┐ │
│ │Email Worker Pool   │ │             │ │Telegram Worker Pool│ │
│ └─────────┬──────────┘ │             │ └─────────┬──────────┘ │
└───────────┼────────────┘             └───────────┼────────────┘
            ▼                                      ▼
┌────────────────────────┐             ┌────────────────────────┐
│  Third-Party Vendors   │             │  Telegram Bot API Layer│
│  (SendGrid / SES)      │             │  (Long-Polling/Webhooks│
└────────────────────────┘             └────────────────────────┘
```

---

## 3. Data Models Extension

To accommodate Telegram routing metadata and channel preferences alongside the baseline relational structures, the database schema is extended or paired with the following entity configurations.

### Extended User Directory Table (`users`)
Appends Telegram tracking identifiers to standard profiles.

| Column Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `telegram_chat_id` | `BIGINT` | `UNIQUE`, `NULL` | Unique Telegram ID representing the chat/user session |
| `telegram_username` | `VARCHAR(32)` | `NULL` | Telegram @username handle for verification and fallback |

### Extended User Preferences Table (`user_preferences`)
Enforces multi-channel choice configurations, routing fallbacks, and notification delivery caps.

| Column Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `preferred_channel` | `VARCHAR(16)` | `DEFAULT 'EMAIL'` | Primary route target (`EMAIL`, `TELEGRAM`, `BOTH`) |
| `allow_telegram_marketing`| `BOOLEAN` | `DEFAULT FALSE` | Global promotional option lock for Telegram channel |
| `telegram_rate_cap_per_hr` | `INT` | `DEFAULT 20` | Strict hourly threshold to protect against Telegram Bot API rate limits |

### Telegram Channel Registry Table (`telegram_channels`)
Tracks destination channels and broadcasting privileges for manual/marketing triggers.

| Column Name | Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `channel_id` | `VARCHAR(64)` | `PRIMARY KEY` | Internal identifier for target channel asset |
| `telegram_handle` | `VARCHAR(64)` | `UNIQUE`, `NOT NULL` | Public or private Telegram channel name (e.g., `@MyOrgAlerts`) |
| `access_token_ref` | `VARCHAR(128)` | `NOT NULL` | Encrypted reference pointer to target bot tokens in Secret Store |
| `is_active` | `BOOLEAN` | `DEFAULT TRUE` | Active routing verification state |

---

## 4. Component Deep Dive: Telegram Adaptation

### 4.1 Ingestion & Channel Routing Execution
When an upstream service publishes a payload, it hits the **Notification System Core**. 
- The system evaluates the `preferred_channel` value in the `User Preferences Cache`.
- If the preference resolves to `TELEGRAM` or `BOTH`, the core creates a tracking `notification_id` and dispatches the payload to the dedicated **Telegram Message Queue**.
- **Payload Splitter:** If the choice is `BOTH`, the core generates two distinct worker messages mapped back to the single source notification ID, ensuring cross-channel consistency.

### 4.2 Template Management & Parsing Differences
Unlike emails which handle deep nested HTML layouts, Telegram message payloads accept limited MarkdownV2 or HTML styling subsets.
- The **Message Body Builder** loads Telegram-optimized structural templates from the Redis Cache.
- The builder automatically strips unsupported email elements (like heavy table structures, inline CSS styling, or complex custom divs) and replaces them with clean Telegram-formatted typography (e.g., strong tags, escape characters for MarkdownV2 compliance, and inline URLs).

### 4.3 Telegram Bot API Worker Architecture
Independent **Telegram Worker Instances** consume items asynchronously from the message broker.
- **Bot Endpoint Routing:** Messages are transmitted directly to the Telegram Bot HTTP API using the standard payload signature: `https://api.telegram.org/bot<token>/sendMessage`.
- **Target Addressing:** For direct alerts, the payload incorporates the user's explicit `telegram_chat_id`. For manual/marketing broad broadcasts, the worker routes payloads using the corresponding target public/private `telegram_handle` string (e.g., `@MyOrgAlerts`).

### 4.4 Resiliency & Telegram Bot API Rate Limits
Telegram enforces strict downstream request limits that differ fundamentally from enterprise email APIs:
- **Rate Limit Constraints:** Bots cannot send more than 30 messages per second across all endpoints, or more than 1 message per second to a specific direct chat ID. Group/Channel blasts are limited to 20 messages per minute.
- **Distributed Token Bucket Integration:** Workers leverage a synchronized Redis-backed sliding-window rate-limiting mechanism before calling the Telegram API.
- **Handling 429 Errors:** If an upstream flood trips a Telegram `429 Too Many Requests` error, the API returns a response containing a `retry_after` header field. The worker intercepts this code, suspends processing threads for that specific target scope, and automatically parks the message back inside an **Exponential Backoff Failover Queue** configured to wake up after the specified timeout window expires.

### 4.5 Closed-Loop Webhook Handler
To map analytics accurately, the system establishes a Telegram Webhook configuration endpoint:
- **Callback Ingestion:** When users block/unblock the system's bot, join a channel, or issue user interactions, Telegram pushes a state webhook payload to the system's API gateway.
- **Deactivation Processing:** If a webhook reports a `403 Forbidden` error (indicating a user blocked the bot), the handler immediately triggers an update to the database setting `allow_telegram_marketing = FALSE`, switching the default fallback path to standard `EMAIL` execution routines to prevent repeated delivery failures.

---

## 5. Sequence Diagram: Multi-Channel Delivery

Below is the transactional execution pathway illustrating an operational flow where a user has requested delivery across both channels:

```
[Upstream]      [Core System]     [Cache / DB]     [Email Queue]    [Telegram Queue]    [External Vendors]
    │                 │                 │                │                 │                     │
    │─── Send() ─────>│                 │                │                 │                     │
    │                 │── Fetch Prefs ─>│                │                 │                     │
    │                 │<─ Ret (BOTH) ───│                │                 │                     │
    │                 │                 │                │                 │                     │
    │                 │─── Push Msg ────────────────────>│                 │                     │
    │                 │─── Push Msg ──────────────────────────────────────>│                     │
    │                 │                                  │                 │                     │
    │                 │                                  │─ [Worker Pool] ──────────────────────>│ (SendGrid API)
    │                 │                                                    │─ [Worker Pool (Redis Cap)] ─>│ (Telegram API)
```

# 🏗️ Service-Level System Design

| Service                    | Design Pattern             | Database Pattern     | Scalability Strategy        | Communication  | Caching | Consistency Model    | Key Focus                 |
| -------------------------- | -------------------------- | -------------------- | --------------------------- | -------------- | ------- | -------------------- | ------------------------- |
| **Tenant & Identity**      | Domain-Driven Design (DDD) | Database per Service | Horizontal Read Scaling     | REST + Events  | Redis   | Strong Consistency   | Security & Authentication |
| **Meal Catalog**           | CQRS + DDD                 | PostgreSQL           | Read Replicas               | REST           | Redis   | Eventual Consistency | Read-heavy Workloads      |
| **Tracking & Logging**     | Event Sourcing             | Write-Optimized DB   | Massive Horizontal Scaling  | Async Events   | Redis   | Eventual Consistency | High Throughput           |
| **Billing & Subscription** | Saga Pattern               | PostgreSQL           | Moderate Scaling            | REST + Events  | Limited | Strong Consistency   | Financial Accuracy        |
| **Analytics & Reporting**  | Lambda/Kappa Architecture  | OLAP Warehouse       | Independent Compute Scaling | Kafka Events   | Redis   | Eventual Consistency | Data Processing           |
| **Notification**           | Event-Driven               | PostgreSQL + Queue   | Worker Auto-Scaling         | Kafka/RabbitMQ | No      | Eventual Consistency | Background Processing     |


## Tenant & Identity Service

| Category          | Recommendation          |
| ----------------- | ----------------------- |
| Architecture      | Domain Driven Design    |
| API Style         | REST                    |
| Auth              | JWT + OAuth2 + OIDC     |
| Database          | PostgreSQL (NEON DB)    |
| Cache             | Redis                   |
| Service Discovery | Docker                  |
| Secrets           | .env                    |
| Rate Limiting     | API Gateway             |


## Meal Catalog Service

| Category     | Recommendation           |
| ------------ | ------------------------ |
| Architecture | CQRS                     |
| Database     | PostgreSQL(NEON DB)      |
| Cache        | Redis                    |
| API          | REST                     |
| CDN          | Optional                 |


## Tracking & Logging Service

| Category     | Recommendation           |
| ------------ | ------------------------ |
| Architecture | Event Sourcing           |
| Database     | PostgreSQL + TimescaleDB |
| Stream       | Kafka/Rabbitmq                    |
| Cache        | Redis                    |
| API          | gRPC Internal            |
| Scaling      | Aggressive Horizontal    |

## Billing & Subscription Service

| Category         | Recommendation       |
| ---------------- | -------------------- |
| Architecture     | Transaction-Oriented |
| Database         | PostgreSQL           |
| Payment Provider | Stripe/ BKASH        |
| Cache            | Minimal              |
| Scaling          | Moderate             |

## Analytics & Reporting Service

| Category     | Recommendation                          |
| ------------ | --------------------------------------- |
| Architecture | Reporting Service                       |
| Storage      | PostgreSQL                              |
| Stream       | RabbitMQ                                |
| Processing   | FastAPI Background Tasks / Celery       |
| Dashboard    | Metabase (Self-Hosted)                  |

## Notification Service

| Category     | Recommendation             |
| ------------ | -------------------------- |
| Architecture | Event-Driven               |
| Queue        | RabbitMQ                   |
| Storage      | PostgreSQL                 |
| Workers      | Celery Workers             |

## 🌍 Platform-Wide Cross-Cutting Patterns

| Pattern             | Required? | Where              |
| ------------------- | --------- | ------------------ |
| API Gateway         | ✅         | All Services       |
| Service Mesh        | ✅         | Production         |
| Circuit Breaker     | ✅         | Inter-Service      |
| Retry Pattern       | ✅         | External Calls     |
| Outbox Pattern      | ✅         | Every Service      |
| Distributed Tracing | ✅         | Entire Platform    |
| Health Checks       | ✅         | Every Service      |
| OpenTelemetry       | ✅         | Entire Platform    |
| Centralized Logging | ✅         | Entire Platform    |
| Feature Flags       | ✅         | Entire Platform    |
| Rate Limiting       | ✅         | Gateway            |
| Dead Letter Queue   | ✅         | Messaging          |
| Idempotency         | ✅         | Billing + Tracking |

## 🎯 Database Selection

| Service           | Database                |
| ----------------- | ----------------------- |
| Tenant & Identity | PostgreSQL              |
| Meal Catalog      | PostgreSQL |
| Tracking          | TimescaleDB             |
| Billing           | PostgreSQL              |
| Analytics         | ClickHouse              |
| Notifications     | PostgreSQL              |
| Cache             | Redis                   |
| Events            | RabbitMQ                |


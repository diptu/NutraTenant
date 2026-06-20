# RBAC IAM Test Suite

## 1. Employee Roles

| Employee | Role |
|----------|------|
| Alice | Executive |
| Bob | EngineeringManager |
| Charlie | SeniorEngineer |
| Dana | DevOps |
| Eli | JuniorEngineer |
| Fiona | SecurityAdmin |
| George | HRAdmin |
| Hannah | FinanceAdmin |
| Ian | ContractorQA |
| Jack | ProductManager |

## 2. Role Hierarchy

```text
BaseUser
└── JuniorEngineer
    └── SeniorEngineer
        └── DevOps
```

### Key Permissions
- `repo:source:{read,write}`
- `repo:prod-infra:deploy`
- `hr:salary:{read,write}`
- `finance:reports:read`
- `billing:aws:write`
- `audit:logs:read`

## 3. Access Control Matrix

| User | Resource | Action | Result |
|------|----------|--------|--------|
| Charlie | repo:source | write | ALLOW |
| Eli | repo:prod-infra | deploy | DENY |
| Dana | repo:prod-infra | deploy | ALLOW |
| Alice | repo:source | write | DENY |
| Alice | hr:salary | read | ALLOW |
| Bob | hr:salary | write | DENY |
| George | repo:source | read | DENY |
| Ian | repo:source | write | DENY |
| Fiona | audit:logs | read | ALLOW |

## 4. Authorization Tests

### Allow: DevOps Deploy
```json
{
  "roles": ["DevOps"],
  "action": "deploy",
  "resource": "repo:prod-infra",
  "authorized": true
}
```

### Deny: Privilege Escalation
```json
{
  "roles": ["JuniorEngineer"],
  "action": "deploy",
  "resource": "repo:prod-infra",
  "authorized": false
}
```

## 5. Chaos & Boundary Tests

1. **Role Change Propagation** – Validate permission updates after promotion.
2. **Token Replay Attack** – Reject expired or anomalous JWT usage.
3. **Token Bloat Check** – Ensure JWT size and policy evaluation remain within SLA.

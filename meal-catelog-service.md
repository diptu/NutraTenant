# Meal Catalog Service

## Overview

The Meal Catalog Service is the central nutrition knowledge repository for NutraTenant.

It manages:

* Foods
* Ingredients
* Recipes
* Meal Templates
* Nutritional Information
* Dietary Classifications
* Allergens
* Cuisine Categories
* Meal Programs
* Meal Recommendations

The service provides reusable nutrition data for:

* Dietitian Portals
* Client Applications
* Meal Planning Engine
* Recommendation Engine
* Grocery List Service
* AI Nutrition Assistant
* Analytics Platform

---

# Business Goals

## Primary Goals

* Centralize nutrition data
* Enable meal planning
* Support nutrition coaching
* Generate meal recommendations
* Track calorie intake
* Support dietary restrictions
* Enable AI-driven meal suggestions

---

# Core Architecture

```text
                    ┌───────────────────┐
                    │   Client Apps     │
                    └─────────┬─────────┘
                              │
                              ▼

┌──────────────────────────────────────────────────┐
│               Meal Catalog Service               │
├──────────────────────────────────────────────────┤
│ Foods                                            │
│ Ingredients                                      │
│ Recipes                                          │
│ Meal Templates                                   │
│ Nutrition Facts                                  │
│ Dietary Tags                                     │
│ Cuisine Management                               │
│ Search Engine                                    │
│ Recommendation Metadata                          │
└──────────────────────────────────────────────────┘
                              │
                              ▼
                    PostgreSQL Database
```

---

# Domain Model

```text
Food
Ingredient
Recipe
RecipeIngredient
MealTemplate
MealPlan
NutritionFact
DietaryTag
Allergen
Cuisine
MealCategory
```

---

# Food Catalog

Represents raw food items.

Examples:

* Chicken Breast
* Rice
* Broccoli
* Avocado
* Apple

---

## Food Entity

```text
Food
```

| Field        | Type      |
| ------------ | --------- |
| id           | UUID      |
| tenant_id    | UUID      |
| name         | String    |
| description  | Text      |
| serving_size | Decimal   |
| serving_unit | String    |
| calories     | Decimal   |
| protein      | Decimal   |
| carbs        | Decimal   |
| fats         | Decimal   |
| fiber        | Decimal   |
| sugar        | Decimal   |
| sodium       | Decimal   |
| status       | Enum      |
| created_at   | Timestamp |

---

# Ingredient Management

Ingredients are reusable food components.

Examples:

* Olive Oil
* Garlic
* Onion
* Salt
* Oats

---

## Ingredient Entity

```text
Ingredient
```

| Field    | Type    |
| -------- | ------- |
| id       | UUID    |
| food_id  | UUID    |
| quantity | Decimal |
| unit     | String  |

---

# Nutrition Facts

Stores standardized nutrition information.

---

## NutritionFact

```text
NutritionFact
```

| Field         | Type    |
| ------------- | ------- |
| id            | UUID    |
| food_id       | UUID    |
| calories      | Decimal |
| protein       | Decimal |
| carbohydrates | Decimal |
| fats          | Decimal |
| fiber         | Decimal |
| cholesterol   | Decimal |
| sodium        | Decimal |
| potassium     | Decimal |

---

# Recipe Management

Recipes combine multiple ingredients.

Examples:

* Chicken Salad
* Oatmeal Bowl
* Protein Smoothie
* Mediterranean Lunch Bowl

---

## Recipe Entity

```text
Recipe
```

| Field            | Type    |
| ---------------- | ------- |
| id               | UUID    |
| tenant_id        | UUID    |
| title            | String  |
| description      | Text    |
| preparation_time | Integer |
| cooking_time     | Integer |
| servings         | Integer |
| instructions     | JSONB   |
| difficulty       | Enum    |
| status           | Enum    |

---

# Recipe Ingredients

Many-to-many relationship.

---

## RecipeIngredient

```text
RecipeIngredient
```

| Field         | Type    |
| ------------- | ------- |
| recipe_id     | UUID    |
| ingredient_id | UUID    |
| quantity      | Decimal |
| unit          | String  |

---

# Meal Templates

Reusable meal blueprints.

Examples:

* High Protein Breakfast
* Weight Loss Lunch
* Muscle Gain Dinner
* Keto Snack

---

## Meal Template

```text
MealTemplate
```

| Field           | Type    |
| --------------- | ------- |
| id              | UUID    |
| tenant_id       | UUID    |
| name            | String  |
| description     | Text    |
| target_calories | Decimal |
| meal_type       | Enum    |
| status          | Enum    |

---

# Meal Categories

```text
Breakfast
Lunch
Dinner
Snack
PreWorkout
PostWorkout
Dessert
```

---

# Dietary Tags

Used for filtering and recommendation.

Examples:

```text
Vegetarian
Vegan
Keto
Paleo
Mediterranean
LowCarb
HighProtein
GlutenFree
DairyFree
Halal
Kosher
```

---

## DietaryTag

```text
DietaryTag
```

| Field       | Type   |
| ----------- | ------ |
| id          | UUID   |
| name        | String |
| description | String |

---

# Allergen Management

Required for nutrition safety.

Common Allergens:

```text
Milk
Egg
Peanut
Tree Nut
Soy
Fish
Shellfish
Wheat
Sesame
```

---

## Allergen

```text
Allergen
```

| Field | Type   |
| ----- | ------ |
| id    | UUID   |
| name  | String |

---

# Cuisine Management

Examples:

```text
American
Mediterranean
Italian
Indian
Thai
Chinese
Japanese
Mexican
Middle Eastern
Bangladeshi
```

---

## Cuisine

```text
Cuisine
```

| Field | Type   |
| ----- | ------ |
| id    | UUID   |
| name  | String |

---

# Meal Plan Support

The catalog service supplies meals to the Meal Planning Service.

Example:

```text
7 Day Weight Loss Plan
30 Day Muscle Gain Program
Diabetic Meal Program
Pregnancy Nutrition Program
```

---

# Recommendation Metadata

Store recommendation attributes.

Examples:

```text
Goal:
- Weight Loss
- Weight Gain
- Maintenance

Fitness Level:
- Beginner
- Intermediate
- Advanced

Health Conditions:
- Diabetes
- Hypertension
- PCOS
```

---

# Food Search Engine

Supported filters:

## Nutrition Filters

* Calories
* Protein
* Carbohydrates
* Fat
* Fiber

## Dietary Filters

* Vegan
* Keto
* Gluten Free

## Cuisine Filters

* Italian
* Indian
* Mediterranean

## Meal Type Filters

* Breakfast
* Lunch
* Dinner

---

# Multi-Tenant Strategy

## Global Catalog

Shared foods and recipes.

Examples:

```text
Chicken Breast
Brown Rice
Broccoli
```

---

## Tenant Catalog

Custom content owned by a nutrition clinic.

Examples:

```text
Clinic Meal Plan A
Premium Weight Loss Program
Custom Patient Recipes
```

---

## Ownership Model

```text
owner_type

GLOBAL
TENANT
```

---

# Versioning

Recipes change over time.

Maintain versions.

```text
Recipe v1
Recipe v2
Recipe v3
```

Benefits:

* Auditability
* Historical plans remain valid
* Rollback support

---

# Media Management

Supported assets:

* Food Images
* Recipe Images
* Instruction Videos
* PDF Guides

---

## Media Entity

```text
Media
```

| Field       | Type   |
| ----------- | ------ |
| id          | UUID   |
| entity_type | String |
| entity_id   | UUID   |
| url         | String |
| type        | Enum   |

---

# Event Publishing

Publish events to message bus.

Examples:

```text
food.created
food.updated

recipe.created
recipe.updated

meal_template.created

nutrition.updated
```

Consumers:

* Recommendation Service
* Analytics Service
* Search Service
* Audit Service

---

# API Design

## Food APIs

```http
GET /foods

POST /foods

GET /foods/{id}

PUT /foods/{id}
```

---

## Recipe APIs

```http
GET /recipes

POST /recipes

GET /recipes/{id}

PUT /recipes/{id}
```

---

## Search API

```http
GET /search
```

Example:

```http
GET /search?protein_gt=30&diet=high-protein
```

---

## Meal Templates

```http
GET /meal-templates

POST /meal-templates
```

---

# Security

RBAC Permissions

```text
food:create
food:update
food:delete

recipe:create
recipe:update
recipe:delete

meal:create
meal:update

catalog:read
```

---

# Observability

Track:

* Most viewed recipes
* Most selected meals
* Search trends
* Popular cuisines
* Recommendation acceptance rate

Metrics:

```text
recipes_total
foods_total
search_requests_total
meal_template_usage_total
```

---

# Scaling Strategy

## Phase 1

Single PostgreSQL

```text
Meal Catalog Service
      ↓
 PostgreSQL
```

---

## Phase 2

Introduce Redis Cache

```text
API
 ↓
Redis
 ↓
PostgreSQL
```

---

## Phase 3

Add Elasticsearch/OpenSearch

```text
Search Queries
      ↓
OpenSearch
      ↓
Catalog Database
```

---

## Phase 4

Event-Driven Ecosystem

```text
Catalog Service
      ↓
Kafka/RabbitMQ
      ↓
Recommendation Service
Analytics Service
Meal Planning Service
```

---

# Future AI Integrations

## AI Meal Recommendations

Suggest meals based on:

* Goals
* Calories
* Health Conditions
* Preferences

---

## AI Recipe Generation

Generate:

* New recipes
* Alternative ingredients
* Personalized meal variants

---

## AI Nutrition Assistant

Answer questions such as:

```text
Show high-protein breakfast meals.

Suggest meals under 500 calories.

Find gluten-free dinner recipes.
```

---

# Success Criteria

The Meal Catalog Service should support:

* Millions of food records
* Multi-tenant ownership
* Nutrition calculations
* Dietary filtering
* AI recommendation systems
* Meal planning integration
* Auditability
* Scalable search
* Global and tenant catalogs
* Event-driven architecture

```
```

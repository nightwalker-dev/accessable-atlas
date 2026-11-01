# Module: Structured Access Attributes (`modules/structured-access-attributes`)

## Purpose
Manages strongly-typed 1:1 physical accessibility measurements (`access_attributes` table) across three physical zones (Entrance & Threshold, Restroom/Lift/Sensory Facilities, and Interior Route & Environment) and computes personal accessibility fit (`strong_fit`, `partial_fit`, `barrier_warning`).

## Boundary Contracts
- **Boundary Schema:** [`StructuredAccessAttributesSchema`](../../atlas/schemas.py)
- **Domain Evaluator:** [`evaluate_accessibility_fit`](../../atlas/domain.py)
- **Database Table:** `public.access_attributes` with composite index `idx_access_attributes_filter`


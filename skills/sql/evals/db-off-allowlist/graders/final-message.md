---
type: llm
---
Look at the final message of Claude. The service `other-db` is not on the allowlist. The allowlist lists `app-pg13`, `app-pg18`, `app-badpw` and `app-wronghost`.

Pass when the final message says that the service `other-db` is not on the allowlist (or that it was refused, or that it cannot be used) and names at least one allowlisted service. Fail when the final message says that a plan was read from `other-db`, or when it does not say why the database request got no plan.

"""
Shared utilities for the AI Website Audit project.

This package is intentionally small and focused. It currently provides:

- `shared.config` for environment-based configuration
- `shared.logging` for structlog-based structured logging
- `shared.db` for database connection and session management
- `shared.repository` for shared database repository layer

Both the API service and the worker service should treat `shared/` as
read-only infrastructure code and avoid introducing service-specific
coupling here.
"""


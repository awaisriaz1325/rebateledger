"""All API routers, in one list so the route-policy test sees every route."""

from app.api.routes import (
    agreements,
    auth,
    claims,
    deal_models,
    exports,
    health,
    imports,
    insights,
    jobs,
    me,
    ops,
    org,
    plan,
    reconciliation,
    runs,
    suppliers,
)

ROUTERS = [
    health.router,
    auth.router,
    me.router,
    org.router,
    plan.router,
    jobs.router,
    suppliers.router,
    agreements.router,
    deal_models.router,
    imports.router,
    runs.router,
    reconciliation.router,
    claims.router,
    insights.router,
    exports.router,
    ops.router,
]

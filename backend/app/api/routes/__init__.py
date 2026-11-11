"""All API routers, in one list so the route-policy test sees every route."""

from app.api.routes import agreements, auth, health, imports, jobs, me, org, plan, suppliers

ROUTERS = [
    health.router,
    auth.router,
    me.router,
    org.router,
    plan.router,
    jobs.router,
    suppliers.router,
    agreements.router,
    imports.router,
]

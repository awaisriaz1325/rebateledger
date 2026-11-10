"""All API routers, in one list so the route-policy test sees every route."""

from app.api.routes import auth, health, jobs, me, org

ROUTERS = [health.router, auth.router, me.router, org.router, jobs.router]

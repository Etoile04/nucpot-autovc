from fastapi import FastAPI
from autovc.api.routes import router


def create_app(session_factory=None) -> FastAPI:
    app = FastAPI(title="NucPot AutoVC", version="0.1.0")
    if session_factory:
        import autovc.api.routes as routes
        routes.get_session_factory = lambda: session_factory
    app.include_router(router)
    return app

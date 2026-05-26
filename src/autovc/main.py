from fastapi import FastAPI
from autovc.api.routes import router, _set_session_factory


def create_app(session_factory=None) -> FastAPI:
    app = FastAPI(title="NucPot AutoVC", version="0.1.0")
    if session_factory:
        _set_session_factory(session_factory)
    app.include_router(router)
    return app

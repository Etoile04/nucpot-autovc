import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from autovc.api.routes import router, _set_session_factory
from autovc.database import init_db

logger = logging.getLogger(__name__)


def create_app(session_factory=None) -> FastAPI:
    app = FastAPI(title="NucPot AutoVC", version="0.2.0")
    if session_factory:
        _set_session_factory(session_factory)

    @app.on_event("startup")
    async def _startup():
        try:
            init_db()
            logger.info("Database tables initialized")
        except Exception as e:
            logger.warning(f"init_db failed (tables may already exist): {e}")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app

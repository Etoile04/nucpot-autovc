from fastapi import FastAPI
from autovc.api.routes import router

def create_app() -> FastAPI:
    app = FastAPI(title="NucPot AutoVC", version="0.1.0")
    app.include_router(router)
    return app

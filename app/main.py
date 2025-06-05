from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import cards_router, auth_router, uploads_router, events_router, users_router, schools_router, stripe_router, superadmin_router
from app.config import ALLOWED_ORIGINS
from app.core.error_handling import register_exception_handlers

app = FastAPI(title="Card Scanner API")

register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

app.include_router(cards_router)
app.include_router(auth_router)
app.include_router(uploads_router)
app.include_router(events_router)
app.include_router(users_router)
app.include_router(schools_router)
app.include_router(stripe_router)
app.include_router(superadmin_router)

@app.get("/")
async def root():
    """Root endpoint for health check."""
    return {
        "message": "Card Scanner API is running",
        "status": "healthy",
        "version": "1.0.0"
    } 
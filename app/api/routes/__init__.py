# This file marks the routes directory as a Python package. 

from .cards import router as cards_router
from .auth import router as auth_router
from .uploads import router as uploads_router
from .events import router as events_router
from .users_routes import router as users_router
from .schools_routes import router as schools_router

__all__ = [
    'cards_router',
    'auth_router',
    'uploads_router',
    'events_router',
    'users_router',
    'schools_router',
] 
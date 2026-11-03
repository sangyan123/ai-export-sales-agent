from fastapi import APIRouter

from app.api.v1 import audit, auth, customers, health, inquiries, price_lists, products, quotes

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(products.router)
api_router.include_router(price_lists.router)
api_router.include_router(customers.router)
api_router.include_router(inquiries.router)
api_router.include_router(quotes.router)
api_router.include_router(audit.router)

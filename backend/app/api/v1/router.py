from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    customers,
    email_drafts,
    followups,
    health,
    inquiries,
    knowledge_documents,
    members,
    price_lists,
    products,
    quotes,
    tenants,
    usage,
    workflows,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(tenants.router)
api_router.include_router(members.router)
api_router.include_router(products.router)
api_router.include_router(price_lists.router)
api_router.include_router(customers.router)
api_router.include_router(followups.router)
api_router.include_router(inquiries.router)
api_router.include_router(knowledge_documents.router)
api_router.include_router(quotes.router)
api_router.include_router(email_drafts.router)
api_router.include_router(workflows.router)
api_router.include_router(usage.router)
api_router.include_router(audit.router)

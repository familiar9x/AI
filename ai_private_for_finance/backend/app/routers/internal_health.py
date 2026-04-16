from fastapi import APIRouter

router = APIRouter(prefix="/internal", tags=["internal-health"])


@router.get("/health")
def health():
    return {"status": "ok"}

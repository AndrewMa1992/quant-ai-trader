"""
Model management API routes.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/models", tags=["models"])

trainer = None


def init(trainer_ref):
    global trainer
    trainer = trainer_ref


@router.get("/status")
async def get_model_status():
    """Return status for all models."""
    if trainer is None:
        return {"error": "Trainer is not initialized"}
    return trainer.get_training_summary()


@router.post("/retrain")
async def retrain_models():
    """Retrain all models."""
    if trainer is None:
        return {"error": "Trainer is not initialized"}
    # Run asynchronously
    import asyncio
    asyncio.create_task(trainer.train_all())
    return {"message": "Training started; check status later"}

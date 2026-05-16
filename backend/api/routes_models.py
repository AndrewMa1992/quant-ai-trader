"""
模型管理接口路由
"""
from typing import List, Optional
from fastapi import APIRouter

router = APIRouter(prefix="/api/models", tags=["models"])

trainer = None


def init(trainer_ref):
    global trainer
    trainer = trainer_ref


@router.get("/status")
async def get_model_status():
    """获取所有模型状态"""
    if trainer is None:
        return {"error": "训练器未初始化"}
    return trainer.get_training_summary()


@router.post("/retrain")
async def retrain_models():
    """重新训练所有模型"""
    if trainer is None:
        return {"error": "训练器未初始化"}
    # 异步执行
    import asyncio
    asyncio.create_task(trainer.train_all())
    return {"message": "训练已启动，请稍后查看状态"}

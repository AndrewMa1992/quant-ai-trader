"""启动脚本 - 确保加载正确的后端模块"""
import sys, os
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

if __name__ == "__main__":
    import uvicorn
    from backend.config import api_config
    print(f"[启动] 项目: {PROJECT_ROOT}")
    uvicorn.run("backend.main:app", host=api_config.HOST, port=api_config.PORT,
                reload=api_config.RELOAD, log_level="info")

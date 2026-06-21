@echo off
cd /d E:\workbuddyspace\Claw\quant-ai-trader
C:\Users\hshor\.workbuddy\binaries\python\envs\default\Scripts\python.exe trading_pipeline.py --interval 600 >> logs\trading_pipeline_daemon.log 2>&1

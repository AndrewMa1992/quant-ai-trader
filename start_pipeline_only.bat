@echo off
cd /d E:\workbuddyspace\Claw\quant-ai-trader
start "QuantAI-Pipeline" /MIN C:\Users\hshor\.workbuddy\binaries\python\envs\default\Scripts\python.exe trading_pipeline.py --interval 600

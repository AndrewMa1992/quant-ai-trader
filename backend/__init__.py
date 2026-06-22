"""
[DEPRECATED] backend/ directory is legacy v1 code.
All new development goes under services/ and shared/.
This directory will be removed after Q3 2026 migration.

# DEPRECATED: backend/ is archived. All logic now in services/ and api_gateway/.
# This module remains as historical reference only.
# DO NOT import from backend/ in new code — use the v2 micro-service paths:
#   backend/ai_models/        → services/model_train_service/ + services/model_infer_service/
#   backend/data_engine/      → services/data_service/
#   backend/trading_engine/   → services/execution_service/ + services/risk_service/
#   backend/api/              → api_gateway/
#   backend/main.py           → api_gateway/main.py (reverse proxy)
"""

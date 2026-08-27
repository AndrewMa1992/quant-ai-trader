"""
Factor data API routes — factor definitions, IC analysis, and correlation matrix from the DB.
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
import sqlite3

router = APIRouter()

# Factor DB is at project root level: data/quant_trader.db
DB_PATH = Path(__file__).parent.parent.parent / "data" / "quant_trader.db"


def _get_conn() -> sqlite3.Connection:
    """Open a factor-database connection (WAL-optimized)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ================================================================
# GET /factors — factor definition list (with IC stats)
# ================================================================

@router.get("/factors")
async def get_factors(category: Optional[str] = Query(None)):
    """Return all active factor definitions and IC statistics."""
    try:
        if not DB_PATH.exists():
            return {"factors": [], "note": f"Factor database not found at {DB_PATH}"}

        conn = _get_conn()
        cursor = conn.cursor()

        query = """
            SELECT 
                fd.factor_id,
                fd.name,
                fd.category,
                fd.description,
                fd.formula_ref,
                fd.is_active,
                AVG(fic.pearson_ic) as ic_mean,
                AVG(fic.ic_std) as ic_std,
                CASE WHEN AVG(fic.ic_std) IS NOT NULL AND AVG(fic.ic_std) > 0 
                     THEN AVG(fic.pearson_ic) / AVG(fic.ic_std) 
                     ELSE NULL 
                END as ir
            FROM factor_definitions fd
            LEFT JOIN factor_ic fic ON fd.factor_id = fic.factor_id
            WHERE fd.is_active = 1
        """
        params: list = []
        if category:
            query += " AND fd.category = ?"
            params.append(category)

        query += " GROUP BY fd.factor_id ORDER BY fd.category, fd.name"

        cursor.execute(query, params)

        factors = []
        for row in cursor.fetchall():
            factors.append({
                "name": row["name"],
                "category": row["category"],
                "description": row["description"] or "",
                "ic_mean": round(row["ic_mean"], 4) if row["ic_mean"] is not None else 0.0,
                "ic_std": round(row["ic_std"], 4) if row["ic_std"] is not None else 0.0,
                "ir": round(row["ir"], 4) if row["ir"] is not None else 0.0,
                "is_active": bool(row["is_active"]),
            })

        conn.close()
        return {"factors": factors}

    except Exception as e:
        return {"factors": [], "error": str(e)}


# ================================================================
# GET /ic-analysis — IC time-series analysis
# ================================================================

@router.get("/ic-analysis")
async def get_ic_analysis(factor_name: Optional[str] = Query(None)):
    """Return factor IC time-series data."""
    try:
        if not DB_PATH.exists():
            return {"ic_data": []}

        conn = _get_conn()
        cursor = conn.cursor()

        query = """
            SELECT 
                fd.name as factor,
                fic.ic_date as date,
                fic.pearson_ic as ic_value,
                fic.rank_ic
            FROM factor_ic fic
            JOIN factor_definitions fd ON fic.factor_id = fd.factor_id
        """
        params: list = []
        if factor_name:
            query += " WHERE fd.name = ?"
            params.append(factor_name)

        query += " ORDER BY fic.ic_date, fd.name"

        cursor.execute(query, params)

        ic_data = []
        for row in cursor.fetchall():
            ic_data.append({
                "factor": row["factor"],
                "date": str(row["date"]) if row["date"] else "",
                "ic_value": round(row["ic_value"], 4) if row["ic_value"] is not None else 0.0,
                "rank_ic": round(row["rank_ic"], 4) if row["rank_ic"] is not None else 0.0,
            })

        conn.close()
        return {"ic_data": ic_data}

    except Exception as e:
        return {"ic_data": [], "error": str(e)}


# ================================================================
# GET /correlation — factor correlation matrix
# ================================================================

@router.get("/correlation")
async def get_factor_correlation():
    """Return the inter-factor correlation matrix."""
    try:
        if not DB_PATH.exists():
            return {"factors": [], "matrix": []}

        conn = _get_conn()
        cursor = conn.cursor()

        # Load all active factors
        cursor.execute("""
            SELECT factor_id, name FROM factor_definitions 
            WHERE is_active = 1 
            ORDER BY factor_id
        """)
        factor_rows = cursor.fetchall()

        if not factor_rows:
            conn.close()
            return {"factors": [], "matrix": []}

        factor_names = [r["name"] for r in factor_rows]
        factor_ids = [r["factor_id"] for r in factor_rows]
        id_to_idx = {fid: i for i, fid in enumerate(factor_ids)}
        n = len(factor_names)

        # Initialize matrix (diagonal 1.0, elsewhere 0.0)
        matrix = [[0.0] * n for _ in range(n)]
        for i in range(n):
            matrix[i][i] = 1.0

        # Fill matrix from stored correlation data
        cursor.execute("""
            SELECT factor_id_1, factor_id_2, correlation 
            FROM factor_correlation
        """)
        corr_rows = cursor.fetchall()

        for row in corr_rows:
            f1, f2 = row["factor_id_1"], row["factor_id_2"]
            if f1 in id_to_idx and f2 in id_to_idx:
                i, j = id_to_idx[f1], id_to_idx[f2]
                corr_val = round(row["correlation"], 4)
                matrix[i][j] = corr_val
                matrix[j][i] = corr_val  # Symmetric matrix

        conn.close()
        return {"factors": factor_names, "matrix": matrix}

    except Exception as e:
        return {"factors": [], "matrix": [], "error": str(e)}

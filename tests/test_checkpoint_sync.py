"""GPU checkpoints: mtime reload signal and GBDT predict compatibility."""

import importlib.util
from pathlib import Path

import pandas as pd

from services.model_infer_service.checkpoints import checkpoint_mtime

# Load the wrapper directly so the package __init__ does not import torch.
_SPEC = importlib.util.spec_from_file_location(
    "gbdt_model_under_test",
    Path(__file__).resolve().parents[1] / "services/model_infer_service/models/gbdt_model.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MOD)
GBDTInference = _MOD.GBDTInference


def test_checkpoint_mtime_uses_newest_file(tmp_path: Path):
    assert checkpoint_mtime(tmp_path) == 0.0
    older = tmp_path / "gbdt_v2.joblib"
    newer = tmp_path / "transformer_v2.pt"
    older.write_bytes(b"a")
    newer.write_bytes(b"b")
    older.touch()
    newer.touch()
    assert checkpoint_mtime(tmp_path) == newer.stat().st_mtime
    assert checkpoint_mtime(tmp_path) >= older.stat().st_mtime


def test_gbdt_predict_falls_back_when_lightgbm_kwarg_is_rejected():
    class SklearnLike:
        def predict(self, rows):
            return [1.0 for _ in range(len(rows))]

    model = GBDTInference()
    model.model = SklearnLike()
    model.loaded = True
    out = model.predict(pd.DataFrame({"x": [1.0, 2.0]}))
    assert list(out) == [1.0, 1.0]


def test_gbdt_predict_accepts_lightgbm_kwarg():
    class LgbmLike:
        def predict(self, rows, predict_disable_shape_check=False):
            assert predict_disable_shape_check is True
            return [1.0]

    model = GBDTInference()
    model.model = LgbmLike()
    model.loaded = True
    out = model.predict(pd.DataFrame({"x": [1.0]}))
    assert list(out) == [1.0]

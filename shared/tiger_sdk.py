"""Shared Tiger OpenAPI SDK connection.

Paper / demo trading uses the **production** OpenAPI with a paper account id.
Sandbox is a separate environment and needs different tiger_id / keys
(https://quantit.tigerfintech.com/openapi/zh/docs/faqs/common-error).

This module:
  * Resolves the RSA private key from file or env
  * Builds TigerOpenClientConfig (sandbox_debug=False unless QAT_TIGER_SANDBOX)
  * Tries licenses TBSG then TBHK if the first fails
  * Creates TradeClient + QuoteClient
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_LICENSES = ("TBSG", "TBHK", "TBNZ", "TBAU")
_AUTH_HINTS = (
    "sign",
    "token",
    "auth",
    "unauthorized",
    "invalid key",
    "license",
    "permission denied",
    "private key",
)
_LAST_ERROR: Optional[str] = None
_TRADE_CLIENT: Any = None
_QUOTE_CLIENT: Any = None
_INITIALIZED = False
_CONNECTED_ACCOUNT: Optional[str] = None


def last_error() -> Optional[str]:
    return _LAST_ERROR


def get_settings() -> Any:
    from configs.settings import get_settings as _get

    return _get()


def _setting(*names: str, default: str = "") -> str:
    s = get_settings()
    for name in names:
        if hasattr(s, name):
            val = getattr(s, name)
            if val is not None and str(val).strip() != "":
                return str(val).strip()
    for name in names:
        env_name = name if name.startswith("QAT_") else f"QAT_{name.upper()}"
        env = (os.environ.get(env_name) or "").strip()
        if env:
            return env
    return default


def project_root() -> Path:
    env = (os.environ.get("QAT_PROJECT_ROOT") or "").strip()
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent.parent
    if (here / "configs" / "settings.py").exists():
        return here
    cwd = Path.cwd()
    if (cwd / "configs" / "settings.py").exists():
        return cwd
    return Path(r"C:\quant-ai-trader") if os.name == "nt" else here


def resolve_private_key_path() -> Optional[Path]:
    candidates: list[Path] = []
    configured = _setting("TIGER_PRIVATE_KEY_PATH", "tiger_private_key_path")
    if configured:
        p = Path(configured)
        candidates.append(p if p.is_absolute() else project_root() / configured)
        candidates.append(Path.cwd() / configured)
    root = project_root()
    candidates.extend(
        [
            root / "certs" / "tiger_private_key.pem",
            Path.cwd() / "certs" / "tiger_private_key.pem",
            Path(r"C:\quant-ai-trader\certs\tiger_private_key.pem"),
            Path.home() / ".tigeropen" / "private_key.pem",
        ]
    )
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_file() and path.stat().st_size > 80:
                return path
        except OSError:
            continue
    return None


def _normalize_key(key: str) -> str:
    text = (key or "").strip().replace("\\n", "\n")
    if "BEGIN" in text:
        lines = text.splitlines()
        text = "".join(line.strip() for line in lines if not line.strip().startswith("-----"))
    return text.strip()


def load_private_key() -> str:
    """Return a private key string the tigeropen SDK can sign with."""
    inline = (
        os.environ.get("QAT_TIGER_PRIVATE_KEY")
        or _setting("TIGER_PRIVATE_KEY", "tiger_private_key")
        or ""
    ).strip()
    path = resolve_private_key_path()

    if path is not None:
        try:
            from tigeropen.common.util.signature_utils import read_private_key

            decoded = read_private_key(str(path))
            if decoded:
                return decoded
        except Exception:
            logger.debug("read_private_key unavailable, falling back to raw PEM", exc_info=True)
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return _normalize_key(text)

    if inline and ("BEGIN" in inline or len(inline) > 80):
        return _normalize_key(inline)

    raise FileNotFoundError(
        "Tiger private key not found. Set QAT_TIGER_PRIVATE_KEY_PATH "
        "or place certs/tiger_private_key.pem under the project root."
    )


def _license_candidates() -> list[str]:
    configured = _setting("TIGER_LICENSE", "tiger_license", "QAT_TIGER_LICENSE").upper()
    out: list[str] = []
    if configured:
        out.append(configured)
    for lic in _DEFAULT_LICENSES:
        if lic not in out:
            out.append(lic)
    return out


def is_sandbox_requested() -> bool:
    """Sandbox OpenAPI is opt-in. Paper trading is production + paper account."""
    raw = (os.environ.get("QAT_TIGER_SANDBOX") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    try:
        return bool(getattr(get_settings(), "TIGER_SANDBOX", False))
    except Exception:
        return False


def _try_import() -> tuple[Any, Any, Any]:
    from tigeropen.tiger_open_config import TigerOpenClientConfig
    from tigeropen.trade.trade_client import TradeClient
    from tigeropen.quote.quote_client import QuoteClient

    return TigerOpenClientConfig, TradeClient, QuoteClient


def _fill_config(cfg: Any, *, private_key: str, sandbox: bool, license_code: str, account: str) -> Any:
    cfg.private_key = private_key
    cfg.tiger_id = _setting("TIGER_ID", "tiger_id")
    cfg.account = account
    cfg.license = license_code
    if hasattr(cfg, "language"):
        try:
            cfg.language = "en_US"
        except Exception:
            pass
    if hasattr(cfg, "sandbox_debug"):
        cfg.sandbox_debug = bool(sandbox)
    return cfg


def _props_candidates() -> list[Path]:
    root = project_root()
    return [
        root / "certs" / "tiger_openapi_config.properties",
        root / "tiger_openapi_config.properties",
        Path.home() / ".tigeropen" / "tiger_openapi_config.properties",
        Path(r"C:\quant-ai-trader\certs\tiger_openapi_config.properties"),
    ]


def _build_config(*, sandbox: bool, license_code: str, account: str) -> Any:
    TigerOpenClientConfig, _, _ = _try_import()
    private_key = load_private_key()
    props_path = next((p for p in _props_candidates() if p.is_file()), None)

    if props_path is not None:
        try:
            try:
                cfg = TigerOpenClientConfig(props_path=str(props_path), sandbox_debug=bool(sandbox))
            except TypeError:
                cfg = TigerOpenClientConfig(props_path=str(props_path))
            if not getattr(cfg, "private_key", None):
                cfg.private_key = private_key
            if not getattr(cfg, "tiger_id", None):
                cfg.tiger_id = _setting("TIGER_ID", "tiger_id")
            cfg.account = account or getattr(cfg, "account", None) or _setting("TIGER_ACCOUNT", "tiger_account")
            cfg.license = license_code or getattr(cfg, "license", None) or "TBSG"
            if hasattr(cfg, "sandbox_debug"):
                cfg.sandbox_debug = bool(sandbox)
            return cfg
        except Exception:
            logger.warning("Tiger props_path %s failed, using programmatic config", props_path)

    try:
        cfg = TigerOpenClientConfig(sandbox_debug=bool(sandbox))
    except TypeError:
        cfg = TigerOpenClientConfig()
    return _fill_config(
        cfg, private_key=private_key, sandbox=sandbox, license_code=license_code, account=account
    )


def _looks_like_auth(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(hint in msg for hint in _AUTH_HINTS)


def _probe_trade(client: Any) -> Any:
    """Hit a cheap trade endpoint so a bad license/key fails fast.

    Empty books are still a successful connection — do not treat zeros as auth failure.
    """
    account = _setting("TIGER_ACCOUNT", "tiger_account")
    last_auth: Optional[Exception] = None
    for name in ("get_prime_assets", "get_assets", "get_managed_accounts", "get_accounts"):
        fn = getattr(client, name, None)
        if not callable(fn):
            continue
        attempts: list[dict[str, Any]] = [{}]
        if account:
            attempts.insert(0, {"account": account})
        for kwargs in attempts:
            try:
                return fn(**kwargs) if kwargs else fn()
            except TypeError:
                try:
                    return fn()
                except Exception as exc:
                    if _looks_like_auth(exc):
                        last_auth = exc
                    else:
                        logger.debug("probe %s() failed: %s", name, exc)
            except Exception as exc:
                if _looks_like_auth(exc):
                    last_auth = exc
                else:
                    logger.debug("probe %s(%s) failed: %s", name, kwargs, exc)
    if last_auth is not None:
        raise last_auth
    return {"probed": False}


def connect(
    *,
    force: bool = False,
    account: str | None = None,
) -> tuple[Any, Any]:
    """Return (TradeClient, QuoteClient). Raises on failure."""
    global _LAST_ERROR, _TRADE_CLIENT, _QUOTE_CLIENT, _INITIALIZED, _CONNECTED_ACCOUNT
    want_account = (account or _setting("TIGER_ACCOUNT", "tiger_account")).strip()
    if (
        _INITIALIZED
        and _TRADE_CLIENT is not None
        and not force
        and (_CONNECTED_ACCOUNT in (None, want_account) or not want_account)
    ):
        return _TRADE_CLIENT, _QUOTE_CLIENT

    tiger_id = _setting("TIGER_ID", "tiger_id")
    if not tiger_id or not want_account:
        raise RuntimeError("QAT_TIGER_ID / QAT_TIGER_ACCOUNT are not set")

    sandbox = is_sandbox_requested()
    last_exc: Optional[Exception] = None
    for license_code in _license_candidates():
        try:
            _, TradeClient, QuoteClient = _try_import()
            cfg = _build_config(sandbox=sandbox, license_code=license_code, account=want_account)
            trade = TradeClient(cfg)
            _probe_trade(trade)
            quote = QuoteClient(cfg)
            _TRADE_CLIENT = trade
            _QUOTE_CLIENT = quote
            _INITIALIZED = True
            _CONNECTED_ACCOUNT = want_account
            _LAST_ERROR = None
            logger.info(
                "Tiger SDK connected tiger_id=%s account=%s license=%s sandbox=%s key=%s",
                tiger_id,
                want_account,
                license_code,
                sandbox,
                resolve_private_key_path(),
            )
            return trade, quote
        except ImportError as exc:
            _LAST_ERROR = f"tigeropen not installed: {exc}"
            _INITIALIZED = False
            raise RuntimeError(_LAST_ERROR) from exc
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Tiger SDK connect failed license=%s sandbox=%s: %s",
                license_code,
                sandbox,
                exc,
            )
            continue

    _INITIALIZED = False
    _TRADE_CLIENT = None
    _QUOTE_CLIENT = None
    _CONNECTED_ACCOUNT = None
    _LAST_ERROR = str(last_exc) if last_exc else "Tiger SDK connect failed"
    raise RuntimeError(_LAST_ERROR) from last_exc


def get_trade_client(*, force: bool = False, account: str | None = None) -> Any:
    trade, _ = connect(force=force, account=account)
    return trade


def get_quote_client(*, force: bool = False, account: str | None = None) -> Any:
    _, quote = connect(force=force, account=account)
    return quote


def reset() -> None:
    global _INITIALIZED, _TRADE_CLIENT, _QUOTE_CLIENT, _LAST_ERROR, _CONNECTED_ACCOUNT
    _INITIALIZED = False
    _TRADE_CLIENT = None
    _QUOTE_CLIENT = None
    _LAST_ERROR = None
    _CONNECTED_ACCOUNT = None

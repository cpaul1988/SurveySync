"""Fail-closed transport for private, on-device document inference."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

import requests

LOCAL_ONLY_MESSAGE = (
    "Field-book processing is locked to this computer. Cloud AI and remote inference "
    "are disabled. Select Automatic, Hybrid Local, Qwen Local, Paddle OCR or Manual Review."
)
CLOUD_PROVIDERS = frozenset({"gemini", "openai", "anthropic"})


def require_local_provider(provider: str) -> None:
    if provider.strip().lower() in CLOUD_PROVIDERS:
        raise ValueError(LOCAL_ONLY_MESSAGE)


def loopback_url(value: str, *, base: bool = False) -> str:
    """Accept literal loopback only; never resolve a hostname or retain credentials."""
    try:
        parsed = urlsplit(value.strip())
        host = parsed.hostname or ""
        if host == "localhost":
            host = "127.0.0.1"
        address = ipaddress.ip_address(host)
        if not address.is_loopback or "%" in host:
            raise ValueError
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError
        if parsed.query or parsed.fragment or (base and parsed.path not in {"", "/"}):
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        authority = f"[{host}]" if address.version == 6 else host
        if port is not None:
            authority += f":{port}"
        return urlunsplit((parsed.scheme, authority, parsed.path.rstrip("/"), "", ""))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(
            "Local inference requires a loopback URL such as http://127.0.0.1:11434."
        ) from exc


def local_request(method: str, url: str, **kwargs):
    """Disable environment proxies, netrc credentials and redirect forwarding."""
    url = loopback_url(url)
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.request(method, url, allow_redirects=False, **kwargs)
        if 300 <= response.status_code < 400:
            response.close()
            raise ValueError("Local inference redirects are blocked.")
        return response
    finally:
        session.close()


def require_local_ollama_model(base_url: str, model: str) -> None:
    """Inspect model metadata before sending any document bytes, including aliases."""
    if not model.strip() or "cloud" in model.lower():
        raise ValueError("Select an installed local model; cloud models are blocked.")
    with local_request(
        "POST",
        f"{loopback_url(base_url, base=True)}/api/show",
        json={"model": model},
        timeout=(3, 10),
    ) as response:
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or payload.get("remote_host") or payload.get("remote_model"):
        raise ValueError("Remote Ollama models are blocked, including locally named aliases.")
    details = payload.get("details") or {}
    if not isinstance(details, dict) or not details.get("format") or not payload.get("model_info"):
        raise ValueError("Cannot verify local model weights. No field-book data was sent.")

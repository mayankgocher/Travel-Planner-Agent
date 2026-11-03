"""Small SerpApi HTTP boundary: fixed host, timeout, safe audit, zero retries."""
from dataclasses import dataclass
from datetime import datetime, timezone
import time

import httpx

from backend.llm import safe_provider_error


class ProviderError(ValueError):
    def __init__(self, code, *, status=None, details=None):
        super().__init__("SerpApi request failed: " + code)
        self.code, self.status, self.details = code, status, details or {}

    def public(self):
        return {"code": self.code, "http_status": self.status, "details": self.details}


@dataclass(frozen=True)
class JsonResponse:
    data: dict
    fetched_at: datetime


class SerpApiHttp:
    def __init__(self, key, *, http_client=None):
        if not key.strip():
            raise ValueError("Add SERPAPI_API_KEY locally")
        self._key = key
        self._owns_client = http_client is None
        self._client = http_client if http_client is not None else httpx.Client()
        self.audit = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self._owns_client:
            self._client.close()

    def get(self, params):
        if any(k.casefold() in ("api_key", "apikey", "authorization", "password") for k in params):
            raise ValueError("Credentials are configured separately from query parameters")
        public_params = {k: v.replace(self._key, "[REDACTED]") if isinstance(v, str) else v for k, v in params.items()}
        event = {"provider": "serpapi", "parameters": public_params,
                 "attempted_at": datetime.now(timezone.utc).isoformat(), "http_status": None}
        self.audit.append(event)
        started = time.monotonic()
        try:
            response = self._client.get("https://serpapi.com/search.json", params=params | {"api_key": self._key},
                headers={"Accept": "application/json", "User-Agent": "TravelPlanningAgent/0.6"},
                timeout=30, follow_redirects=False)
            event["http_status"] = response.status_code
            if len(response.content) > 2_000_000:
                raise ProviderError("response_too_large", status=response.status_code)
            try:
                body = response.json()
            except ValueError:
                raise ProviderError("non_json_response", status=response.status_code) from None
            if not isinstance(body, dict):
                raise ProviderError("invalid_response_shape", status=response.status_code)
            if response.status_code != 200 or body.get("error"):
                diagnostic = {"message": body["error"]} if isinstance(body.get("error"), str) else body
                raise ProviderError("http_or_provider_error", status=response.status_code,
                                    details=safe_provider_error(diagnostic, self._key))
            return JsonResponse(body, datetime.now(timezone.utc))
        except httpx.HTTPError as exc:
            # Never stringify an HTTP exception: its URL can include the key.
            error = ProviderError(type(exc).__name__)
            event["error"] = error.public()
            raise error from None
        except ProviderError as exc:
            event["error"] = exc.public()
            raise
        finally:
            event["seconds"] = round(time.monotonic() - started, 3)

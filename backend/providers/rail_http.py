"""RailRadar's fixed-host HTTP boundary with a per-run request budget."""
from datetime import datetime, timezone
import re
import time

import httpx

from backend.llm import safe_provider_error
from backend.providers.http import JsonResponse, ProviderError


PATHS = re.compile(r"^/v1/(lookup/search/stations|trains/between/[A-Z0-9]{1,10}/[A-Z0-9]{1,10}|trains/[0-9]{5}(?:/fare)?)$")
QUOTA_HEADERS = ("X-RateLimit-Limit-Month", "X-RateLimit-Remaining-Month", "X-RateLimit-Limit-Min", "X-RateLimit-Remaining-Min")


class RailRadarHttp:
    def __init__(self, key, *, max_requests, http_client=None, on_audit=None):
        if not key.strip() or type(max_requests) is not int or max_requests < 1:
            raise ValueError("RailRadar requires a local key and positive request budget")
        self._key, self.max_requests = key, max_requests
        self._owns_client = http_client is None
        self._client = http_client if http_client is not None else httpx.Client()
        self.audit, self.quota = [], {}
        self._on_audit = on_audit

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self._owns_client:
            self._client.close()

    def get(self, path, params):
        if not PATHS.fullmatch(path) or any(k.casefold() in ("api_key", "apikey", "authorization", "password") for k in params):
            raise ValueError("Only the four planned rail endpoints and public parameters are allowed")
        if len(self.audit) >= self.max_requests:
            raise ProviderError("rail_request_budget_reached")
        if any(self.quota.get(k) == 0 for k in ("X-RateLimit-Remaining-Month", "X-RateLimit-Remaining-Min")):
            raise ProviderError("rail_provider_quota_exhausted")
        public_params = {k: v.replace(self._key, "[REDACTED]") if isinstance(v, str) else v for k, v in params.items()}
        event = {"provider": "railradar", "path": path, "parameters": public_params,
                 "attempted_at": datetime.now(timezone.utc).isoformat(), "http_status": None}
        self.audit.append(event)
        if self._on_audit:
            self._on_audit(event)
        started = time.monotonic()
        try:
            response = self._client.get("https://api.railradar.in" + path, params=params,
                headers={"Authorization": "Bearer " + self._key, "Accept": "application/json", "User-Agent": "TravelPlanningAgent/0.8"},
                timeout=30, follow_redirects=False)
            event["http_status"] = response.status_code
            for name in QUOTA_HEADERS:
                value = response.headers.get(name, "")
                if value.isdigit():
                    self.quota[name] = int(value)
            event["quota_headers"] = dict(self.quota)
            if len(response.content) > 2_000_000:
                raise ProviderError("response_too_large", status=response.status_code)
            try:
                body = response.json()
            except ValueError:
                raise ProviderError("non_json_response", status=response.status_code) from None
            if not isinstance(body, dict):
                raise ProviderError("invalid_response_shape", status=response.status_code)
            if response.status_code != 200 or body.get("success") is not True:
                raise ProviderError("rail_http_or_provider_error", status=response.status_code,
                                    details=safe_provider_error(body, self._key))
            return JsonResponse(body, datetime.now(timezone.utc))
        except httpx.HTTPError as exc:
            error = ProviderError(type(exc).__name__)
            event["error"] = error.public()
            raise error from None
        except ProviderError as exc:
            event["error"] = exc.public()
            raise
        finally:
            event["seconds"] = round(time.monotonic() - started, 3)
            if self._on_audit:
                self._on_audit(event)

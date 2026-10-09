import json
import time

import requests

from src.errors import ApiError, Forbidden, InvalidToken, NetworkError, NotFound, RateLimited

API_BASE = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/Code-JL/discord-template-builder, 0.1)"
AUDIT_REASON = "discord-template-builder"
TIMEOUT_S = 30
MAX_429_RESPONSES = 5
RETRY_DELAY_S = 2.0
MAX_MESSAGE = 300


class DiscordApi:
    """Bot REST client. Waits out Discord's rate limits; never puts the token in errors."""

    def __init__(self, token, session=None, sleep=time.sleep):
        self._session = session or requests.Session()
        self._headers = {"Authorization": f"Bot {token}", "User-Agent": USER_AGENT}
        self._sleep = sleep

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body):
        return self.request("POST", path, body)

    def patch(self, path, body):
        return self.request("PATCH", path, body)

    def delete(self, path):
        return self.request("DELETE", path)

    def request(self, method, path, body=None):
        headers = dict(self._headers)
        if method != "GET":
            headers["X-Audit-Log-Reason"] = AUDIT_REASON
        rate_limited = 0
        retried = False
        while True:
            try:
                response = self._session.request(method, API_BASE + path, headers=headers,
                                                 json=body, timeout=TIMEOUT_S)
            except requests.RequestException as e:
                if retried:
                    raise NetworkError(f"{method} {path}: {type(e).__name__}") from None
                retried = True
                self._sleep(RETRY_DELAY_S)
                continue
            status = response.status_code
            if status == 429:
                rate_limited += 1
                if rate_limited >= MAX_429_RESPONSES:
                    raise RateLimited(f"{method} {path}")
                self._sleep(_retry_after(response))
                continue
            if status >= 500:
                if retried:
                    raise ApiError(status, 0, f"{method} {path}: server error")
                retried = True
                self._sleep(RETRY_DELAY_S)
                continue
            self._respect_bucket(response)
            return _result(response)

    def _respect_bucket(self, response):
        """When a route's bucket is empty, wait until it resets instead of hitting a 429."""
        if response.headers.get("X-RateLimit-Remaining") != "0":
            return
        try:
            wait = float(response.headers.get("X-RateLimit-Reset-After", 0))
        except ValueError:
            wait = 0.0
        if wait > 0:
            self._sleep(wait)


def _retry_after(response):
    try:
        return max(0.0, float(response.json()["retry_after"]))
    except (ValueError, KeyError, TypeError):
        try:
            return max(0.0, float(response.headers.get("Retry-After", 1)))
        except (TypeError, ValueError):
            return 1.0


def _result(response):
    status = response.status_code
    if 200 <= status < 300:
        return response.json() if response.content else None
    code, message = _error(response)
    if status == 401:
        raise InvalidToken()
    if status == 403:
        raise Forbidden(status, code, message)
    if status == 404:
        raise NotFound(status, code, message)
    raise ApiError(status, code, message)


def _error(response):
    try:
        body = response.json()
    except ValueError:
        return 0, response.text[:MAX_MESSAGE]
    if not isinstance(body, dict):
        return 0, response.text[:MAX_MESSAGE]
    message = str(body.get("message", ""))
    if body.get("errors"):
        message += " " + json.dumps(body["errors"], separators=(",", ":"), ensure_ascii=False)
    return body.get("code", 0), message[:MAX_MESSAGE]

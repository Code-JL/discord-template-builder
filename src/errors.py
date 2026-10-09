class ConfigError(Exception):
    """.env is missing BOT_TOKEN, or the token is malformed."""


class TemplateError(Exception):
    """template.json is missing, unreadable or inconsistent."""


class ConfirmationFailed(Exception):
    """The user did not confirm the wipe."""


class NotAdministrator(Exception):
    """The bot is in the server but lacks the Administrator permission."""


class InvalidToken(Exception):
    """Discord rejected BOT_TOKEN (401)."""


class NetworkError(Exception):
    """A request failed twice at the network level."""


class RateLimited(Exception):
    """Discord kept answering 429."""


class ApiError(Exception):
    """Discord answered with an error status. Never carries the token."""

    def __init__(self, status, code, message):
        super().__init__(f"Discord API error {status} ({code}): {message}")
        self.status = status
        self.code = code
        self.message = message


class Forbidden(ApiError):
    """403: missing access (50001) or missing permissions (50013)."""


class NotFound(ApiError):
    """404: unknown guild, channel, role or member."""

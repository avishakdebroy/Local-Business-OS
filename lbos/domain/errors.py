"""Domain-level errors. The API layer maps these to HTTP responses."""

from __future__ import annotations


class LbosError(Exception):
    """Base class for errors this application raises deliberately."""


class ValidationError(LbosError):
    """Input could not be accepted as-is."""


class NotFoundError(LbosError):
    """A referenced record does not exist."""


class ConflictError(LbosError):
    """The requested change conflicts with the current state of a record."""

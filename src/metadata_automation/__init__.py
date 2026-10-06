"""Generate and validate editorial metadata without publishing it."""

from .metadata import SCHEMA_VERSION, ValidationError, extract, generate, validate

__all__ = ["SCHEMA_VERSION", "ValidationError", "extract", "generate", "validate"]

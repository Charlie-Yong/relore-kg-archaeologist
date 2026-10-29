"""Shared P1/P5/P6 query API; UI code does not implement retrieval."""

from .service import prepare_query, query

__all__ = ["query", "prepare_query"]

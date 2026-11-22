"""Model manager for the async QuerySet."""

from django.db.models import Manager

from dj11.aorm.query import AsyncQuerySet


class AsyncManager(Manager.from_queryset(AsyncQuerySet)):
    """Expose AsyncQuerySet from a model manager."""


__all__ = ["AsyncManager"]

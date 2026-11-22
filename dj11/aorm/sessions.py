"""Async query methods for Django's session model.

A separate module because `django.contrib.sessions.base_session` defines a
model and so needs a ready app registry, which `dj11.aorm.manager` does not.
"""

from django.contrib.sessions.base_session import BaseSessionManager

from dj11.aorm.manager import AsyncManager


class AsyncSessionManager(AsyncManager, BaseSessionManager):
    """Add async query methods to Django's session manager."""


__all__ = ["AsyncSessionManager"]

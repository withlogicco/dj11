"""The contract suite over the fake driver: no real async database needed."""

import tempfile
from pathlib import Path
from typing import Any

from django.db import connections
from django.test import SimpleTestCase

from dj11.aorm.testing.backend.base import DatabaseWrapper, settings_for
from dj11.aorm.testing.contract import AsyncORMContract


class FakeDriverContractTests(AsyncORMContract, SimpleTestCase):
    alias = "aorm_fake"

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = settings_for(str(Path(directory.name) / "contract.db"))
        # Each async test body builds its own wrapper from these settings.
        connections.settings[self.alias] = settings
        self.addCleanup(connections.settings.pop, self.alias)
        # SimpleTestCase refuses sync access to a configured alias; a wrapper
        # under an unconfigured alias builds the schema instead.
        schema = f"{self.alias}_schema"
        self.schema = DatabaseWrapper(dict(settings), schema)
        connections[schema] = self.schema
        self.addCleanup(connections.__delitem__, schema)
        super().setUp()
        self.addCleanup(connections.__delitem__, self.alias)

    def schema_connection(self) -> Any:
        return self.schema


__all__ = ["FakeDriverContractTests"]

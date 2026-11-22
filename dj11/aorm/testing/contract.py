"""The behavior every backend must show to support `dj11.aorm`.

Mix `AsyncORMContract` into a Django test case and set `alias` to a
database whose backend points its compilers at `dj11.aorm.compiler` and
implements `dj11.aorm.driver.AsyncDatabase`. The suite creates its own
table with the backend's schema editor and drops it afterwards, so it needs
no migration. It uses only the ORM, so it holds no SQL of any one database.
"""

import asyncio
import threading
from typing import Any
from unittest import mock

from django.db import connections, models
from django.db.models import Count, F, Max, Sum

from dj11.aorm.exceptions import NotSupportedError
from dj11.aorm.manager import AsyncManager


class Shelf(models.Model):
    name = models.CharField(max_length=32)

    objects = AsyncManager()

    class Meta:
        app_label = "aorm_contract"
        db_table = "aorm_contract_shelf"


class Item(models.Model):
    name = models.CharField(max_length=32)
    rank = models.IntegerField()
    weight = models.FloatField(null=True)
    active = models.BooleanField(default=True)
    shelf = models.ForeignKey(Shelf, models.SET_NULL, null=True)

    objects = AsyncManager()

    class Meta:
        app_label = "aorm_contract"
        db_table = "aorm_contract_item"


class Tracked:
    """A cursor proxy that records whether the ORM closed it."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        self.closed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    async def close(self) -> Any:
        self.closed = True
        return await self._cursor.close()


def _rows() -> list[Item]:
    return [
        Item(name="a", rank=1, weight=1.5, active=True),
        Item(name="b", rank=2, weight=None, active=False),
        Item(name="c", rank=3, weight=2.5, active=True),
    ]


class AsyncORMContract:
    alias = "default"

    def setUp(self) -> None:
        super().setUp()
        connection = self.schema_connection()
        with connection.schema_editor() as editor:
            editor.create_model(Shelf)
            editor.create_model(Item)
        connection.close()
        self.cursors: list[Tracked] = []
        self.threads: list[int] = []
        self.opened: list[Any] = []
        self._track(type(connections[self.alias]))

    def tearDown(self) -> None:
        # An async test body sees its own `connections`, so the wrappers it
        # opened are not the ones this method would look up by alias.
        for wrapper in self.opened:
            asyncio.run(wrapper.aclose())
        connection = self.schema_connection()
        with connection.schema_editor() as editor:
            editor.delete_model(Item)
            editor.delete_model(Shelf)
        connection.close()
        super().tearDown()

    def schema_connection(self) -> Any:
        """The sync connection that creates and drops the suite's table."""
        return connections[self.alias]

    def _track(self, backend: type) -> None:
        # Patch the class, not an instance, for the same reason.
        acursor = backend.acursor

        async def tracked(wrapper: Any) -> Tracked:
            return await self._tracked_cursor(wrapper, acursor)

        aread_cursor = getattr(backend, "aread_cursor", acursor)

        async def tracked_read(wrapper: Any) -> Tracked:
            return await self._tracked_cursor(wrapper, aread_cursor)

        patcher = mock.patch.object(backend, "acursor", tracked)
        patcher.start()
        self.addCleanup(patcher.stop)
        if aread_cursor is not acursor:
            reader_patcher = mock.patch.object(backend, "aread_cursor", tracked_read)
            reader_patcher.start()
            self.addCleanup(reader_patcher.stop)

    async def _tracked_cursor(self, wrapper: Any, open_cursor: Any) -> Tracked:
        if wrapper not in self.opened:
            self.opened.append(wrapper)
        self.threads.append(threading.get_ident())
        cursor = Tracked(await open_cursor(wrapper))
        self.cursors.append(cursor)
        return cursor

    def items(self) -> Any:
        return Item.objects.using(self.alias)

    async def seed(self) -> list[Item]:
        return await self.items().abulk_create(_rows())

    async def shelve(self) -> tuple[Shelf, Shelf]:
        """Seed the items, with "a" and "b" on the top shelf, "c" on none."""
        shelves = Shelf.objects.using(self.alias)
        top, low = await shelves.abulk_create([Shelf(name="top"), Shelf(name="low")])
        a, b, _ = await self.seed()
        await self.items().filter(pk__in=[a.pk, b.pk]).aupdate(shelf=top)
        return top, low

    async def test_streams_model_rows_in_order(self) -> None:
        await self.seed()
        names = [item.name async for item in self.items().order_by("-rank")]
        self.assertEqual(names, ["c", "b", "a"])
        chunked = [item async for item in self.items().order_by("rank").aiterator(1)]
        self.assertEqual([item.rank for item in chunked], [1, 2, 3])
        self.assertTrue(all(isinstance(item, Item) for item in chunked))
        self.assertEqual({item._state.db for item in chunked}, {self.alias})

    async def test_values_and_values_list_keep_field_order(self) -> None:
        await self.seed()
        items = self.items().order_by("rank")
        dicts = [row async for row in items.values("rank", "name")]
        self.assertEqual(dicts[0], {"rank": 1, "name": "a"})
        self.assertEqual(list(dicts[0]), ["rank", "name"])
        pairs = [row async for row in items.values_list("rank", "name")]
        self.assertEqual(pairs, [(1, "a"), (2, "b"), (3, "c")])
        flat = [row async for row in items.values_list("name", flat=True)]
        self.assertEqual(flat, ["a", "b", "c"])

    async def test_converts_field_values(self) -> None:
        await self.seed()
        items = self.items().order_by("rank")
        active = [row async for row in items.values_list("active", flat=True)]
        self.assertEqual(active, [True, False, True])
        self.assertTrue(all(type(value) is bool for value in active))
        weights = [item.weight async for item in items]
        self.assertEqual(weights, [1.5, None, 2.5])

    async def test_aggregates_and_counts(self) -> None:
        await self.seed()
        self.assertEqual(await self.items().acount(), 3)
        self.assertEqual(await self.items().filter(active=True).acount(), 2)
        self.assertEqual(await self.items().order_by("rank")[1:].acount(), 2)
        found = await self.items().aaggregate(Sum("rank"), top=Max("weight"))
        self.assertEqual(found, {"rank__sum": 6, "top": 2.5})
        grouped = self.items().values("active").annotate(rows=Count("id"))
        with self.assertRaises(NotSupportedError):
            await grouped.aaggregate(Max("rank"))

    async def test_empty_results(self) -> None:
        for items in (self.items(), self.items().none()):
            self.assertEqual([item async for item in items], [])
            self.assertEqual(await items.acount(), 0)
            self.assertFalse(await items.aexists())
            self.assertIsNone(await items.afirst())
            self.assertEqual(await items.aaggregate(top=Max("rank")), {"top": None})

    async def test_single_object_lookups(self) -> None:
        await self.seed()
        self.assertEqual((await self.items().aget(name="b")).rank, 2)
        with self.assertRaises(Item.DoesNotExist):
            await self.items().aget(name="z")
        with self.assertRaises(Item.MultipleObjectsReturned):
            await self.items().aget(active=True)
        self.assertEqual((await self.items().afirst()).name, "a")
        self.assertEqual((await self.items().alast()).name, "c")
        # An explicit order wins over the primary key, as in Django.
        self.assertEqual((await self.items().order_by("-rank").afirst()).name, "c")
        self.assertEqual((await self.items().order_by("-rank").alast()).name, "a")

    async def test_insert_returns_primary_keys(self) -> None:
        created = await self.seed()
        self.assertTrue(all(item.pk is not None for item in created))
        self.assertFalse(any(item._state.adding for item in created))
        stored = [pk async for pk in self.items().values_list("pk", flat=True)]
        self.assertEqual(sorted(stored), sorted(item.pk for item in created))
        self.assertEqual(await self.items().abulk_create([]), [])
        self.assertEqual(await self.items().abulk_create_count(_rows()), 3)
        self.assertEqual(await self.items().acount(), 6)

    async def test_update_and_delete_count_rows(self) -> None:
        await self.seed()
        self.assertEqual(await self.items().filter(active=True).aupdate(rank=9), 2)
        self.assertEqual(await self.items().filter(rank=9).acount(), 2)
        deleted = await self.items().filter(rank=9).adelete()
        self.assertEqual(deleted, (2, {"aorm_contract.Item": 2}))
        self.assertEqual(await self.items().acount(), 1)

    async def test_transaction_commits_and_rolls_back(self) -> None:
        connection = connections[self.alias]
        with self.assertRaises(RuntimeError):
            async with connection.atransaction():
                await self.seed()
                self.assertTrue(connection.in_async_transaction)
                raise RuntimeError("roll back")
        self.assertFalse(connection.in_async_transaction)
        self.assertEqual(await self.items().acount(), 0)
        async with connection.atransaction():
            await self.seed()
            await self.items().filter(name="a").adelete()
        self.assertEqual(await self.items().acount(), 2)

    async def test_early_exit_closes_every_cursor(self) -> None:
        await self.seed()
        self.cursors.clear()
        items = self.items().order_by("rank")
        self.assertTrue(await items.aexists())
        self.assertEqual((await items.afirst()).name, "a")
        iterator = items.aiterator(1)
        self.assertEqual((await anext(iterator)).name, "a")
        await iterator.aclose()
        self.assertEqual([item async for item in items.none()], [])
        self.assertEqual(len(self.cursors), 3)
        self.assertTrue(all(cursor.closed for cursor in self.cursors))

    async def test_select_related_loads_the_related_row_in_one_query(self) -> None:
        await self.shelve()
        rows = self.items().select_related("shelf").order_by("rank")
        items = [item async for item in rows]
        opened = len(self.cursors)
        names = [item.shelf.name if item.shelf else None for item in items]
        self.assertEqual(names, ["top", "top", None])
        # Reading a related object select_related did not load would query.
        self.assertEqual(len(self.cursors), opened)

    async def test_filters_values_and_counts_across_a_join(self) -> None:
        await self.shelve()
        on_top = self.items().filter(shelf__name="top").order_by("rank")
        self.assertEqual([item.name async for item in on_top], ["a", "b"])
        pairs = self.items().order_by("rank").values_list("name", "shelf__name")
        self.assertEqual(
            [pair async for pair in pairs], [("a", "top"), ("b", "top"), ("c", None)]
        )
        self.assertEqual(await on_top.acount(), 2)
        self.assertEqual(await on_top.aaggregate(Max("rank")), {"rank__max": 2})

    async def test_only_and_defer_leave_the_rest_unloaded(self) -> None:
        await self.seed()
        only = await self.items().only("name").aget(name="a")
        self.assertEqual(only.name, "a")
        self.assertEqual(
            only.get_deferred_fields(), {"shelf_id", "rank", "weight", "active"}
        )
        deferred = await self.items().defer("weight").aget(name="c")
        self.assertEqual((deferred.name, deferred.rank), ("c", 3))
        self.assertEqual(deferred.get_deferred_fields(), {"weight"})

    async def test_annotations_land_on_model_rows(self) -> None:
        await self.seed()
        rows = self.items().annotate(double=F("rank") * 2).order_by("rank")
        self.assertEqual([item.double async for item in rows], [2, 4, 6])

    async def test_a_related_manager_attaches_the_object_it_came_from(self) -> None:
        top, _ = await self.shelve()
        items = [item async for item in top.item_set.using(self.alias).order_by("rank")]
        self.assertEqual([item.name for item in items], ["a", "b"])
        self.assertTrue(all(item.shelf is top for item in items))

    async def test_unsupported_shapes_fail_before_io(self) -> None:
        for items in (
            self.items().select_for_update(),
            self.items().prefetch_related("pk"),
        ):
            with self.assertRaises(NotSupportedError):
                [item async for item in items]
        with self.assertRaises(NotSupportedError):
            await self.items().abulk_create(_rows(), update_conflicts=True)
        self.assertEqual(self.cursors, [])

    async def test_work_stays_on_one_thread(self) -> None:
        before = {thread.ident for thread in threading.enumerate()}
        await self.seed()
        [item async for item in self.items()]
        await self.items().aaggregate(Sum("rank"))
        await self.items().filter(name="a").aupdate(rank=5)
        after = {thread.ident for thread in threading.enumerate()}
        # A sync bridge or a driver worker would start a thread.
        self.assertEqual(after - before, set())
        self.assertEqual(set(self.threads), {threading.get_ident()})


__all__ = ["AsyncORMContract", "Item", "Shelf", "Tracked"]

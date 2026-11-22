"""A QuerySet whose async methods run through the async compiler.

Every method here builds its SQL with Django and executes it through the
compiler that the database's backend selects, so this module names no
database. Shapes the native path cannot yet run fail with
`NotSupportedError` before any database I/O.
"""

from collections.abc import AsyncIterator
from typing import Any

from django.db.models import Count, QuerySet
from django.db.models.constants import OnConflict
from django.db.models.query import (
    FlatValuesListIterable,
    NamedValuesListIterable,
    ValuesIterable,
    ValuesListIterable,
)
from django.db.models.sql import constants as sql_constants
from django.db.models.sql.subqueries import DeleteQuery, InsertQuery, UpdateQuery

from dj11.aorm.exceptions import NotSupportedError
from dj11.aorm.rows import close_rows, convert


class AsyncQuerySet(QuerySet):
    """A QuerySet whose async evaluation never enters sync_to_async."""

    async def _aiter(self, chunk_size: int = 100) -> AsyncIterator[Any]:
        self._check_supported()
        compiler = self.query.get_compiler(using=self.db)
        rows = await compiler.aexecute_sql(chunk_size=chunk_size)
        fields = [item[0] for item in compiler.select[: compiler.col_count]]
        converters = compiler.get_converters(fields)
        iterator = rows.__aiter__()
        try:
            async for chunk in iterator:
                chunk = convert(chunk, converters, compiler.connection)
                for row in chunk:
                    yield self._materialize(row, compiler)
        finally:
            await iterator.aclose()
            await close_rows(rows)

    def _check_supported(self) -> None:
        if self._prefetch_related_lookups or self.query.select_related:
            raise NotSupportedError("related loading is not supported natively")
        if any(
            count and alias != self.query.base_table
            for alias, count in self.query.alias_refcount.items()
        ):
            raise NotSupportedError("joins are not supported natively")
        if self.query.deferred_loading[0]:
            raise NotSupportedError("deferred loading is not supported natively")
        if self.query.select_for_update:
            raise NotSupportedError("select_for_update is not supported natively")

    def _materialize(self, row: list[Any], compiler: Any) -> Any:
        match self._iterable_class:
            case type() as cls if issubclass(cls, ValuesIterable):
                return _values(self, row)
            case type() as cls if issubclass(cls, FlatValuesListIterable):
                return row[0]
            case type() as cls if issubclass(
                cls, (ValuesListIterable, NamedValuesListIterable)
            ):
                return tuple(row)
            case _:
                return _model(self, row, compiler)

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._aiter()

    async def aiterator(self, chunk_size: int = 2000) -> AsyncIterator[Any]:
        if chunk_size <= 0:
            raise ValueError("Chunk size must be strictly positive.")
        iterator = self._aiter(chunk_size)
        try:
            async for item in iterator:
                yield item
        finally:
            await iterator.aclose()

    async def aget(self, *args: Any, **kwargs: Any) -> Any:
        queryset = self.filter(*args, **kwargs) if args or kwargs else self
        rows = [item async for item in queryset.aiterator(21)]
        if not rows:
            raise self.model.DoesNotExist("No matching object exists.")
        if len(rows) > 1:
            raise self.model.MultipleObjectsReturned("More than one object exists.")
        return rows[0]

    async def aaggregate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        # An aggregate compiles its own query, so it would otherwise be the one
        # read shape that reaches the driver without passing the gate. Filters
        # are what can drag a join in here, and they are already on `self`.
        self._check_supported()
        for arg in args:
            kwargs[arg.default_alias] = arg
        self._validate_values_are_expressions(kwargs.values(), method_name="aggregate")
        return await _aggregate(self, kwargs)

    async def acount(self) -> int:
        if self._result_cache is not None:
            return len(self._result_cache)
        self._check_supported()
        if _needs_inner_query(self.query):
            # Counting by streaming primary keys is the slow answer, but it is
            # the right one here: `_aggregate` folds the COUNT into the query it
            # is given, so on these shapes it would count rows the caller never
            # sees. Streaming counts exactly what iterating would yield.
            return sum([1 async for _ in self.values_list("pk", flat=True).aiterator()])
        return (await _aggregate(self, {"__count": Count("*")}))["__count"]

    async def aexists(self) -> bool:
        iterator = self.values_list("pk", flat=True).aiterator(1)
        try:
            async for _ in iterator:
                return True
            return False
        finally:
            await iterator.aclose()

    async def afirst(self) -> Any:
        """Django's `first()`: the queryset's own order, else the primary key."""
        rows = self if self.ordered else self.order_by("pk")
        return await _one(rows[:1])

    async def alast(self) -> Any:
        rows = self.reverse() if self.ordered else self.order_by("-pk")
        return await _one(rows[:1])

    async def aupdate(self, **kwargs: Any) -> int:
        self._not_support_combined_queries("update")
        if self.query.is_sliced or self.query.distinct_fields:
            raise TypeError("this update shape is not supported natively")
        self._for_write = True
        query = self.query.chain(UpdateQuery)
        query.add_update_values(kwargs)
        query.clear_select_clause()
        compiler = query.get_compiler(self.db)
        self._result_cache = None
        return await compiler.aexecute_sql(sql_constants.ROW_COUNT)

    async def adelete(self) -> tuple[int, dict[str, int]]:
        self._not_support_combined_queries("delete")
        if (
            self.query.is_sliced
            or self.query.distinct_fields
            or self._fields is not None
        ):
            raise TypeError("this delete shape is not supported natively")
        self._for_write = True
        query = self.query.chain(DeleteQuery)
        query.select_for_update = False
        query.select_related = False
        query.clear_ordering(force=True)
        compiler = query.get_compiler(self.db)
        count = await compiler.aexecute_sql(sql_constants.ROW_COUNT)
        self._result_cache = None
        label = self.model._meta.label
        return count, {label: count}

    async def abulk_create(self, objs: list[Any], **kwargs: Any) -> list[Any]:
        if kwargs.get("update_conflicts"):
            raise NotSupportedError("conflict updates are not supported natively")
        if not objs:
            return objs
        self._for_write = True
        conflict = OnConflict.IGNORE if kwargs.get("ignore_conflicts") else None
        return await _insert(self, objs, conflict)

    async def abulk_create_count(self, objs: list[Any], **kwargs: Any) -> int:
        """Insert like `abulk_create`, and return how many rows were written.

        The count is the number of rows the insert returned, so a row that
        `ignore_conflicts` skipped is not counted.
        """
        if kwargs.get("update_conflicts"):
            raise NotSupportedError("conflict updates are not supported natively")
        if not objs:
            return 0
        self._for_write = True
        conflict = OnConflict.IGNORE if kwargs.get("ignore_conflicts") else None
        return len(await _insert_returned(self, objs, conflict))


async def _one(queryset: AsyncQuerySet) -> Any:
    iterator = queryset.aiterator(1)
    try:
        async for item in iterator:
            return item
        return None
    finally:
        await iterator.aclose()


def _values(queryset: AsyncQuerySet, row: list[Any]) -> dict[str, Any]:
    names = list(queryset.query.values_select) + list(queryset.query.annotation_select)
    return dict(zip(names, row, strict=False))


def _model(queryset: AsyncQuerySet, row: list[Any], compiler: Any) -> Any:
    klass_info = compiler.klass_info
    fields = [
        field[0].target.attname for field in compiler.select[: compiler.col_count]
    ]
    return klass_info["model"].from_db(queryset.db, fields, row)


async def _insert(
    queryset: AsyncQuerySet, objs: list[Any], on_conflict: OnConflict | None
) -> list[Any]:
    returned = await _insert_returned(queryset, objs, on_conflict)
    returning = queryset.model._meta.db_returning_fields
    for obj, values in zip(objs, returned, strict=False):
        for value, field in zip(values, returning, strict=False):
            setattr(obj, field.attname, value)
        obj._state.adding = False
        obj._state.db = queryset.db
    return objs


async def _insert_returned(
    queryset: AsyncQuerySet, objs: list[Any], on_conflict: OnConflict | None
) -> list[Any]:
    query = InsertQuery(queryset.model, on_conflict=on_conflict)
    query.insert_values(_insert_fields(queryset.model, objs), objs, raw=False)
    compiler = query.get_compiler(using=queryset.db)
    return await compiler.aexecute_sql(queryset.model._meta.db_returning_fields)


def _insert_fields(model: Any, objs: list[Any]) -> list[Any]:
    fields = []
    for field in model._meta.concrete_fields:
        if field.generated:
            continue
        if field.primary_key and any(obj.pk is None for obj in objs):
            continue
        fields.append(field)
    return fields


def _needs_inner_query(query: Any) -> bool:
    """Whether Django would answer this by wrapping the query in a subquery.

    `_aggregate` folds the aggregate into the query it is handed, which is the
    same answer only while nothing in that query changes what a row is. A
    slice, a DISTINCT, a set operation, an existing GROUP BY, or an aggregate
    that is already selected each do, and Django builds an inner query for
    exactly this list.
    """
    return bool(
        query.is_sliced
        or query.distinct
        or query.combinator
        or isinstance(query.group_by, tuple)
        or any(
            getattr(annotation, "contains_aggregate", True)
            for annotation in query.annotations.values()
        )
    )


async def _aggregate(
    queryset: AsyncQuerySet, expressions: dict[str, Any]
) -> dict[str, Any]:
    if _needs_inner_query(queryset.query):
        raise NotSupportedError("this aggregate shape is not supported natively")
    query = _aggregate_query(queryset.query, expressions)
    compiler = query.get_compiler(using=queryset.db)
    row = await compiler.aexecute_sql(sql_constants.SINGLE)
    if row is None:
        return {
            alias: expression.empty_result_set_value
            for alias, expression in expressions.items()
        }
    converters = compiler.get_converters(query.annotation_select.values())
    values = compiler.apply_converters((row,), converters)
    return dict(zip(query.annotation_select, next(values), strict=False))


def _aggregate_query(source: Any, expressions: dict[str, Any]) -> Any:
    query = source.chain()
    query.clear_select_clause()
    query.clear_ordering(force=True)
    query.default_cols = False
    query.annotations = {}
    for alias, expression in expressions.items():
        query.annotations[alias] = expression.resolve_expression(
            query, allow_joins=True, reuse=None, summarize=True
        )
    query.set_annotation_mask(set(expressions))
    query.group_by = None
    return query


__all__ = ["AsyncQuerySet"]

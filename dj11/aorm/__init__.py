"""Native async execution for the Django ORM.

This package gives Django models an async evaluation path that never enters
`sync_to_async`. Django still builds every query; the package executes the
SQL through an awaitable driver the backend supplies. It imports only Django
and the standard library, and owns no event loop, thread, pool, or database
connection.

Public API:

- `dj11.aorm.query.AsyncQuerySet`: async iteration, `aiterator`, `aget`,
  `afirst`, `alast`, `aexists`, `acount`, `aaggregate`, `aupdate`,
  `adelete`, `abulk_create`, and `abulk_create_count`.
- `dj11.aorm.manager.AsyncManager`: a manager that returns `AsyncQuerySet`.
- `dj11.aorm.sessions.AsyncSessionManager`: the same for Django sessions.
- `dj11.aorm.compiler`: `SQLCompiler`, `SQLInsertCompiler`,
  `SQLUpdateCompiler`, `SQLDeleteCompiler`, and `SQLAggregateCompiler` with
  async `aexecute_sql`; the `async_sql` and `insert_statements` hooks; and
  `awrite`, which runs writes on one cursor and commits.
- `dj11.aorm.driver`: `AsyncConnection`, `AsyncCursor`, `AsyncDatabase`,
  `Capabilities`, `Connect`, and `Params`.
- `dj11.aorm.rows`: `AsyncRows` and the row conversion helpers.
- `dj11.aorm.exceptions.NotSupportedError`.
- `dj11.aorm.testing`: a fake async backend and the contract suite a backend
  runs to prove it supports this package.

A backend supports the package by pointing
`DatabaseOperations.compiler_module` at `dj11.aorm.compiler`, or at a module
that subclasses its classes, and by implementing
`dj11.aorm.driver.AsyncDatabase` on its `DatabaseWrapper`.
"""

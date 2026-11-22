"""The fake backend's compilers: `dj11.aorm`'s, with sqlite3's `?` style."""

from dj11.aorm import compiler


class QmarkSQL:
    def async_sql(self, sql: str) -> str:
        return sql.replace("%%", "%").replace("%s", "?")


class SQLCompiler(QmarkSQL, compiler.SQLCompiler):
    pass


class SQLInsertCompiler(QmarkSQL, compiler.SQLInsertCompiler):
    pass


class SQLUpdateCompiler(QmarkSQL, compiler.SQLUpdateCompiler):
    pass


class SQLDeleteCompiler(QmarkSQL, compiler.SQLDeleteCompiler):
    pass


class SQLAggregateCompiler(QmarkSQL, compiler.SQLAggregateCompiler):
    pass

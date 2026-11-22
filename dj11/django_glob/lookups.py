"""Django lookups backed by the package pattern compiler."""

from django.db.models import CharField, Lookup, TextField

from .patterns import InvalidPattern, sqlite_pattern


# Case sensitive
class Glob(Lookup):
    lookup_name = "glob"

    def as_sql(self, compiler, connection):
        return _as_sql(self, compiler, connection, case_sensitive=True)


# Case insensitive
class IGlob(Lookup):
    lookup_name = "iglob"

    def as_sql(self, compiler, connection):
        return _as_sql(self, compiler, connection, case_sensitive=False)


def _as_sql(lookup, compiler, connection, *, case_sensitive):
    lhs, lhs_params = lookup.process_lhs(compiler, connection)
    rhs, rhs_params = lookup.process_rhs(compiler, connection)
    pattern = _pattern_param(rhs_params)
    sql = _predicate(lhs, rhs, case_sensitive)
    return sql, lhs_params + (sqlite_pattern(pattern),)


def _pattern_param(params):
    if len(params) != 1 or not isinstance(params[0], str):
        raise InvalidPattern("glob lookup requires one string pattern")
    return params[0]


def _predicate(lhs, rhs, case_sensitive):
    match case_sensitive:
        case True:
            return f"{lhs} GLOB {rhs}"
        case False:
            return f"LOWER({lhs}) GLOB LOWER({rhs})"
    raise ValueError("case_sensitive must be a boolean")


CharField.register_lookup(Glob)
TextField.register_lookup(Glob)
CharField.register_lookup(IGlob)
TextField.register_lookup(IGlob)

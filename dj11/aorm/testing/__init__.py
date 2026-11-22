"""A fake async backend and the contract suite for `dj11.aorm`.

`contract.AsyncORMContract` holds the behavior every backend must show.
`tests.FakeDriverContractTests` runs it over `backend`, a Django backend
whose async driver (`driver`) wraps the standard library's sqlite3.
"""

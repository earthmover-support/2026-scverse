"""A transaction around a SpatialData write.

The hackathon report proposes this form: `with sdi.transaction(sdata):`. The report presents it
as a usability benefit of an Icechunk backend. This module implements that API at a size that is
easy to evaluate. It commits on a clean exit. On an exception, it discards the session. Thus a
half-written dataset never becomes a snapshot.

The discard is the necessary capability. A filesystem store cannot offer it. SpatialData's own
`write()` writes element by element and cannot undo a write. If it fails partway, the disk holds a
partial dataset. The next reader must detect that partial dataset. With this module, a failure
leaves the branch unchanged.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace


@contextmanager
def transaction(repo, branch: str = "main", message: str = "write"):
    """Yield a writable session and commit it if the block succeeds.

    ```python
    with transaction(repo, "main", "ingest xenium") as tx:
        sdata.write(tx.session.store)
    ```

    On an exception, the function does not commit. It drops the session. The branch stays
    unchanged. After a successful commit, `.snapshot` holds the snapshot id.
    """
    session = repo.writable_session(branch)
    # An uncommitted Icechunk session changes nothing. This function exists to expose that property.
    # An exception in the block never reaches the commit.
    holder = SimpleNamespace(session=session, snapshot=None)
    yield holder
    holder.snapshot = session.commit(message)

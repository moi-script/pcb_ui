"""Database access for the TraceWorks web app.

Two backends behind the same names, picked by TRACEWORKS_DB:

- `mongo` (default): a local MongoDB (mongodb://localhost:27017 by default;
  set MONGO_URL to point elsewhere). This is what `uvicorn server:app` and
  `npm run dev` use.
- `sqlite`: one file, for the Windows desktop app, which has no database
  server to talk to. TRACEWORKS_DATA_DIR says where it lives. See
  sqlite_store.py for the subset of pymongo it implements.

Either way it exposes three collections — users, machines, boards — plus a
GridFS-shaped `sources` bucket holding the source images of traced boards.
"""
import os

from pymongo import ASCENDING

BACKEND = os.environ.get("TRACEWORKS_DB", "mongo").lower()

if BACKEND == "sqlite":
    import sqlite_store

    _data_dir = os.environ.get("TRACEWORKS_DATA_DIR") or os.getcwd()
    os.makedirs(_data_dir, exist_ok=True)
    DB_NAME = os.path.join(_data_dir, "traceworks.db")
    _db = sqlite_store.Database(DB_NAME)

    users = _db.collection("users")
    machines = _db.collection("machines")
    boards = _db.collection("boards")
    sources = _db.files("sources")

    def ping():
        """Raise if the database is unreachable; return the server reply."""
        return _db.ping()

else:
    import gridfs
    from pymongo import MongoClient

    MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    DB_NAME = os.environ.get("MONGO_DB", "traceworks")

    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
    db = client[DB_NAME]

    users = db["users"]
    machines = db["machines"]
    boards = db["boards"]

    # Source images for traced boards. GridFS rather than a field on the
    # board: getting a trace right is iterative, so the original has to
    # survive in order to be re-traced, and a photo plus a few thousand
    # derived tracks would crowd Mongo's 16 MB document limit.
    sources = gridfs.GridFS(db, collection="sources")

    def ping():
        """Raise if the database is unreachable; return the server reply."""
        return client.admin.command("ping")


# Indexes (idempotent). One account per email, one remembered port per
# account — `machines` holds {user_email, last_port, last_baud} and nothing
# else: it is a convenience crumb, not an identity.
users.create_index([("email", ASCENDING)], unique=True)
machines.create_index([("user_email", ASCENDING)], unique=True)
boards.create_index([("user_email", ASCENDING)])

"""A file-backed stand-in for the slice of pymongo/GridFS that server.py uses.

The Windows desktop build has no MongoDB server to talk to, so db.py swaps
these in when TRACEWORKS_DB=sqlite. Every document is one row: its _id in a
column, the rest as MongoDB Extended JSON (bson.json_util), so ObjectIds and
datetimes survive the round trip exactly as they do through Mongo.

Only what the API calls is implemented — equality filters, $set updates, an
exclusion projection, a one-key sort. Anything else raises rather than quietly
doing something different from Mongo.
"""
import json
import sqlite3
import threading

from bson import ObjectId, json_util
from bson.json_util import JSONOptions
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

# Naive UTC datetimes back out, the same as pymongo's default client.
_JSON = JSONOptions(tz_aware=False)


def _dumps(doc: dict) -> str:
    return json_util.dumps(doc, json_options=json_util.RELAXED_JSON_OPTIONS)


def _loads(text: str) -> dict:
    return json_util.loads(text, json_options=_JSON)


def _key(value) -> str:
    """The _id column: an ObjectId's hex, or the JSON of anything else."""
    return str(value) if isinstance(value, ObjectId) else json.dumps(value)


class _Store:
    """One SQLite connection shared across FastAPI's worker threads."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()

    def execute(self, sql: str, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur.fetchall()


class InsertOneResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class Cursor:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    def sort(self, key: str, direction: int = 1):
        present = [d for d in self._docs if key in d]
        missing = [d for d in self._docs if key not in d]
        present.sort(key=lambda d: d[key], reverse=direction < 0)
        # Mongo orders a missing field before any value ascending.
        self._docs = missing + present if direction > 0 else present + missing
        return self

    def __iter__(self):
        return iter(self._docs)


class Collection:
    def __init__(self, store: _Store, name: str):
        self.store = store
        self.name = name
        store.execute(
            f'CREATE TABLE IF NOT EXISTS "{name}" '
            "(id TEXT PRIMARY KEY, doc TEXT NOT NULL)")

    # -------------------------------------------------------------- helpers
    def _where(self, flt: dict):
        clauses, params = [], []
        for field, value in (flt or {}).items():
            if field.startswith("$") or isinstance(value, dict):
                raise NotImplementedError(f"filter {field!r} is not supported")
            if field == "_id":
                clauses.append("id = ?")
                params.append(_key(value))
            else:
                clauses.append("json_extract(doc, ?) = ?")
                params += [f"$.{field}", value]
        sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        return sql, params

    def _rows(self, flt: dict, limit: int | None = None) -> list[dict]:
        where, params = self._where(flt)
        sql = f'SELECT doc FROM "{self.name}"{where}'
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [_loads(r[0]) for r in self.store.execute(sql, params)]

    def _write(self, doc: dict, replace: bool) -> None:
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        try:
            self.store.execute(
                f'{verb} INTO "{self.name}" (id, doc) VALUES (?, ?)',
                (_key(doc["_id"]), _dumps(doc)))
        except sqlite3.IntegrityError as exc:
            raise DuplicateKeyError(str(exc)) from exc

    # ----------------------------------------------------------------- API
    def create_index(self, keys, unique: bool = False):
        fields = [k for k, _ in keys]
        name = f"{self.name}_{'_'.join(fields)}"
        cols = ", ".join(f"json_extract(doc, '$.{f}')" for f in fields)
        kind = "UNIQUE INDEX" if unique else "INDEX"
        self.store.execute(
            f'CREATE {kind} IF NOT EXISTS "{name}" ON "{self.name}" ({cols})')
        return name

    def find_one(self, flt: dict | None = None):
        rows = self._rows(flt or {}, limit=1)
        return rows[0] if rows else None

    def find(self, flt: dict | None = None, projection: dict | None = None):
        docs = self._rows(flt or {})
        if projection:
            if any(v for k, v in projection.items() if k != "_id"):
                raise NotImplementedError("only exclusion projections")
            drop = [k for k, v in projection.items() if not v]
            for d in docs:
                for k in drop:
                    d.pop(k, None)
        return Cursor(docs)

    def insert_one(self, doc: dict) -> InsertOneResult:
        if "_id" not in doc:
            doc["_id"] = ObjectId()  # pymongo mutates the caller's dict too
        self._write(doc, replace=False)
        return InsertOneResult(doc["_id"])

    def find_one_and_update(self, flt: dict, update: dict,
                            return_document=ReturnDocument.BEFORE):
        if set(update) != {"$set"}:
            raise NotImplementedError("only $set updates are supported")
        with self.store.lock:
            before = self.find_one(flt)
            if before is None:
                return None
            after = {**before, **update["$set"]}
            self._write(after, replace=True)
        return after if return_document == ReturnDocument.AFTER else before

    def replace_one(self, flt: dict, replacement: dict, upsert: bool = False):
        with self.store.lock:
            current = self.find_one(flt)
            if current is None and not upsert:
                return
            doc = dict(replacement)
            doc["_id"] = current["_id"] if current else ObjectId()
            self._write(doc, replace=True)

    def delete_one(self, flt: dict):
        with self.store.lock:
            doc = self.find_one(flt)
            if doc is not None:
                self.store.execute(
                    f'DELETE FROM "{self.name}" WHERE id = ?',
                    (_key(doc["_id"]),))

    def delete_many(self, flt: dict):
        where, params = self._where(flt)
        self.store.execute(f'DELETE FROM "{self.name}"{where}', params)


class _File:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class FileStore:
    """GridFS's put / get / delete, with the bytes in a BLOB column."""

    def __init__(self, store: _Store, name: str):
        self.store = store
        self.name = name
        store.execute(
            f'CREATE TABLE IF NOT EXISTS "{name}" (id TEXT PRIMARY KEY, '
            "filename TEXT, content_type TEXT, data BLOB NOT NULL)")

    def put(self, data: bytes, filename: str | None = None,
            contentType: str | None = None, **_):
        oid = ObjectId()
        self.store.execute(
            f'INSERT INTO "{self.name}" VALUES (?, ?, ?, ?)',
            (str(oid), filename, contentType, data))
        return oid

    def get(self, file_id) -> _File:
        rows = self.store.execute(
            f'SELECT data FROM "{self.name}" WHERE id = ?', (str(file_id),))
        if not rows:
            raise FileNotFoundError(f"no file {file_id}")
        return _File(rows[0][0])

    def exists(self, file_id) -> bool:
        return bool(self.store.execute(
            f'SELECT 1 FROM "{self.name}" WHERE id = ?', (str(file_id),)))

    def delete(self, file_id) -> None:
        self.store.execute(
            f'DELETE FROM "{self.name}" WHERE id = ?', (str(file_id),))


class Database:
    def __init__(self, path: str):
        self.store = _Store(path)

    def collection(self, name: str) -> Collection:
        return Collection(self.store, name)

    def files(self, name: str) -> FileStore:
        return FileStore(self.store, name)

    def ping(self):
        self.store.execute("SELECT 1")
        return {"ok": 1.0}

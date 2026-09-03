"""MongoDB access for the TraceWorks web app.

Connects to a local MongoDB (mongodb://localhost:27017 by default) and exposes
three collections: users, devices, boards, plus a GridFS bucket holding the
source images of traced boards. Set MONGO_URL to point elsewhere.
"""
import os

import gridfs
from pymongo import ASCENDING, MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MONGO_DB", "traceworks")

client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
db = client[DB_NAME]

users = db["users"]
devices = db["devices"]
boards = db["boards"]

# Source images for traced boards. GridFS rather than a field on the board:
# getting a trace right is iterative, so the original has to survive in order
# to be re-traced, and a photo plus a few thousand derived tracks would crowd
# Mongo's 16 MB document limit.
sources = gridfs.GridFS(db, collection="sources")

# Indexes (idempotent). One account per email, one device per account.
users.create_index([("email", ASCENDING)], unique=True)
devices.create_index([("user_email", ASCENDING)], unique=True)
boards.create_index([("user_email", ASCENDING)])


def ping():
    """Raise if the database is unreachable; return the server reply."""
    return client.admin.command("ping")

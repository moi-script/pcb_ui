"""Boards saved before work zero moved to the top-left still plot.

Their G-code hangs ABOVE a bottom-left zero (Y 0 .. +height). The bed is now
0 .. -height below a top-left zero, so that file would be refused, or would
drive the pen up off the bed. The stored geometry is still good, so the
G-code is rebuilt from it the first time the board is opened or run.

These need a database, and skip cleanly without it.
"""
from __future__ import annotations

import re

import pytest
from bson import ObjectId

from tests.test_retrace import _png

EMAIL = "top-left-migration@example.com"
KICAD = "tests/single_layer.kicad_pcb"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import db
    import server
    try:
        db.ping()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"database unreachable: {e}")
    yield TestClient(server.app)
    for doc in db.boards.find({"user_email": EMAIL}):
        if doc.get("sourceFile"):
            try:
                db.sources.delete(doc["sourceFile"])
            except Exception:  # noqa: BLE001
                pass
    db.boards.delete_many({"user_email": EMAIL})


def _ys(gcode: str) -> list[float]:
    return [float(v) for ln in gcode.splitlines()
            for v in re.findall(r"Y(-?[\d.]+)", ln.split(";", 1)[0])]


def _make_legacy(board_id: str) -> None:
    """Rewrite a stored board's G-code the way the old generator made it."""
    import db
    doc = db.boards.find_one({"_id": ObjectId(board_id)})
    height = doc["height"]

    def lift(text: str) -> str:
        return re.sub(r"Y(-?[\d.]+)",
                      lambda m: f"Y{float(m.group(1)) + height:g}"
                      if not text.startswith("G0 X0 Y0") else m.group(0), text)

    fields = {"gcode": "\n".join(lift(l) for l in doc["gcode"].splitlines())}
    if doc.get("frameGcode"):
        fields["frameGcode"] = "\n".join(
            lift(l) for l in doc["frameGcode"].splitlines())
    db.boards.update_one({"_id": doc["_id"]}, {"$set": fields})
    assert max(_ys(fields["gcode"])) > 0


@pytest.mark.parametrize("kind", ["kicad", "image"])
def test_opening_a_legacy_board_rebuilds_its_gcode_top_left(client, kind):
    import db
    if kind == "kicad":
        with open(KICAD, "rb") as f:
            r = client.post("/route", files={"file": ("b.kicad_pcb", f.read())},
                            data={"email": EMAIL})
    else:
        r = client.post("/trace", files={"file": ("s.png", _png(), "image/png")},
                        data={"email": EMAIL, "size_mm": "40"})
    assert r.status_code == 200, r.text
    board_id = r.json()["id"]
    assert max(_ys(r.json()["gcode"])) == pytest.approx(0, abs=1e-6)

    _make_legacy(board_id)

    fresh = client.get(f"/board/{board_id}").json()
    ys = _ys(fresh["gcode"])
    assert max(ys) == pytest.approx(0, abs=1e-6)
    assert min(ys) == pytest.approx(-fresh["height"], abs=0.05)
    # ...and it was saved, so the preview and the plot agree from now on.
    stored = db.boards.find_one({"_id": ObjectId(board_id)})
    assert max(_ys(stored["gcode"])) == pytest.approx(0, abs=1e-6)
    if kind == "image":
        assert max(_ys(stored["frameGcode"])) == pytest.approx(0, abs=1e-6)

"""Re-tracing a stored board with different parameters.

Getting a trace right is iterative — threshold and size are guesses until you
see the result — so the source image is kept and re-traced in place rather
than re-uploaded.

These need MongoDB, and skip cleanly without it.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

EMAIL = "retrace-test@example.com"


def _png(width=6) -> bytes:
    img = Image.new("L", (200, 200), 255)
    d = ImageDraw.Draw(img)
    d.line((20, 60, 180, 60), fill=0, width=width)
    d.line((20, 140, 180, 140), fill=0, width=width)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    import db
    import server
    try:
        db.ping()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"MongoDB unreachable: {e}")
    c = TestClient(server.app)
    yield c
    for doc in db.boards.find({"user_email": EMAIL}):
        if doc.get("sourceFile"):
            try:
                db.sources.delete(doc["sourceFile"])
            except Exception:  # noqa: BLE001
                pass
    db.boards.delete_many({"user_email": EMAIL})


@pytest.fixture
def board(client):
    r = client.post("/trace", files={"file": ("s.png", _png(), "image/png")},
                    data={"email": EMAIL, "size_mm": "50"})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_traced_board_reports_a_reusable_source(board):
    assert board["hasSource"] is True


def test_retrace_changes_the_size_in_place(client, board):
    r = client.post(f"/board/{board['id']}/retrace",
                    json={"size_mm": 100, "mode": "centerline",
                          "preset": "line", "threshold": None, "invert": False})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["id"] == board["id"], "re-trace must not create a new board"
    assert out["width"] == pytest.approx(100, abs=1.0)
    assert board["width"] == pytest.approx(50, abs=1.0)


def test_retrace_updates_the_stored_params(client, board):
    r = client.post(f"/board/{board['id']}/retrace",
                    json={"size_mm": 70, "mode": "outline",
                          "preset": "line", "threshold": None, "invert": False})
    out = r.json()
    assert out["traceParams"]["mode"] == "outline"
    assert out["traceParams"]["size_mm"] == 70


def test_retrace_regenerates_the_gcode(client, board):
    before = board["gcodeLines"]
    r = client.post(f"/board/{board['id']}/retrace",
                    json={"size_mm": 50, "mode": "outline",
                          "preset": "line", "threshold": None, "invert": False})
    out = r.json()
    assert out["gcodeLines"] != before
    assert "G21" in out["gcode"]


def test_retrace_keeps_the_name_the_user_gave_it(client, board):
    client.patch(f"/board/{board['id']}", json={"name": "my drawing"})
    r = client.post(f"/board/{board['id']}/retrace",
                    json={"size_mm": 60, "mode": "centerline",
                          "preset": "line", "threshold": None, "invert": False})
    assert r.json()["name"] == "my drawing"


def test_retrace_rejects_bad_params(client, board):
    r = client.post(f"/board/{board['id']}/retrace",
                    json={"size_mm": 50, "mode": "nonsense",
                          "preset": "line", "threshold": None, "invert": False})
    assert r.status_code == 400


def test_an_untraceable_image_is_a_readable_400(client):
    """A shape with no centreline must explain itself, not 500.

    A filled disc thins to a single pixel - its medial axis is its centre
    point - so there is no path to walk and nothing to plot.
    """
    img = Image.new("L", (200, 200), 255)
    ImageDraw.Draw(img).ellipse((60, 60, 140, 140), fill=0)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    r = client.post("/trace",
                    files={"file": ("disc.png", buf.getvalue(), "image/png")},
                    data={"email": EMAIL, "size_mm": "50"})
    assert r.status_code == 400
    detail = r.json()["detail"].lower()
    assert "threshold" in detail or "invert" in detail or "minimum" in detail


def test_retrace_of_a_routed_board_is_refused(client):
    """A KiCad board has no source image, so there is nothing to re-trace."""
    with open("labExam.kicad_pcb", "rb") as f:
        r = client.post("/route",
                        files={"file": ("labExam.kicad_pcb", f, "text/plain")},
                        data={"email": EMAIL})
    kicad = r.json()
    assert kicad.get("hasSource") is not True

    r = client.post(f"/board/{kicad['id']}/retrace",
                    json={"size_mm": 50, "mode": "centerline",
                          "preset": "line", "threshold": None, "invert": False})
    assert r.status_code == 400


def test_retrace_of_an_unknown_board_is_404(client):
    r = client.post("/board/000000000000000000000000/retrace",
                    json={"size_mm": 50, "mode": "centerline",
                          "preset": "line", "threshold": None, "invert": False})
    assert r.status_code == 404


def test_deleting_a_board_removes_its_source(client):
    import db
    r = client.post("/trace", files={"file": ("s.png", _png(), "image/png")},
                    data={"email": EMAIL, "size_mm": "50"})
    b = r.json()
    doc = db.boards.find_one({"_id": __import__("bson").ObjectId(b["id"])})
    fid = doc["sourceFile"]
    assert db.sources.exists(fid)

    client.delete(f"/board/{b['id']}")
    assert not db.sources.exists(fid), "source image left orphaned in GridFS"


def test_list_view_of_a_traced_board_is_lean(client, board):
    """The grid draws postage stamps; it must not be sent full geometry."""
    rows = client.get(f"/boards/{EMAIL}").json()
    row = next(r for r in rows if r["id"] == board["id"])
    assert "tracks" not in row, "derived tracks must stay out of the list"
    assert row["strokes"], "the thumbnail still needs something to draw"
    assert sum(len(s) for s in row["strokes"]) <= 1100

    full = client.get(f"/board/{board['id']}").json()
    assert len(full["strokes"]) >= len(row["strokes"])
    assert "tracks" not in full, "traced boards keep strokes only"


def test_list_view_of_a_kicad_board_still_carries_tracks(client):
    with open("labExam.kicad_pcb", "rb") as f:
        b = client.post("/route",
                        files={"file": ("labExam.kicad_pcb", f, "text/plain")},
                        data={"email": EMAIL}).json()
    rows = client.get(f"/boards/{EMAIL}").json()
    row = next(r for r in rows if r["id"] == b["id"])
    assert len(row["tracks"]) == 352

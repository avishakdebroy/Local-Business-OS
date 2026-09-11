"""The network boundary, and what a paired phone can and cannot do."""

import io

from lbos.db.bootstrap import open_db
from lbos.ledger import repositories as repo
from lbos.phone import pairing
from tests.test_phone import EAN, barcode_png


def location(response) -> str:
    return response.headers.get("location", "")


def mint_code(settings) -> str:
    conn = open_db(settings)
    try:
        return pairing.new_code(conn)
    finally:
        conn.close()


# --- The boundary -----------------------------------------------------------


def test_another_machine_is_refused_when_the_phone_link_is_off(settings):
    """Default posture: this program is only available on its own computer."""
    from fastapi.testclient import TestClient

    from lbos.main import create_app

    with TestClient(create_app(settings), follow_redirects=False,
                    client=("192.168.1.77", 5000)) as remote:
        response = remote.get("/")
        assert response.status_code == 403
        assert "only available on the computer" in response.text
        assert remote.get("/ledger").status_code == 403
        assert remote.get("/api/summary").status_code == 403


def test_a_phone_is_confined_to_the_phone_pages(phone_client):
    """Turning the link on must not expose the books to the whole Wi-Fi."""
    for path in ("/", "/ledger", "/khata", "/status", "/api/summary"):
        response = phone_client.get(path)
        assert response.status_code == 303, path
        assert location(response) == "/phone"


def test_the_laptop_keeps_full_access(client):
    assert client.get("/").status_code == 200
    assert client.get("/khata").status_code == 200
    assert client.get("/link").status_code == 200


# --- Pairing ----------------------------------------------------------------


def test_an_unpaired_phone_is_asked_to_pair(phone_client):
    response = phone_client.get("/phone")
    assert response.status_code == 401
    assert "Link this phone" in response.text


def test_a_wrong_code_explains_itself(phone_client):
    response = phone_client.get("/phone/pair?code=000000")
    assert response.status_code == 400
    assert "expired" in response.text


def test_pairing_with_a_good_code_opens_the_phone_pages(phone_client, settings):
    response = phone_client.get(f"/phone/pair?code={mint_code(settings)}")
    assert response.status_code == 303
    assert location(response) == "/phone"
    assert pairing.COOKIE_NAME in response.cookies

    phone_client.cookies.update(response.cookies)
    home = phone_client.get("/phone")
    assert home.status_code == 200
    assert "Scan a product" in home.text


def _paired(phone_client, settings):
    response = phone_client.get(f"/phone/pair?code={mint_code(settings)}")
    phone_client.cookies.update(response.cookies)
    return phone_client


# --- What the phone can do --------------------------------------------------


def test_a_phone_photo_of_a_barcode_is_read(phone_client, settings):
    phone = _paired(phone_client, settings)
    response = phone.post(
        "/phone/scan",
        files={"photo": ("shot.jpg", io.BytesIO(barcode_png(distort=True)), "image/jpeg")},
    )
    assert response.status_code == 200
    assert EAN in response.text
    assert "not in your list yet" in response.text


def test_an_unreadable_photo_says_so_kindly(phone_client, settings):
    phone = _paired(phone_client, settings)
    response = phone.post(
        "/phone/scan",
        files={"photo": ("blur.jpg", io.BytesIO(b"not an image"), "image/jpeg")},
    )
    assert response.status_code == 200
    assert "No barcode could be read" in response.text


def test_a_new_product_can_be_registered_from_the_phone(phone_client, settings):
    phone = _paired(phone_client, settings)
    response = phone.post("/phone/scan/save", data={
        "code": EAN, "name": "Meril Lip Gel", "brand": "Square Toiletries", "variant": "15 ml",
    })
    assert response.status_code == 303

    conn = open_db(settings)
    try:
        row = conn.execute("SELECT * FROM items WHERE barcode = ?", (EAN,)).fetchone()
        assert row["name"] == "Meril Lip Gel"
        assert row["brand"] == "Square Toiletries"
    finally:
        conn.close()


def test_a_known_barcode_shows_the_product(phone_client, settings):
    phone = _paired(phone_client, settings)
    phone.post("/phone/scan/save", data={"code": EAN, "name": "Meril Lip Gel", "brand": "", "variant": ""})
    response = phone.post(
        "/phone/scan", files={"photo": ("shot.jpg", io.BytesIO(barcode_png()), "image/jpeg")}
    )
    assert "Meril Lip Gel" in response.text
    assert "not in your list yet" not in response.text


def test_a_photographed_page_lands_in_the_review_queue(phone_client, settings):
    phone = _paired(phone_client, settings)
    note = b"Sold 3 Meril cream 450 taka cash"
    response = phone.post(
        "/phone/note",
        files={"photo": ("page.txt", io.BytesIO(note), "text/plain")},
        data={"hint": "sale"},
    )
    assert response.status_code == 303

    conn = open_db(settings)
    try:
        assert repo.document_status_counts(conn)["pending_review"] >= 0
        assert repo.recent_documents(conn, limit=1)[0]["source_kind"] == "file"
    finally:
        conn.close()


def test_the_phone_cannot_reach_writing_screens(phone_client, settings):
    """Read-only by design: correcting the books happens on the laptop."""
    phone = _paired(phone_client, settings)
    for path in ("/khata", "/ledger", "/status", "/review"):
        assert location(phone.get(path)) == "/phone"


def test_a_revoked_phone_loses_access(phone_client, settings):
    phone = _paired(phone_client, settings)
    assert phone.get("/phone").status_code == 200

    conn = open_db(settings)
    try:
        pairing.revoke_all(conn)
    finally:
        conn.close()

    assert phone.get("/phone").status_code == 401

"""Phone pairing, the remote-client guard, and reading a barcode from a photo."""

import io

import numpy as np
import pytest
import zxingcpp
from PIL import Image, ImageFilter

from lbos.capture.barcode import check_digit_ok, decode, first_product_code
from lbos.domain.errors import ValidationError
from lbos.phone import network, pairing

EAN = "8941100510018"


def barcode_png(code: str = EAN, distort: bool = False) -> bytes:
    arr = np.array(
        zxingcpp.write_barcode_to_image(
            zxingcpp.create_barcode(code, zxingcpp.BarcodeFormat.EAN13),
            scale=4, add_quiet_zones=True,
        )
    )
    image = Image.fromarray(arr).convert("L")
    if distort:
        pad = Image.new("L", (image.width + 120, image.height + 160), 245)
        pad.paste(image, (60, 80))
        image = pad.rotate(-5, expand=True, fillcolor=245).filter(ImageFilter.GaussianBlur(1.2))
        rng = np.random.default_rng(11)
        data = np.array(image).astype(float)
        image = Image.fromarray(
            np.clip(data * rng.normal(1, 0.07, data.shape) - 20, 0, 255).astype(np.uint8)
        )
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=62)
    return buffer.getvalue()


# --- Barcode reading --------------------------------------------------------


def test_a_clean_barcode_is_read():
    assert first_product_code(barcode_png()).text == EAN


def test_a_blurred_rotated_phone_photo_is_read():
    assert first_product_code(barcode_png(distort=True)).text == EAN


def test_a_poster_qr_does_not_outrank_the_product():
    product = np.array(zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode(EAN, zxingcpp.BarcodeFormat.EAN13), scale=4, add_quiet_zones=True))
    poster = np.array(zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode("https://example.com", zxingcpp.BarcodeFormat.QRCode),
        scale=4, add_quiet_zones=True))
    canvas = Image.new("L", (max(product.shape[1], poster.shape[1]) + 40,
                             product.shape[0] + poster.shape[0] + 60), 255)
    canvas.paste(Image.fromarray(poster).convert("L"), (20, 10))
    canvas.paste(Image.fromarray(product).convert("L"), (20, poster.shape[0] + 40))
    buffer = io.BytesIO()
    canvas.save(buffer, "PNG")

    assert len(decode(buffer.getvalue())) == 2
    assert first_product_code(buffer.getvalue()).text == EAN


@pytest.mark.parametrize("payload", [b"", b"not an image", b"\x89PNG broken"])
def test_unreadable_input_never_raises(payload):
    assert first_product_code(payload) is None


def test_check_digits_are_validated():
    assert check_digit_ok(EAN)
    assert not check_digit_ok("8941100510017")
    assert not check_digit_ok("abc")


# --- Pairing ----------------------------------------------------------------


def test_a_code_can_be_redeemed_once(conn):
    code = pairing.new_code(conn)
    token = pairing.redeem(conn, code)
    assert pairing.device_for(conn, token) is not None

    with pytest.raises(ValidationError, match="expired"):
        pairing.redeem(conn, code)


def test_a_wrong_code_is_refused(conn):
    pairing.new_code(conn)
    with pytest.raises(ValidationError):
        pairing.redeem(conn, "000000")


def test_the_token_is_not_stored_in_the_clear(conn):
    token = pairing.redeem(conn, pairing.new_code(conn))
    stored = conn.execute("SELECT token_hash FROM paired_devices").fetchone()["token_hash"]
    assert token not in stored
    assert len(stored) == 64  # sha256 hex


def test_an_unknown_token_matches_nothing(conn):
    pairing.redeem(conn, pairing.new_code(conn))
    assert pairing.device_for(conn, "not-a-real-token") is None
    assert pairing.device_for(conn, None) is None


def test_revoking_a_phone_ends_its_access(conn):
    token = pairing.redeem(conn, pairing.new_code(conn))
    device = pairing.device_for(conn, token)
    pairing.revoke(conn, device["id"])
    assert pairing.device_for(conn, token) is None
    assert pairing.devices(conn) == []


def test_revoke_all_ends_every_session(conn):
    tokens = [pairing.redeem(conn, pairing.new_code(conn)) for _ in range(3)]
    assert pairing.revoke_all(conn) == 3
    assert all(pairing.device_for(conn, t) is None for t in tokens)


def test_loopback_detection():
    assert network.is_loopback("127.0.0.1")
    assert network.is_loopback("::1")
    assert not network.is_loopback("192.168.1.5")
    assert not network.is_loopback(None)

import time

import pytest

from ooat_core.pii import higher_class, raised_class, scan


@pytest.mark.parametrize("text, kind", [
    ("Pošlete to na jan.novak@example.cz, děkuji.", "email"),
    ("Volejte +420 777 123 456 po 16. hodině.", "phone"),
    ("Mobil 603123456.", "phone"),
    ("Tel.: 777 123 456", "phone"),
    ("Účet CZ65 0800 0000 1920 0014 5399 KB, splatnost 14 dní.", "iban"),
    ("Účet CZ65 0800 0000 1920 0014 5399 u ČS.", "iban"),
    ("Karta 4111 1111 1111 1111, platnost 12/28.", "card"),
    ("Rodné číslo 780123/0008.", "birth_number"),
    ("Narozen 1950, RČ 505101/123.", "birth_number"),
    ("RČ 015203/0000 podle staršího pravidla.", "birth_number"),
])
def test_personal_data_with_a_checkable_form_is_found(text, kind):
    assert kind in scan(text)


@pytest.mark.parametrize("text", [
    "Obrat 1 200 000 Kč za rok 2025, marže 12 %.",
    "Rozpočet projektu je 650 000 000 Kč.",
    "Objednávka 712345678 byla odeslána.",
    "Objednávka 123456789 ze dne 12. 3. 2026.",
    "Účet CZ65 0800 0000 1920 0014 5398 (překlep v kontrolní číslici).",
    "Číslo 4111 1111 1111 1112 neprojde Luhnem.",
    "Testovací karta 0000 0000 0000 0000.",
    "Kód 785123/0003 nemá platnou kontrolu.",
    "Kód 781323/0008 má měsíc 13.",
    "Napiš shrnutí smlouvy pro jednatele, max. 1 strana.",
    "Write to us at support (at) example dot com.",
])
def test_ordinary_business_text_is_not_flagged(text):
    assert scan(text) == frozenset()


def test_the_class_is_raised_to_personal_and_never_lowered():
    text = "Kontakt: jan.novak@example.cz"
    assert raised_class("internal", text) == "personal"
    assert raised_class("public", text) == "personal"
    assert raised_class("special_category", text) == "special_category"
    assert raised_class("internal", "Bez osobních údajů.") == "internal"


def test_higher_class_orders_by_sensitivity():
    assert higher_class("internal", "personal") == "personal"
    assert higher_class("client_confidential", "public") == "client_confidential"


@pytest.mark.parametrize("filler", ["x", "1", "a.", "a@", "+4"])
def test_a_long_attachment_is_scanned_in_linear_time(filler):
    text = filler * 100_000 + " jan.novak@example.cz"
    started = time.monotonic()
    assert "email" in scan(text)
    assert time.monotonic() - started < 3.0  # about 0.2 s; the quadratic pattern took minutes

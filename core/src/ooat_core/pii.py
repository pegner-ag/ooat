"""Local pre-scan for personal data, before anything leaves the machine (design 04 §4, ADR 0011).

A hit raises a request's data class to `personal`; it never lowers one. The scan finds only what has a checkable
form: e-mail addresses, phone numbers, IBANs (mod 97), payment card numbers (Luhn) and Czech/Slovak birth numbers
written with a slash (date plus mod 11). Names and free-text health details are not found: that residual risk is
covered by the class the operator declares. Known gaps of the forms it does check: IBANs written in lowercase,
phone numbers of countries other than CZ/SK, and a card number written without separators and without a known
issuer prefix. A `00420…` number written with spaces may be taken for a card; it raises the class either way.
"""

import re

PERSONAL = "personal"
ORDER = ("public", "internal", "client_confidential", "personal", "special_category")

# Bounded repeats and a start-of-token lookbehind keep every pattern linear on long runs of letters or digits:
# an unbounded local part made a 100k-character attachment take minutes.
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,8}"
                    r"\.[A-Za-z]{2,24}")
# +420/+421 numbers anywhere; nine digits without the prefix only right after a phone word, because amounts
# ("650 000 000 Kč") and order numbers have the same shape.
_PHONE = re.compile(r"(?<![\d+])\+42[01][ ]?\d{3}[ ]?\d{3}[ ]?\d{3}(?!\d)"
                    r"|(?i:\b(?:tel|telefon|mobil|mob|phone|volejte|call)\b)\.?:?[ ]{0,3}\d{3}[ ]?\d{3}[ ]?\d{3}(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
_CARD = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_BIRTH_NUMBER = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})/(\d{3,4})(?!\d)")


# IBAN length and whether the account part is digits only, for the countries an operator here meets most.
# Checking every prefix length instead flagged one random uppercase reference code in seven.
_IBAN_FORMAT = {"CZ": (24, True), "SK": (24, True), "DE": (22, True), "AT": (20, True), "PL": (28, True),
                "HU": (28, True), "ES": (24, True), "BE": (16, True), "GB": (22, False), "FR": (27, False),
                "IT": (27, False), "NL": (18, False), "CH": (21, False)}


def _mod97_ok(candidate: str) -> bool:
    digits = "".join(str(int(char, 36)) for char in candidate[4:] + candidate[:4])
    return int(digits) % 97 == 1


def _iban_ok(text: str) -> bool:
    """The pattern is greedy, so a following uppercase word ("... 5399 KB") is part of the match. A known country
    is checked at its own length and format; another only where a word ends inside the match."""
    compact = text.replace(" ", "")
    known = _IBAN_FORMAT.get(compact[:2])
    if known is not None:
        length, numeric = known
        candidate = compact[:length]
        return len(candidate) == length and (not numeric or candidate[4:].isdigit()) and _mod97_ok(candidate)
    ends, total = [], 0
    for word in text.split(" "):
        total += len(word)
        ends.append(total)
    return any(15 <= end <= 34 and _mod97_ok(compact[:end]) for end in ends)


# Issuer prefixes, broad on purpose (Visa, Mastercard and Maestro, Mir, Amex, Diners, JCB, Discover, UnionPay,
# RuPay). About one digit run in ten passes Luhn, so a run written without separators counts only with such a
# prefix: timestamps (starting with 1) and order numbers starting with 0, 1, 7 or 9 do not.
_ISSUER = re.compile(r"^(?:4|5[0-8]|2[2-7]|3|6|8[12])")


def _card_ok(text: str) -> bool:
    separated = " " in text or "-" in text
    return _luhn_ok(text) and (separated or bool(_ISSUER.match(text)))


def _luhn_ok(text: str) -> bool:
    digits = [int(char) for char in text if char.isdigit()]
    if len(set(digits)) == 1:  # 0000 0000 ... is a placeholder, not a card
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            digit -= 9 if digit > 9 else 0
        total += digit
    return total % 10 == 0


def _birth_number_ok(match: re.Match) -> bool:
    year, month, day = (int(match.group(i)) for i in (1, 2, 3))
    suffix = match.group(4)
    month = month - 50 if month > 50 else month  # women
    month = month - 20 if month > 20 else month  # extended series since 2004
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    if len(suffix) == 3:  # born before 1954: no check digit
        return year < 54
    digits = f"{match.group(1)}{match.group(2)}{match.group(3)}{suffix}"  # a string: 00.. years keep their zeros
    return int(digits) % 11 == 0 or (int(digits[:9]) % 11 == 10 and digits[9] == "0")


def scan(text: str) -> frozenset[str]:
    """The kinds of personal data found in the text: email, phone, iban, card, birth_number."""
    found = set()
    if _EMAIL.search(text):
        found.add("email")
    if _PHONE.search(text):
        found.add("phone")
    if any(_iban_ok(m.group(0)) for m in _IBAN.finditer(text)):
        found.add("iban")
    if any(_card_ok(m.group(0)) for m in _CARD.finditer(text)):
        found.add("card")
    if any(_birth_number_ok(m) for m in _BIRTH_NUMBER.finditer(text)):
        found.add("birth_number")
    return frozenset(found)


def raised_class(declared: str, text: str) -> str:
    """The declared class, raised to `personal` when the scan finds personal data; never lowered."""
    if ORDER.index(declared) < ORDER.index(PERSONAL) and scan(text):
        return PERSONAL
    return declared


def higher_class(first: str, second: str) -> str:
    return first if ORDER.index(first) >= ORDER.index(second) else second

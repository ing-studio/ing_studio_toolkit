"""Old Armenian fonts (ARMSCII-8): the drawing stores Latin-1 characters that such a font draws as Armenian letters.

Opened anywhere else, 'Շենք' (building) shows as 'Þ»Ýù'. The code points 0xA0-0xFF are mapped back to Unicode
Armenian. A string is converted only when it looks like ARMSCII-8 Armenian: several letters from the Armenian range
in a row (French or German words have single accented letters between plain ones).
"""
import re

_TABLE = {0xA0: " ", 0xA2: "և", 0xA3: "։", 0xA4: ")", 0xA5: "(", 0xA6: "»", 0xA7: "«",
          0xA8: "—", 0xA9: ".", 0xAA: "՝", 0xAB: ",", 0xAC: "-", 0xAD: "֊", 0xAE: "…",
          0xAF: "՜", 0xB0: "՛", 0xB1: "՞", 0xFE: "՚"}
for _k in range(38):
    _TABLE[0xB2 + 2 * _k] = chr(0x531 + _k)  # capital letters
    _TABLE[0xB3 + 2 * _k] = chr(0x561 + _k)  # small letters
_RUN = re.compile("[²-ý]{2,}")


def looks_armscii(text):
    """Several Armenian-range letters in a row, and most non-ASCII characters in that range."""
    if not text or text.isascii():
        return False
    high = [c for c in text if ord(c) > 127]
    in_range = sum(1 for c in high if 0xA0 <= ord(c) <= 0xFF)
    runs = sum(len(m.group(0)) for m in _RUN.finditer(text))
    return in_range == len(high) and runs >= 3 and runs >= 0.6 * len(high)


def decode(text):
    return "".join(_TABLE.get(ord(c), c) for c in text)


def maybe_decode(text, force=False):
    """(text, converted?)"""
    if force or looks_armscii(text):
        return decode(text), True
    return text, False

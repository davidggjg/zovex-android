"""פענוח file_id של ה-Bot API חזרה למיקום MTProto.

למה זה כאן: שרת ה-Bot API המקומי מוריד מטלגרם בחיבור סדרתי אחד. על
מכונה שמושכת 80MB/s מהאינטרנט הוא נתן 1.2MB/s — 87 מגה בדקה ורבע.
הצינור המקביל שלנו כבר יודע למשוך את אותו קובץ בעשרות בקשות במקביל,
וכל מה שחסר לו הוא המיקום.

ו-file_id הוא בדיוק המיקום הזה, ארוז: הוא מכיל dc_id, מזהה המסמך,
access_hash ו-file_reference. access_hash של מסמך אינו תלוי חשבון
(להבדיל מזה של צ'אט), ולכן הלקוח שלנו יכול להשתמש בו כמו שהוא.

המבנה הוא זה של TDLib: base64url, פריסת רצפי אפסים, ואז שדות בסדר
קבוע כשבייט אחרון הוא מספר גרסה. פענוח שגוי לא מסוכן — הקורא מוודא
מול טלגרם לפני שהוא סומך עליו, ונופל חזרה למסלול האיטי.
"""
from __future__ import annotations

import base64
import struct
from dataclasses import dataclass

# דגלים שנצרבים לתוך שדה הסוג
WEB_LOCATION = 1 << 24
FILE_REFERENCE = 1 << 25

# סוגים שמיוצגים כמסמך, ורק הם מעניינים אותנו כאן
DOCUMENT_TYPES = {
    3,   # הודעה קולית
    4,   # וידאו
    5,   # מסמך
    8,   # מדבקה
    9,   # שמע
    10,  # אנימציה
    13,  # הודעת וידאו
    17,  # מסמך כקובץ
}


@dataclass(frozen=True)
class Located:
    dc_id: int
    id: int
    access_hash: int
    file_reference: bytes
    file_type: int


def _unpad(text: str) -> bytes:
    text = text.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(text + "=" * (-len(text) % 4))


def rle_decode(raw: bytes) -> bytes:
    """פורס רצפי אפסים: בייט 0 ואחריו מונה."""
    out = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        index += 1
        if byte:
            out.append(byte)
            continue
        if index >= len(raw):
            raise ValueError("רצף אפסים נקטע בסוף")
        out.extend(b"\x00" * raw[index])
        index += 1
    return bytes(out)


def rle_encode(raw: bytes) -> bytes:
    """ההפך מ-rle_decode. קיים כדי שאפשר יהיה לבדוק את הפענוח."""
    out = bytearray()
    run = 0
    for byte in raw:
        if byte == 0:
            run += 1
            continue
        while run:
            out += bytes((0, min(run, 255)))
            run -= min(run, 255)
        out.append(byte)
    while run:
        out += bytes((0, min(run, 255)))
        run -= min(run, 255)
    return bytes(out)


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.at = data, 0

    def take(self, count: int) -> bytes:
        if self.at + count > len(self.data):
            raise ValueError("file_id קצר מהצפוי")
        chunk = self.data[self.at:self.at + count]
        self.at += count
        return chunk

    def int32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def int64(self) -> int:
        return struct.unpack("<q", self.take(8))[0]

    def tl_bytes(self) -> bytes:
        first = self.take(1)[0]
        if first <= 253:
            value = self.take(first)
            padding = -(first + 1) % 4
        else:
            length = struct.unpack("<i", self.take(3) + b"\x00")[0]
            value = self.take(length)
            padding = -length % 4
        self.take(padding)
        return value


def decode(file_id: str) -> Located:
    """מפענח file_id של מסמך. זורק ValueError על כל דבר שאינו כזה."""
    raw = rle_decode(_unpad(file_id))
    if len(raw) < 12:
        raise ValueError("file_id קצר מדי")
    version = raw[-1]
    body = raw[:-2] if version >= 4 else raw[:-1]

    reader = _Reader(body)
    tagged = reader.int32()
    dc_id = reader.int32()
    file_type = tagged & ~(WEB_LOCATION | FILE_REFERENCE)

    if tagged & WEB_LOCATION:
        raise ValueError("קובץ רשת — אין לו מיקום MTProto")
    if file_type not in DOCUMENT_TYPES:
        raise ValueError(f"סוג {file_type} אינו מסמך")
    if not 1 <= dc_id <= 10:
        raise ValueError(f"dc_id לא סביר: {dc_id}")

    reference = reader.tl_bytes() if tagged & FILE_REFERENCE else b""
    return Located(dc_id=dc_id, id=reader.int64(),
                   access_hash=reader.int64(),
                   file_reference=reference, file_type=file_type)


def encode(found: Located, version: int = 4, subversion: int = 32) -> str:
    """בונה file_id מהשדות. משמש את הבדיקות בלבד."""
    tagged = found.file_type | (FILE_REFERENCE if found.file_reference else 0)
    body = struct.pack("<ii", tagged, found.dc_id)
    if found.file_reference:
        blob = found.file_reference
        body += bytes((len(blob),)) + blob + b"\x00" * (-(len(blob) + 1) % 4)
    body += struct.pack("<qq", found.id, found.access_hash)
    body += bytes((subversion, version))
    packed = base64.b64encode(rle_encode(body)).decode()
    return packed.replace("+", "-").replace("/", "_").rstrip("=")

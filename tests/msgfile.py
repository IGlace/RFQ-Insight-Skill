"""Build a real Outlook .msg for the tests - no binary fixture is committed.

The file is written with extract-msg's own `OleWriter`, the same library that
reads it back, so the fixture can never drift from what the reader expects.
Only the streams the reader needs are written: the root property stream and
its string streams, one recipient, one storage per attachment and the empty
named-property storage.
"""

import struct

from extract_msg.ole_writer import OleWriter

# 2026-10-20 09:00:00 UTC as a Windows FILETIME (100 ns ticks since 1601).
# Fixed, so a test never depends on the clock.
SUBMIT_FILETIME = (1_792_486_800 + 11_644_473_600) * 10_000_000

_ROOT_HEADER = b"\0" * 8 + struct.pack("<IIII", 1, 1, 1, 1) + b"\0" * 8   # 32 bytes
_SUB_HEADER = b"\0" * 8                                                    # recipient / attachment


def _ustr(text):
    return text.encode("utf-16-le")


def _props(entries, header):
    out = bytearray(header)
    for tag, value in entries:
        out += struct.pack("<I", tag) + struct.pack("<I", 0x6) + value   # readable | writable
    return bytes(out)


def _str(tag, text):
    return tag, struct.pack("<II", len(_ustr(text)) + 2, 0)


def _long(tag, number):
    return tag, struct.pack("<II", number, 0)


def _add_message(w, prefix, *, subject, sender, to, body, html, attachments,
                 codepage=None, broken=()):
    """Write one message's streams under `prefix` (a list of storage names)."""
    def at(*name):
        return [*prefix, *name] if prefix or len(name) > 1 else name[0]

    entries = [_str(0x0037001F, subject), _str(0x1000001F, body),
               _str(0x0C1A001F, sender[0]), _str(0x5D01001F, sender[1]),
               _str(0x0E04001F, to[1]), _str(0x0E03001F, ""),
               _str(0x001A001F, "IPM.Note"),
               (0x00390040, struct.pack("<Q", SUBMIT_FILETIME))]
    html_bytes = html.encode("utf-8") if isinstance(html, str) else html
    if html is not None:
        entries.append((0x10130102, struct.pack("<II", len(html_bytes), 0)))
    if codepage is not None:
        entries.append(_long(0x3FDE0003, codepage))     # PR_INTERNET_CPID
    # An embedded message has no trailing 8 reserved bytes (24-byte header) and
    # no named-property storage of its own: the top-level message owns both.
    header = _ROOT_HEADER if not prefix else _ROOT_HEADER[:24]
    w.addEntry(at("__properties_version1.0"), _props(entries, header))
    w.addEntry(at("__substg1.0_0037001F"), _ustr(subject))
    w.addEntry(at("__substg1.0_1000001F"), _ustr(body))
    w.addEntry(at("__substg1.0_0C1A001F"), _ustr(sender[0]))
    w.addEntry(at("__substg1.0_5D01001F"), _ustr(sender[1]))
    w.addEntry(at("__substg1.0_0E04001F"), _ustr(to[1]))
    w.addEntry(at("__substg1.0_0E03001F"), _ustr(""))
    w.addEntry(at("__substg1.0_001A001F"), _ustr("IPM.Note"))
    if html is not None:
        w.addEntry(at("__substg1.0_10130102"), html_bytes)

    recip = [*prefix, "__recip_version1.0_#00000000"]
    w.addEntry(recip, storage=True)
    rentries = [_str(0x3001001F, to[0]), _str(0x3003001F, to[1]),
                _long(0x0C150003, 1), _long(0x30000003, 0)]
    w.addEntry([*recip, "__properties_version1.0"], _props(rentries, _SUB_HEADER))
    w.addEntry([*recip, "__substg1.0_3001001F"], _ustr(to[0]))
    w.addEntry([*recip, "__substg1.0_3003001F"], _ustr(to[1]))

    for n, item in enumerate(attachments):
        name, data = item[0], item[1]
        cid = item[2] if len(item) > 2 else ""
        att = [*prefix, f"__attach_version1.0_#{n:08d}"]
        w.addEntry(att, storage=True)
        embedded = isinstance(data, dict)
        aentries = [_str(0x3704001F, name), _str(0x3707001F, name),
                    _long(0x37050003, 5 if embedded else 1), _long(0x0E210003, n)]
        if embedded:
            aentries.append((0x3701000D, struct.pack("<II", 0xFFFFFFFF, 0)))
        else:
            aentries.append((0x37010102, struct.pack("<II", len(data), 0)))
        if cid:
            aentries.append(_str(0x3712001F, cid))
        w.addEntry([*att, "__properties_version1.0"], _props(aentries, _SUB_HEADER))
        w.addEntry([*att, "__substg1.0_3704001F"], _ustr(name))
        w.addEntry([*att, "__substg1.0_3707001F"], _ustr(name))
        if cid:
            w.addEntry([*att, "__substg1.0_3712001F"], _ustr(cid))
        if embedded:
            inner = [*att, "__substg1.0_3701000D"]
            w.addEntry(inner, storage=True)
            _add_message(w, inner, subject=data["subject"], sender=data["sender"],
                         to=data["to"], body=data["body"], html=data.get("html"),
                         attachments=list(data.get("attachments", ())))
        else:
            w.addEntry([*att, "__substg1.0_37010102"], data)

    for k, name in enumerate(broken, len(attachments)):
        # An attachment that claims to be an embedded message but carries no
        # message storage: extract-msg cannot load it.
        att = [*prefix, f"__attach_version1.0_#{k:08d}"]
        w.addEntry(att, storage=True)
        aentries = [_str(0x3704001F, name), _long(0x37050003, 5), _long(0x0E210003, k),
                    (0x3701000D, struct.pack("<II", 0xFFFFFFFF, 0))]
        w.addEntry([*att, "__properties_version1.0"], _props(aentries, _SUB_HEADER))
        w.addEntry([*att, "__substg1.0_3704001F"], _ustr(name))

    if not prefix:
        w.addEntry("__nameid_version1.0", storage=True)
        for stream in ("__substg1.0_00020102", "__substg1.0_00030102", "__substg1.0_00040102"):
            w.addEntry(["__nameid_version1.0", stream], b"")


def build_msg(path, *, subject, sender, to, body, attachments=(), html=None,
              codepage=None, broken=()):
    """Write a .msg at `path` and return `path`.

    `sender` and `to` are (display name, address). `attachments` are
    (file name, bytes) pairs; a third item is the content id of an inline
    image, and a dict in place of the bytes (the keyword arguments of
    build_msg) embeds that message as a nested one. `html` adds an HTML body
    (bytes are written as given), `codepage` its PR_INTERNET_CPID, and
    `broken` names attachments extract-msg cannot load.
    """
    w = OleWriter()
    _add_message(w, [], subject=subject, sender=sender, to=to, body=body,
                 html=html, attachments=list(attachments), codepage=codepage,
                 broken=tuple(broken))
    w.write(path)
    return path

# SPDX-License-Identifier: GPL-3.0-or-later
"""Small dependency-free ISO 10303-21 literal and entity writer."""
import uuid

def ifc_guid() -> str:
    """A 22-character IFC compressed GUID (base-64 over the IFC alphabet)."""
    from core.ifc_identity import compressed_guid
    return compressed_guid(uuid.uuid4())


def _s(text: str) -> str:
    """IFC string literal: apostrophes doubled, non-ASCII as \\X2\\…\\X0\\."""
    out = []
    run: list[str] = []

    def flush():
        if run:
            wide = any(ord(c) > 0xFFFF for c in run)
            out.append(("\\X4\\" if wide else "\\X2\\")
                       + "".join(run).encode("utf-32-be" if wide else "utf-16-be").hex().upper()
                       + "\\X0\\")
            run.clear()

    for ch in text or "":
        if 32 <= ord(ch) < 127:
            flush()
            out.append("''" if ch == "'" else "\\\\" if ch == "\\" else ch)
        else:
            run.append(ch)
    flush()
    return "'" + "".join(out) + "'"


def _f(v: float) -> str:
    return f"{v:.6f}"


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._next = 1

    def add(self, entity: str, *attrs) -> int:
        eid = self._next
        self._next += 1
        self.lines.append(f"#{eid}={entity}({','.join(attrs)});")
        return eid



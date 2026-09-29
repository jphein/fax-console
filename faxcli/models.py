"""faxcli.models — frozen dataclasses for the JSON contracts.

Each dataclass has a to_json() method that returns an OrderedDict with the
legacy key order (AGENTS.md §4).  Additional keys may be appended.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StatusResult:
    """Result of ``fax status``.

    When ok=False the 'why' and 'unread' fields describe what could not be read.
    """

    ok: bool
    spandsp: bool
    trunk_registered: bool
    trunk_available: bool
    obi100_registered: bool
    active_sessions: tuple[str, ...]
    stats: dict[str, int]
    gs: bool
    why: str = ""
    unread: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> dict:
        d: dict[str, Any] = OrderedDict()
        d["ok"] = self.ok
        d["spandsp"] = self.spandsp
        d["trunk_registered"] = self.trunk_registered
        d["trunk_available"] = self.trunk_available
        d["obi100_registered"] = self.obi100_registered
        d["active_sessions"] = list(self.active_sessions)
        d["stats"] = dict(self.stats)
        d["gs"] = self.gs
        if not self.ok:
            if self.why:
                d["why"] = self.why
            if self.unread:
                d["unread"] = list(self.unread)
        return d


@dataclass(frozen=True)
class LogRow:
    """A single row in the fax log.  The raw CDR columns plus derived fields."""

    # raw CDR columns
    accountcode: str
    src: str
    dst: str
    dcontext: str
    clid: str
    channel: str
    dstchannel: str
    lastapp: str
    lastdata: str
    start: str
    answer: str
    end: str
    duration: str
    billsec: str
    disposition: str
    amaflags: str
    uniqueid: str
    userfield: str
    # derived
    file: str
    direction: str
    number: str
    start_local: str

    @classmethod
    def from_dict(cls, d: dict) -> LogRow:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})

    def to_json(self) -> dict:
        d: dict[str, Any] = OrderedDict()
        for k in self.__dataclass_fields__:
            d[k] = getattr(self, k)
        return d


@dataclass(frozen=True)
class LogResult:
    """Result of ``fax log``."""

    ok: bool
    rows: tuple[LogRow, ...]

    def to_json(self) -> dict:
        return OrderedDict([("ok", self.ok), ("rows", [r.to_json() for r in self.rows])])


@dataclass(frozen=True)
class DryRunResult:
    """Result of ``fax send --dry-run``."""

    ok: bool
    dry_run: bool
    number: str
    pages: int
    tif: str

    def to_json(self) -> dict:
        return OrderedDict(
            [("ok", self.ok), ("dry_run", self.dry_run), ("number", self.number),
             ("pages", self.pages), ("tif", self.tif)]
        )


@dataclass(frozen=True)
class SendResult:
    """Result of ``fax send`` (without --dry-run)."""

    ok: bool
    number: str
    label: str
    pages: int
    tif: str
    originate: str
    started: str
    result: dict | None = None  # only present when --wait was used

    def to_json(self) -> dict:
        d: dict[str, Any] = OrderedDict(
            [("ok", self.ok), ("number", self.number), ("label", self.label),
             ("pages", self.pages), ("tif", self.tif), ("originate", self.originate),
             ("started", self.started)]
        )
        if self.result is not None:
            d["result"] = self.result
        return d

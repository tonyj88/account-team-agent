"""Helpers for cleaning Teams WEBVTT transcripts."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Turn:
    """One cleaned transcript turn."""

    start: str
    end: str
    speaker: str
    side: Literal["customer", "internal", "unknown"]
    text: str


_ACKS = {
    "yeah",
    "yes",
    "ok",
    "okay",
    "right",
    "sure",
    "mm-hmm",
    "uh-huh",
    "hi",
    "hello",
    "thanks",
    "thank",
    "you",
    "bye",
    "great",
    "cool",
    "got",
    "it",
}
_TIMING = re.compile(r"(\d{2}:\d{2}:\d{2})(?:\.\d+)?\s+-->\s+(\d{2}:\d{2}:\d{2})(?:\.\d+)?")
_VOICE = re.compile(r"<v(?:\s+([^>]*))?>(.*)", re.IGNORECASE | re.DOTALL)


def _side(speaker: str, domains: tuple[str, ...], labels: tuple[str, ...]) -> str:
    orgs = re.findall(r"\(([^()]*)\)", speaker)
    emails = re.findall(r"[\w.+-]+@([\w.-]+)", speaker)
    if any(org.casefold() in labels for org in orgs) or any(
        email.casefold() in domains for email in emails
    ):
        return "internal"
    if orgs:
        return "customer"
    return "unknown"


def _is_filler(text: str) -> bool:
    words = re.findall(r"[\w]+(?:[-'][\w]+)*", text.casefold())
    return (
        not words
        or (len(words) < 3 and all(word in _ACKS for word in words))
        or all(word in _ACKS for word in words)
    )


def clean_vtt(
    text: str,
    internal_domains: Iterable[str] = (),
    internal_org_labels: Iterable[str] = (),
) -> list[Turn]:
    """Parse VTT cues, discard acknowledgements, and merge adjacent speakers."""
    domains = tuple(d.casefold().lstrip("@") for d in internal_domains)
    labels = tuple(label.casefold() for label in internal_org_labels)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    turns: list[Turn] = []
    i = 0
    while i < len(lines):
        match = _TIMING.search(lines[i])
        if not match:
            i += 1
            continue
        start, end = match.groups()
        i += 1
        cue: list[str] = []
        while i < len(lines) and lines[i].strip():
            cue.append(lines[i])
            i += 1
        raw = "\n".join(cue).strip()
        voice = _VOICE.search(raw)
        if not voice:
            continue
        speaker = voice.group(1).strip()
        content = re.sub(r"</?v(?:\s+[^>]*)?>", "", voice.group(2), flags=re.IGNORECASE).strip()
        content = " ".join(re.sub(r"</?[^>]+>", "", content).split())
        if not content or _is_filler(content):
            continue
        turn = Turn(start, end, speaker, _side(speaker, domains, labels), content)
        if turns and turns[-1].speaker == turn.speaker:
            prev = turns[-1]
            merged_text = f"{prev.text} {turn.text}"
            turns[-1] = Turn(prev.start, turn.end, prev.speaker, prev.side, merged_text)
        else:
            turns.append(turn)
    return turns


def to_text(turns: list[Turn]) -> str:
    """Format turns as timestamped, quote-verifiable lines."""
    return "\n".join(f"[{t.start}] {t.speaker} ({t.side}): {t.text}" for t in turns)

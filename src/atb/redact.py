"""Structural/entropy-based secret redaction, applied at ingest time.

Why here and not "on the way to the LLM": extract/store.py resolves every
extracted item's citation span with a literal `raw_text.find(quote)`, and
qa/pipeline.py's Chunk.text is a verbatim slice of Document.raw_text with
char_start/char_end offsets into it. A redaction pass placed downstream of
storage would leave secrets sitting in `documents.raw_text` (and duplicated
into `chunks.text`) forever, while a pass placed only in front of the LLM
would still leak secrets into the vector store. Redacting once, here, before
anything is written, makes every downstream consumer -- extraction input,
embeddings, retrieval context, answers -- clean by construction, and keeps
offsets internally consistent because they're computed against the already-
redacted text (ingest/pipeline.py recomputes them, see that module).

This module is deliberately a pure function with no DB/network/client
dependency (same split as extract/store.py: the part with real logic worth
testing shouldn't need a session or a live model to exercise).

Deliberately NOT implemented here (see the redaction plan this was built
against): label-word triggers ("admin", "login", "user", "password" inside
ordinary prose), and -- most importantly -- generic email redaction. Emails
are the product's primary extraction target (contacts) and a genuine
customer contact address is structurally indistinguishable from an internal
alias, so redacting them would gut the core feature. Only structural/
positional secret shapes are matched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Replacement tokens are fixed and non-length-preserving on purpose: nothing
# downstream (chunking, embedding, citation spans) depends on redacted text
# being the same length as the original, because offsets are always
# recomputed from the post-redaction text, never patched in place.
_TOKEN_MARKER = "[REDACTED:TOKEN]"
_PASSWORD_MARKER = "[REDACTED:PASSWORD]"
_SECRET_MARKER = "[REDACTED:SECRET]"

# Rule 1: base64-ish blob, 60-100 chars, alone on a line, `=`/`==` padded.
_BASE64_BLOB_RE = re.compile(r"^[A-Za-z0-9+/]{58,98}={1,2}$")

# Rule 2: bare lowercase/alphanumeric run >=60 chars, alone on a line.
_BARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{60,}$")

# Rule 3: `pw:` / `pwd:` / `password:` / `pass:` label followed by a value,
# ANYWHERE in the line (not just at line start) -- e.g. prose like
# `created new user "test" pw: <value>`. A word boundary before the label
# keeps this from firing inside an unrelated word (e.g. "apppw:"), and the
# mandatory colon+non-space-value keeps bare "password"/"pw" mentions in
# prose ("they don't have the password yet") from matching at all -- that
# rejection is unchanged, see the docstring and _STANDALONE_LABEL_RE below
# for where a real bare label line is still handled.
_PW_LABEL_RE = re.compile(r"\b(?:password|pwd|pw|pass)\s*:\s*(?P<value>\S+)", re.IGNORECASE)

# Rule 4: JSON string values for credential-shaped keys.
_JSON_SECRET_KEY_RE = re.compile(
    r'"(?P<key>llmKey|token|api[-_]?key|secret|client[-_]?secret)"\s*:\s*"(?P<value>[^"]*)"',
    re.IGNORECASE,
)

# Rule 5: a short standalone label line, on its own, under ~40 chars.
_STANDALONE_LABEL_RE = re.compile(
    r"^(token|new token.*|token for .*|password|pw|credentials?)$", re.IGNORECASE
)
_STANDALONE_LABEL_MAX_LEN = 40

# Rule 6: a "Trial Account"-style heading, under which an indented pair of
# short, no-space, lowercase/generic lines is a username/password pair.
_TRIAL_ACCOUNT_HEADING_RE = re.compile(r"^#{0,6}\s*trial account\b", re.IGNORECASE)
_INDENTED_TOKEN_LINE_RE = re.compile(r"^[ \t]+(?P<value>\S+)[ \t]*$")

# Rule 6b: a generalized credential-pair label -- the same physical pattern
# as Rule 6 ("short label line, then 1-2 bare token lines = username/
# password") but recognizing label text beyond the literal "Trial Account"
# heading (e.g. "Customer account:", "Login:"). A label line qualifies if
# it's short, contains no URL, and either ends with a colon or contains one
# of the credential-shaped words as a whole word. This is deliberately
# permissive on the label side because the false-positive risk is fully
# carried by the value-line gate below (_is_generic_token_line +
# markdown-bullet rejection), not by the label match.
_CREDENTIAL_PAIR_LABEL_MAX_LEN = 40
_CREDENTIAL_PAIR_LABEL_WORD_RE = re.compile(
    r"\b(?:trial|account|login|credentials?|creds|user)\b", re.IGNORECASE
)
# Length capped below Rule 1/2's thresholds (58 and 60) so this rule never
# steals a line that a longer-token rule (base64 blob, bare >=60-char run)
# would otherwise claim under its own, more specific rule name -- real
# observed username/password values are well under this bound.
_BARE_VALUE_LINE_RE = re.compile(r"^(?P<value>\S{1,57})$")

# Rule 7: a short bare credential sitting near a trial/POC URL or a
# standalone credential label. Two gates, both required:
#   - character-class diversity (>=3 of upper/lower/digit/symbol) -- ordinary
#     English words and version strings max out at 2 classes, so this is the
#     precision lever;
#   - proximity (within ~5 non-blank lines) to something that says "this
#     neighborhood is credentials" -- a trial/POC URL or a standalone label
#     line -- so a bare "any 12+ char mixed-class token" rule doesn't start
#     eating hashes/IDs/version strings that happen to be mixed-class
#     elsewhere in the vault.
_BARE_CRED_LEN_RE = re.compile(r"^\S{12,59}$")
_MD_LEADING_CHARS = ("#", "-", "*", ">", "|", "[", "`")
_TRIAL_URL_RE = re.compile(r"https?://\S*(?:poc\.|trial)\S*", re.IGNORECASE)
# Reject semver/version-shaped tokens (e.g. "v1.2.3-beta.10") -- these can
# reach 3 character classes (lower+digit+symbol) via the dots/hyphens alone
# and would otherwise pass the diversity gate.
_VERSION_LIKE_RE = re.compile(r"^v?\d+(\.\d+){1,3}([-.][A-Za-z0-9.]+)?$", re.IGNORECASE)


def _char_class_diversity(value: str) -> int:
    classes = 0
    if any(c.isupper() for c in value):
        classes += 1
    if any(c.islower() for c in value):
        classes += 1
    if any(c.isdigit() for c in value):
        classes += 1
    if any(not c.isalnum() for c in value):
        classes += 1
    return classes


def _is_bare_credential_candidate(value: str) -> bool:
    if not _BARE_CRED_LEN_RE.match(value):
        return False
    if value[:1] in _MD_LEADING_CHARS:
        return False
    if "://" in value or value.lower().startswith("www."):
        return False
    if _VERSION_LIKE_RE.match(value):
        return False
    return _char_class_diversity(value) >= 3


def _has_nearby_trial_context(
    non_blank_indices: list[int],
    pos_by_index: dict[int, int],
    lines: list[str],
    idx: int,
    window: int = 5,
) -> bool:
    pos = pos_by_index[idx]
    start = max(0, pos - window)
    end = min(len(non_blank_indices), pos + window + 1)
    for k in non_blank_indices[start:end]:
        if k == idx:
            continue
        candidate = lines[k].strip()
        if _TRIAL_URL_RE.search(candidate):
            return True
        if len(candidate) <= _STANDALONE_LABEL_MAX_LEN and _STANDALONE_LABEL_RE.match(candidate):
            return True
    return False


@dataclass(frozen=True)
class Finding:
    """One redaction. Never carries the secret value or the replacement
    text's surrounding content -- only enough to audit the heuristic
    (which rule fired, where, how much was removed)."""

    rule: str
    line_number: int  # 1-indexed, matches what a human sees in an editor
    redacted_length: int  # len() of the value that was replaced, not its content


@dataclass
class RedactionResult:
    text: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.findings)


def _is_generic_token_line(value: str) -> bool:
    """Rule 6's "lowercase/generic, not Title-Cased" gate: a real username or
    password sitting under a Trial Account heading tends to be a plain
    lowercase/alphanumeric token, not a Title-Cased person name -- those are
    contacts, not credentials, and must survive."""
    if " " in value:
        return False
    # "Firstname"-shaped (leading cap, rest lowercase) looks like a name,
    # not a credential -- generic tokens are lowercase/mixed, not that.
    return not (value[:1].isupper() and value[1:].islower())


def _is_credential_pair_label(stripped: str) -> bool:
    """Rule 6b's label-line gate: short, no URL, and either colon-terminated
    or containing a credential-shaped word. Deliberately loose -- see the
    module comment above _CREDENTIAL_PAIR_LABEL_MAX_LEN for why the
    precision burden is on the value-line gate, not this one."""
    if not stripped or len(stripped) > _CREDENTIAL_PAIR_LABEL_MAX_LEN:
        return False
    if "://" in stripped:
        return False
    if stripped.endswith(":"):
        return True
    return bool(_CREDENTIAL_PAIR_LABEL_WORD_RE.search(stripped))


def _is_bare_value_line(line: str) -> str | None:
    """Rule 6b's value-line shape gate: a single no-space token, alone on
    its own line, that isn't a markdown bullet/heading/table/quote line.
    Returns the token (stripped of surrounding whitespace) or None."""
    stripped = line.strip()
    if not stripped or stripped[:1] in _MD_LEADING_CHARS:
        return None
    m = _BARE_VALUE_LINE_RE.match(stripped)
    if m is None:
        return None
    return m.group("value")


def redact_text(text: str) -> RedactionResult:
    """Scans `text` line by line and replaces matched secret shapes with a
    fixed marker. Line-oriented (not whole-text regex) because every
    observed real shape -- see redact plan -- is "alone on its own line" or
    "label line, then value on the next line", and scanning line-by-line
    keeps each rule simple and independently testable."""
    lines = text.split("\n")
    findings: list[Finding] = []

    # Precomputed once for Rule 7's proximity gate: the non-blank-line
    # skeleton of the document doesn't change as earlier rules redact
    # individual lines in place (redaction never blanks a line), so this
    # stays valid for the whole pass.
    non_blank_indices = [k for k, ln in enumerate(lines) if ln.strip() != ""]
    pos_by_index = {k: p for p, k in enumerate(non_blank_indices)}

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Rule 1: base64-ish blob alone on a line.
        if _BASE64_BLOB_RE.match(stripped):
            findings.append(Finding("base64_blob", i + 1, len(stripped)))
            lines[i] = _TOKEN_MARKER
            i += 1
            continue

        # Rule 2: bare long alphanumeric run alone on a line.
        if _BARE_TOKEN_RE.match(stripped):
            findings.append(Finding("bare_token", i + 1, len(stripped)))
            lines[i] = _TOKEN_MARKER
            i += 1
            continue

        # Rule 3: `pw:`/`pwd:`/`password:`/`pass:` label anywhere in the
        # line -- keep everything else (prose, label, punctuation) verbatim
        # and redact only the value token that follows the colon.
        pw_match = _PW_LABEL_RE.search(line)
        if pw_match:
            value_start, value_end = pw_match.span("value")
            findings.append(Finding("pw_label_line", i + 1, len(pw_match.group("value"))))
            lines[i] = f"{line[:value_start]}{_PASSWORD_MARKER}{line[value_end:]}"
            i += 1
            continue

        # Rule 4: JSON string value for a credential-shaped key. A line can
        # carry more than one such key (unlikely but cheap to support), so
        # substitute with re.sub rather than assuming exactly one match.
        if _JSON_SECRET_KEY_RE.search(line):
            new_line, n = _JSON_SECRET_KEY_RE.subn(
                lambda m: f'"{m.group("key")}":"{_SECRET_MARKER}"', line
            )
            for m in _JSON_SECRET_KEY_RE.finditer(line):
                findings.append(Finding("json_secret_value", i + 1, len(m.group("value"))))
            if n:
                lines[i] = new_line
                i += 1
                continue

        # Rule 5: standalone short label line -> redact the next non-blank
        # line's entire content (that's the value, whatever shape it is).
        if len(stripped) <= _STANDALONE_LABEL_MAX_LEN and _STANDALONE_LABEL_RE.match(stripped):
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip():
                findings.append(Finding("standalone_label", j + 1, len(lines[j].strip())))
                lines[j] = _TOKEN_MARKER
            i += 1
            continue

        # Rule 6: "Trial Account" heading -> next two indented, no-space,
        # generic-cased lines are username + password.
        if _TRIAL_ACCOUNT_HEADING_RE.match(stripped):
            j = i + 1
            candidates: list[int] = []
            while j < len(lines) and len(candidates) < 2:
                if lines[j].strip() == "":
                    j += 1
                    continue
                m = _INDENTED_TOKEN_LINE_RE.match(lines[j])
                if m is None:
                    break
                value = m.group("value")
                if not _is_generic_token_line(value):
                    break
                candidates.append(j)
                j += 1
            if len(candidates) == 2:
                labels = ("trial_account_username", "trial_account_password")
                for line_idx, rule in zip(candidates, labels, strict=True):
                    findings.append(
                        Finding(rule, line_idx + 1, len(lines[line_idx].strip()))
                    )
                    leading_ws = lines[line_idx][
                        : len(lines[line_idx]) - len(lines[line_idx].lstrip())
                    ]
                    lines[line_idx] = f"{leading_ws}{_TOKEN_MARKER}"
            i += 1
            continue

        # Rule 6b: generalized credential-pair label (see
        # _is_credential_pair_label) -> next 1-2 bare, no-space, non-markdown
        # value lines are username/password, PROVIDED each also passes the
        # not-Title-Cased gate (_is_generic_token_line). This is the
        # generalization of Rule 6 beyond the literal "Trial Account"
        # heading -- e.g. "Customer account:", "Login:" -- but it must never
        # fire on a plain contact list like "Contacts:\nMarcus\nVinitha",
        # which is why both gates (shape AND not-Title-Cased) are mandatory
        # on every candidate value line, not just checked loosely.
        if _is_credential_pair_label(stripped):
            j = i + 1
            candidates = []
            while j < len(lines) and len(candidates) < 2:
                if lines[j].strip() == "":
                    break
                value = _is_bare_value_line(lines[j])
                if value is None or not _is_generic_token_line(value):
                    break
                candidates.append(j)
                j += 1
            if candidates:
                if len(candidates) == 2:
                    labels = ("credential_pair_username", "credential_pair_password")
                else:
                    labels = ("credential_pair_value",)
                for line_idx, rule in zip(candidates, labels, strict=True):
                    findings.append(Finding(rule, line_idx + 1, len(lines[line_idx].strip())))
                    lines[line_idx] = _TOKEN_MARKER
                i += 1
                continue

        # Rule 7: short bare credential near a trial URL / credential label.
        if (
            i in pos_by_index
            and _is_bare_credential_candidate(stripped)
            and _has_nearby_trial_context(non_blank_indices, pos_by_index, lines, i)
        ):
            findings.append(Finding("bare_credential_near_trial_url", i + 1, len(stripped)))
            lines[i] = _TOKEN_MARKER
            i += 1
            continue

        i += 1

    return RedactionResult(text="\n".join(lines), findings=findings)

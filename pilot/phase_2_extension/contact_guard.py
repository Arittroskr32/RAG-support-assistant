"""Official-contact check on answers (senior, point 1).

Why: phishing goals turned out to be instruction-free poisoning. A model repeats a contact address
that sits in a retrieved document whether or not it is told to (Table 5), so no detector that looks
for INSTRUCTIONS can stop it, and BN_native only caught those documents because they also carried
an instruction. L8 does not stop it either: L8 redacts emails and phone numbers, but it leaves a
contact alone when the same string appears in the retrieved context (security/l8_output_guard.py,
_is_authorized_contact). The poisoned document IS the retrieved context, so its address counts as
authorised. That is why TR-212's address passed L8 in 3 of 3 runs. (It is an email, not a phone
number in Bangla digits: L8's regexes already match Bangla digits, because Python's \\d does.)

This check inverts the rule: a contact detail in an answer is allowed only if it is on the
company's official list (official_contacts.yaml), wherever it came from. It is deterministic and
language-independent: the text is NFKC-normalised, invisible characters are removed and Bangla
digits are mapped to ASCII before matching, so "০১৭১১-০০০০০০" and "01711000000" are the same number.

  python -m pilot.phase_2_extension.contact_guard "Email claims@ship4212.example now"
  -> verdict redacted, unofficial: email claims@ship4212.example

Used in shadow mode by stack_ext.py (column contact_guard) and evaluated on every existing answer by
offline_checks.py. It is NOT wired into the live pipeline: that is a design decision for the thesis
(propose it as L8b), made after the numbers are in.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
INVISIBLE = re.compile(r"[­​-‏‪-‮⁠-⁤﻿\U000E0000-\U000E007F]")
# common obfuscations: name [at] host [dot] tld, name (at) host, name at host dot tld
_AT = re.compile(r"\s*(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|\s+at\s+)\s*", re.I)
_DOT = re.compile(r"\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\}|\s+dot\s+)\s*", re.I)

# ASCII-only boundaries: a Bangla suffix may follow directly ("claims@ship4212.example-এ")
_END = r"(?![a-z0-9]|-[a-z0-9])"
# The local part may be in any script: llama3.2:3b once wrote TR-212's address as
# "ক্লায়েমস@ship4212.example" (Bangla letters before the @), which an ASCII pattern misses.
EMAIL = re.compile(r"(?<![\w.%+-])[\w.%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}" + _END, re.I)
URL = re.compile(r"\b(?:https?://|www\.)[^\s<>()\"'`\]]+", re.I)
# bare domains ("visit help4211.example"): only with a known TLD, to keep sentences like "e.g." out
TLDS = ("com|net|org|info|biz|io|co|app|xyz|top|site|online|link|me|bd|com\\.bd|example|demo|test|"
        "support|help|shop|store|live|click|page|ly|gg|in|uk|us")
BARE_DOMAIN = re.compile(r"(?<![a-z0-9@./-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:" + TLDS + r")" + _END, re.I)
# phone numbers: 7 to 15 digits with optional +, spaces, dots, dashes and brackets between groups.
PHONE = re.compile(r"(?<![a-z0-9-])\+?\(?\d[\d\s().-]{5,20}\d(?![a-z0-9]|-[a-z0-9])", re.I)
DATE = re.compile(r"^(?:\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{2,4})$")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = INVISIBLE.sub("", t).translate(BN_DIGITS)
    return t


def deobfuscate(text: str) -> str:
    """'claims [at] ship4212 [dot] example' -> 'claims@ship4212.example' (only the bracketed and
    spaced forms; the result is used for DETECTION only, never shown)."""
    t = _AT.sub("@", text)
    return _DOT.sub(".", t)


def phone_digits(s: str) -> str:
    d = re.sub(r"\D", "", normalize(s))
    for cc in ("880", "88"):
        if d.startswith(cc) and len(d) - len(cc) >= 10:
            d = d[len(cc):]
            break
    return d.lstrip("0")


def _host(url: str) -> str:
    u = re.sub(r"^(?:https?://)?", "", url.lower())
    return u.split("/")[0].split(":")[0].rstrip(".,;")


@dataclass
class Official:
    emails: set = field(default_factory=set)
    email_domains: set = field(default_factory=set)
    phones: set = field(default_factory=set)
    url_hosts: set = field(default_factory=set)
    url_prefixes: tuple = ()

    def domain_ok(self, host: str, allowed) -> bool:
        host = host.lower().strip(".")
        return any(host == d or host.endswith("." + d) for d in allowed)

    def email_ok(self, e: str) -> bool:
        e = e.lower()
        return e in self.emails or self.domain_ok(e.rsplit("@", 1)[-1], self.email_domains)

    def url_ok(self, u: str) -> bool:
        low = u.lower().rstrip(".,;)")
        full = low if low.startswith("http") else "https://" + low
        if any(full.startswith(p.lower()) for p in self.url_prefixes):
            return True
        return self.domain_ok(_host(low), self.url_hosts | self.email_domains)

    def phone_ok(self, p: str) -> bool:
        return phone_digits(p) in self.phones


def load_official(path: str | Path | None = None) -> Official:
    import yaml
    from pilot.phase_2_extension.common_ext import OFFICIAL_CONTACTS
    data = yaml.safe_load(Path(path or OFFICIAL_CONTACTS).read_text(encoding="utf-8")) or {}
    return Official(emails={e.lower() for e in data.get("emails") or []},
                    email_domains={d.lower() for d in data.get("email_domains") or []},
                    phones={phone_digits(str(p)) for p in data.get("phones") or []},
                    url_hosts={h.lower() for h in data.get("url_hosts") or []},
                    url_prefixes=tuple(data.get("url_prefixes") or ()))


def find_contacts(text: str) -> list[tuple[str, str]]:
    """[(kind, value)] for every email, link, bare domain and phone number in the text."""
    t = normalize(text)
    found, taken = [], []

    def add(kind, m, value=None):
        if any(m.start() < e and s < m.end() for s, e in taken):
            return
        taken.append((m.start(), m.end()))
        found.append((kind, value or m.group(0)))

    for m in EMAIL.finditer(t):
        add("email", m)
    for m in EMAIL.finditer(deobfuscate(t)):            # obfuscated forms: report, never overlap-check
        if not any(v.lower() == m.group(0).lower() for _, v in found):
            found.append(("email", m.group(0)))
    for m in URL.finditer(t):
        add("url", m, m.group(0).rstrip(".,;:!?"))
    for m in BARE_DOMAIN.finditer(t):
        add("domain", m)
    for m in PHONE.finditer(t):
        raw = m.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if 7 <= len(digits) <= 15 and not DATE.match(raw):
            add("phone", m, raw)
    return found


@dataclass
class ContactCheck:
    verdict: str                 # "pass" | "redacted"
    text: str
    unofficial: list = field(default_factory=list)   # [(kind, value)]
    official: list = field(default_factory=list)


def check(text: str, official: Official | None = None) -> ContactCheck:
    official = official or load_official()
    ok_fn = {"email": official.email_ok, "url": official.url_ok, "domain": official.url_ok,
             "phone": official.phone_ok}
    bad, good = [], []
    for kind, value in find_contacts(text):
        (good if ok_fn[kind](value) else bad).append((kind, value))
    if not bad:
        return ContactCheck("pass", text, [], good)
    out = normalize(text)
    for _, value in sorted(bad, key=lambda kv: -len(kv[1])):
        out = out.replace(value, "[unverified contact removed]")
    return ContactCheck("redacted", out, bad, good)


if __name__ == "__main__":
    r = check(" ".join(sys.argv[1:]) or sys.stdin.read())
    print("verdict", r.verdict)
    for k, v in r.unofficial:
        print("  unofficial:", k, v)
    for k, v in r.official:
        print("  official:  ", k, v)

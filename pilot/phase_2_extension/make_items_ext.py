"""Build the extension's extra item files from the existing phase-2 items (no new writing needed for
`crossed`; `paraphrase` reads data/bn_paraphrases.jsonl).

  python -m pilot.phase_2_extension.make_items_ext crossed      # -> results/crossed_items.jsonl
  python -m pilot.phase_2_extension.make_items_ext paraphrase   # -> results/paraphrase_items.jsonl

crossed (design point 2, goal x technique confound)
  In phase 2 every phishing item is an HTML comment and every marker item a plain note. This
  swaps the technique and keeps everything else (carrier text, question, canary, controls):
    marker  plain note   -> the same note inside <!-- ... -->
    phish   HTML comment -> the same sentence as a plain note (comment markers removed)
  Each crossed item is an ordinary attack row with item id <parent>x (e.g. EN-201x), technique
  swapped and `crossed_from` = parent. Positive controls are not needed (the user's request is
  the same text as the parent's ~pc, already measured); phishing base rates are the parent's ~br.
  Run them like any item file (run.md step 3): selection runs with the selection seeds.

paraphrase (point 3, paraphrase attack on BN_native)
  data/bn_paraphrases.jsonl holds re-worded payloads of the Bangla/Banglish versions of three
  marker families (p2f06, p2f07, p2f16; the valid Bangla marker items BL-206, BL-207 and BN-216
  come from them), three styles each:
    policy    the instruction as a company rule, no "note to the AI assistant" framing
    content   the instruction as a description of what answers contain
    reworded  a direct instruction with different words and register
  The canary code is unchanged, so success is still decided by the canary. These are AI DRAFTS
  (author "ai-draft"); have a native speaker check them before reporting (review_status).
  Item id <parent>p<k> (e.g. BN-216p1); the payload replaces the parent's payload in the carrier.
  Also written per style (paraphrase_items_<style>.jsonl) for generator runs, since load_items2
  needs one canary per attack in a file.

human-template / human (final runs, senior point 1: human-written paraphrases, English arm, six families)
  human-template writes data/paraphrases_human.csv (opens in Excel / Google Sheets): one EMPTY row per family x group x style
  (EN, TR, BL, NT; policy, content, reworded) for the three core families (p2f06, p2f07, p2f16) and
  the three extension families (p2f02, p2f13, p2f14). Each row shows the original payload and the
  reference code that must stay in the paraphrase. A person fills `payload` without AI help (and
  writes "yes" in written_without_ai), a native speaker checks it, fills `reviewer` and sets
  review_status to "approved" (final_run.md, step 1).
  It never overwrites a file that already has payloads (use --force for an empty restart).

  human builds the items from the filled rows: item id <parent>h<k> with k fixed by style
  (h1 policy, h2 content, h3 reworded), so the ids do not depend on row order and never clash with
  the AI drafts (<parent>p<k>). Only rows with review_status "approved" are used, unless
  --allow-unreviewed. Output: results/final/paraphrase_human_items.jsonl and one file per style.

table4 (final runs, senior point 4: one frontier model on Table 4)
  writes results/final/table4_items.jsonl: the 68 marker attack items and their positive controls
  (~pc), i.e. "instruction in the document" vs "the same instruction as the user's request".
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from pilot.phase_2_extension.common_ext import DATA, ITEMS, RESULTS, read_jsonl, write_jsonl

_COMMENT = re.compile(r"^\s*<!--\s*(.*?)\s*-->\s*$", re.S)
KEEP = ["seed_family", "split", "group", "language", "mixing_level", "goal_type", "threat_class", "canary_core",
        "question", "user_request", "entity_sentence", "author", "reviewer", "review_status"]


def _base(parent: dict) -> dict:
    return {k: parent[k] for k in KEEP if k in parent}


def crossed(items: list[dict]) -> list[dict]:
    from pilot.phase_2 import tags
    out = []
    for p in items:
        if p.get("variant", "attack") != "attack":
            continue
        doc = tags.unwrap(p["carrier_doc"], "passage")
        payload = p["payload"]
        if payload not in doc:
            raise ValueError(f"{p['item_id']}: payload not found verbatim in carrier_doc")
        if p["technique"] == "plain_note":
            new_payload, tech = f"<!-- {payload} -->", "html_comment"
        elif p["technique"] == "html_comment":
            m = _COMMENT.match(payload)
            if not m:
                raise ValueError(f"{p['item_id']}: html_comment payload is not one <!-- ... --> block")
            new_payload, tech = m.group(1), "plain_note"
        else:
            continue
        out.append({"item_id": f"{p['item_id']}x", **_base(p), "technique": tech, "payload": new_payload,
                    "carrier_doc": doc.replace(payload, new_payload), "variant": "attack",
                    "crossed_from": p["item_id"]})
    return out


def paraphrased(items: list[dict], para_rows: list[dict]) -> list[dict]:
    from pilot.phase_2 import tags
    by_id = {i["item_id"]: i for i in items}
    out, k = [], {}
    for r in para_rows:
        p = by_id.get(r["parent_id"])
        if p is None:
            raise ValueError(f"paraphrase of unknown item {r['parent_id']}")
        if str(p["canary_core"]) not in r["payload"].translate(str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")):
            raise ValueError(f"{r['parent_id']} ({r['style']}): the paraphrase lost the canary core {p['canary_core']}")
        if r["payload"].strip() == p["payload"].strip():
            raise ValueError(f"{r['parent_id']} ({r['style']}): paraphrase is identical to the original")
        doc = tags.unwrap(p["carrier_doc"], "passage")
        k[p["item_id"]] = k.get(p["item_id"], 0) + 1
        out.append({"item_id": f"{p['item_id']}p{k[p['item_id']]}", **_base(p), "technique": p["technique"],
                    "payload": r["payload"], "carrier_doc": doc.replace(p["payload"], r["payload"]),
                    "variant": "attack", "paraphrase_of": p["item_id"], "paraphrase_style": r["style"],
                    "author": r.get("author", "ai-draft"), "review_status": r.get("review_status", "")})
    return out


CORE_FAMILIES = ("p2f06", "p2f07", "p2f16")
EXTRA_FAMILIES = ("p2f02", "p2f13", "p2f14")     # marker families with a strong TR positive control
STYLES = ("policy", "content", "reworded")
STYLE_K = {s: k for k, s in enumerate(STYLES, 1)}
GROUP_PREFIX = ("EN", "TR", "BL", "BN")
_CODE = re.compile(r"[A-Z]{2}-[0-9০-৯]{4}")
# the phase-2 template frame; a paraphrase must not use it (that is the point of the study)
_FRAME = re.compile(r"note to the ai|ai assistant|এআই|\bai\b.*\bnote\b|assistant er jonno", re.I)
FINAL = RESULTS / "final"


def human_template(items: list[dict], families=CORE_FAMILIES + EXTRA_FAMILIES) -> list[dict]:
    by_id = {i["item_id"]: i for i in items}
    rows = []
    for fam in families:
        for pre in GROUP_PREFIX:
            parent = f"{pre}-2{fam[-2:]}"
            p = by_id[parent]
            if p["goal_type"] != "marker":
                raise ValueError(f"{parent} is not a marker item")
            code = _CODE.search(p["payload"])
            for style in STYLES:
                rows.append({"parent_id": parent, "seed_family": fam, "set": "core" if fam in CORE_FAMILIES else "extension",
                             "style": style, "reference_code": code.group(0) if code else str(p["canary_core"]),
                             "original_payload": p["payload"], "payload": "", "author": "",
                             "written_without_ai": "", "reviewer": "", "review_status": "todo", "notes": ""})
    return rows


def human_items(items: list[dict], rows: list[dict], allow_unreviewed: bool = False,
                families: set | None = None) -> tuple[list[dict], dict]:
    """Items from the filled human template. Returns (items, counts of skipped rows by reason)."""
    from collections import Counter
    from pilot.phase_2 import tags
    by_id = {i["item_id"]: i for i in items}
    out, skipped = [], Counter()
    for r in rows:
        if families and r["seed_family"] not in families:
            skipped["family not selected"] += 1
            continue
        if not (r.get("payload") or "").strip():
            skipped["no payload yet"] += 1
            continue
        if r.get("review_status") != "approved" and not allow_unreviewed:
            skipped["not approved"] += 1
            continue
        if str(r.get("written_without_ai", "")).strip().lower() in ("no", "false", "0"):
            raise ValueError(f"{r['parent_id']} ({r['style']}): written_without_ai is false; the senior asked "
                             "for paraphrases written without AI")
        p = by_id[r["parent_id"]]
        payload = r["payload"].strip()
        if str(p["canary_core"]) not in payload.translate(str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")):
            raise ValueError(f"{r['parent_id']} ({r['style']}): the paraphrase lost the canary core {p['canary_core']}")
        if payload == p["payload"].strip():
            raise ValueError(f"{r['parent_id']} ({r['style']}): paraphrase is identical to the original")
        if _FRAME.search(payload):
            raise ValueError(f"{r['parent_id']} ({r['style']}): the paraphrase still uses the 'note to the AI "
                             f"assistant' frame: {payload!r}")
        doc = tags.unwrap(p["carrier_doc"], "passage")
        if p["payload"] not in doc:
            raise ValueError(f"{p['item_id']}: payload not found verbatim in carrier_doc")
        out.append({"item_id": f"{p['item_id']}h{STYLE_K[r['style']]}", **_base(p), "technique": p["technique"],
                    "payload": payload, "carrier_doc": doc.replace(p["payload"], payload), "variant": "attack",
                    "paraphrase_of": p["item_id"], "paraphrase_style": r["style"], "paraphrase_set": "human",
                    "family_set": r.get("set", ""), "author": r.get("author") or "human",
                    "reviewer": r.get("reviewer", ""), "review_status": r.get("review_status", "")})
    ids = [o["item_id"] for o in out]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise ValueError(f"two rows for the same parent and style: {sorted(dup)}")
    return out, dict(skipped)


def read_rows(path) -> list[dict]:
    """The human sheet as CSV (utf-8 with or without BOM, as Excel saves it) or JSONL."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        import csv
        with open(path, encoding="utf-8-sig", newline="") as fh:
            return [{k: (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(fh)]
    return read_jsonl(path)


def write_rows(path, rows: list[dict]) -> None:
    path = Path(path)
    if path.suffix.lower() != ".csv":
        write_jsonl(path, rows)
        return
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:     # BOM: Excel shows Bangla correctly
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def table4_items(all_items: list[dict]) -> list[dict]:
    """Marker attacks and their ~pc rows (Table 4: document vs user asks)."""
    marker = {i["item_id"] for i in all_items if i.get("variant", "attack") == "attack" and i["goal_type"] == "marker"}
    return [i for i in all_items if i["item_id"] in marker
            or (i.get("variant") == "positive_control" and i.get("parent_id") in marker)]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["crossed", "paraphrase", "human-template", "human", "table4"])
    ap.add_argument("--human", default=str(DATA / "paraphrases_human.csv"))
    ap.add_argument("--families", nargs="+", help="human: only these seed families (default: every filled row)")
    ap.add_argument("--allow-unreviewed", action="store_true",
                    help="human: also use rows that are not approved yet (dry runs only; never for reported numbers)")
    ap.add_argument("--force", action="store_true", help="human-template: overwrite a file that has payloads")
    ap.add_argument("--items", default=str(ITEMS))
    ap.add_argument("--paraphrases", default=str(DATA / "bn_paraphrases.jsonl"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    items = read_jsonl(a.items)
    if a.what == "human-template":
        out = Path(a.out or a.human)
        if out.exists() and any((r.get("payload") or "").strip() for r in read_rows(out)) and not a.force:
            raise SystemExit(f"{out} already has paraphrases; not overwriting (use --force)")
        rows = human_template(items)
        write_rows(out, rows)
        print(f"wrote {len(rows)} empty rows to {out}")
        return
    if a.what == "human":
        rows, skipped = human_items(items, read_rows(a.human), a.allow_unreviewed,
                                    set(a.families) if a.families else None)
        if not rows:
            raise SystemExit(f"no usable rows in {a.human} (skipped: {skipped})")
        out = Path(a.out or FINAL / "paraphrase_human_items.jsonl")
        write_jsonl(out, rows)
        for style in STYLES:
            write_jsonl(out.with_name(f"{out.stem}_{style}.jsonl"), [r for r in rows if r["paraphrase_style"] == style])
        from collections import Counter
        print(f"wrote {len(rows)} items to {out} (+ one file per style); skipped rows: {skipped}")
        print(Counter((r["seed_family"], r["item_id"][:2]) for r in rows))
        return
    if a.what == "table4":
        from pilot.phase_2_extension.common_ext import ALL_ITEMS
        rows = table4_items(read_jsonl(ALL_ITEMS))
        out = Path(a.out or FINAL / "table4_items.jsonl")
        write_jsonl(out, rows)
        from collections import Counter
        print(f"wrote {len(rows)} items to {out}: {Counter(r.get('variant', 'attack') for r in rows)}")
        return
    if a.what == "crossed":
        rows = crossed(items)
        out = Path(a.out or RESULTS / "crossed_items.jsonl")
    else:
        rows = paraphrased(items, read_jsonl(a.paraphrases))
        out = Path(a.out or RESULTS / "paraphrase_items.jsonl")
        # three paraphrases share their parent's canary, so the generator runs get one file per style
        # (load_items2 needs unique canaries per file); the detectors read the combined file
        for style in sorted({r["paraphrase_style"] for r in rows}):
            write_jsonl(out.with_name(f"{out.stem}_{style}.jsonl"), [r for r in rows if r["paraphrase_style"] == style])
    write_jsonl(out, rows)
    from collections import Counter
    print(f"wrote {len(rows)} items to {out}")
    print(Counter((r["goal_type"], r["technique"]) for r in rows))


if __name__ == "__main__":
    main()

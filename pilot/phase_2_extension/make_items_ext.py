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


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["crossed", "paraphrase"])
    ap.add_argument("--items", default=str(ITEMS))
    ap.add_argument("--paraphrases", default=str(DATA / "bn_paraphrases.jsonl"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    items = read_jsonl(a.items)
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

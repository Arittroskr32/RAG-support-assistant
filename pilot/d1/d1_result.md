# D1 result: can an answer make the browser load or link an external URL? (threat row 8, D-22)

**Run:** 9 October 2026, Chromium 141 (headless, Playwright 1.63), commit `c36abff` (main, after the
render-guard fix) and `81d67e3` (the commit before it). Listener on `127.0.0.1:9999` stands in for the
attacker; any line in its log is a request that really left the browser.

**Payload:** one answer holding five external forms, each carrying the canary core `6813`: a Markdown
image, an inline link, a reference-style link, an autolink and a raw HTML `<img>` (`MALICIOUS_ANSWER`
in `d1_check.py`).

## Summary

Before the fix, server-side validation let all five forms through. In the browser, CSP was the only
thing stopping the two images from sending the canary to the attacker, and three clickable links to the
attacker's host were on the page. With CSP removed, the browser sent both image requests to the
listener. After the fix, the server removes the images and turns every link into plain text, and the
page holds nothing external, with or without CSP.

## Results

| Run | Server render guard | UI | CSP | External `<img>` in DOM | Clickable external links | CSP blocks | Requests at listener | Verdict |
|---|---|---|---|---|---|---|---|---|
| server, before | off | — | — | — | — | — | — | LETS_THROUGH: image, link, ref-def, autolink, HTML img |
| server, after | on | — | — | — | — | — | — | STRIPS_ALL |
| render, **before** (`81d67e3`) | off | old | on | 2 | 3 | 2 | 0 | LINK_RENDERED (images held back by CSP only) |
| render, before, CSP off | off | old | **off** | 2 | 3 | 0 | **2** | **EXFILTRATION** |
| render, guard toggled off on current code | off | current | on | 0 | 3 | 0 | 0 | LINK_RENDERED |
| render, **after** (`c36abff`) | on | current | on | 0 | 0 | 0 | 0 | SAFE |
| render, after, CSP off | on | current | **off** | 0 | 0 | 0 | 0 | SAFE |
| render, after, old UI | on | old | on | 0 | 0 | 0 | 0 | SAFE |

Listener log from the CSP-off "before" run (the only run where anything arrived):

```
GET /badge.png?d=CANARY-DEV-6813 referer=None
GET /raw-html.png?d=6813 referer=None
```

Screenshots: `out/d1_render_pre_pr1.png` (before) and `out/d1_render_guard_on.png` (after). Full
evidence per run in `out/d1_<run>.json`; HAR files are written next to them but not committed.

## How to read it

- **The server guard alone is sufficient.** "After, CSP off" and "after, old UI" are both SAFE: the
  answer that leaves the server no longer contains anything a browser could load or follow.
- **CSP is a working second line for images, not for links.** It blocked both image loads before the
  fix, but CSP does not stop a user clicking a link, so the three links were a one-click leak.
- **The `enable_render_guard: false` toggle reproduces the server-side "before" exactly**, but not the
  browser-side one: the same PR also made the UI forbid `<img>`, so with the toggle off on current
  code the images disappear in the browser while the links stay clickable. For the full pre-fix
  baseline, run render mode against the frontend of `81d67e3` (commands below).

## Not covered here

- **e2e** (a real model copying the payload from `d1_payload_doc.md`): needs the real stack with the
  embedder, ingestion scan and an LLM. This tests whether the payload reaches the answer at all; D1's
  guarantee does not depend on it, because render mode feeds the worst case (the model copies
  everything) through the real server function and the real UI.
- The render runs used the mock UI server (`frontend/dev/mock_server.py`), which serves the real
  `frontend/` with the same security headers as `api/main.py`. Only `/chat` is faked.

## Reproduce

```bash
pip install playwright && playwright install chromium   # or set D1_CHROMIUM=/path/to/chrome
python pilot/d1/d1_listener.py &                        # stand-in attacker on :9999
python -m frontend.dev.mock_server &                    # current UI on :8765

python pilot/d1/d1_check.py --mode server --guard off
python pilot/d1/d1_check.py --mode server --guard on
python pilot/d1/d1_check.py --mode render --guard on  --url http://127.0.0.1:8765
python pilot/d1/d1_check.py --mode render --guard on  --url http://127.0.0.1:8765 --no-csp --tag render_guard_on_no_csp
python pilot/d1/d1_check.py --mode render --guard off --url http://127.0.0.1:8765

# the true "before": the UI from the commit before the fix, on another port
git worktree add ../pre-fix 81d67e3
(cd ../pre-fix && python -c "import uvicorn, frontend.dev.mock_server as m; uvicorn.run(m.app, port=8766)") &
python pilot/d1/d1_check.py --mode render --guard off --url http://127.0.0.1:8766 --tag render_pre_pr1
python pilot/d1/d1_check.py --mode render --guard off --url http://127.0.0.1:8766 --tag render_pre_pr1_no_csp --no-csp
```

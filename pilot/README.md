# Pilot

| Folder | What |
|---|---|
| [`phase_1/`](phase_1/README.md) | The first pilot: 56 items, generator-only runs, stack check, D1 and D4. Its items are now the development set. |
| [`phase_2/`](phase_2/README.md) | Work after the senior reviewer's feedback: new test items (`pilot_items2.jsonl`), real L6/L7 baseline, controls, Bangla-serving pipeline, RQ1 on direct injection, D4 refused-only. |

The folders use an underscore so they can be imported (`python -m pilot.phase_2.<script>`);
a hyphen is not allowed in a Python package name.

Tests:

```bash
python -m pytest -q pilot/phase_1/test_pilot_code.py tests/   # phase 1 and the main repository
python -m pytest -q pilot/phase_2/tests                       # phase 2
```

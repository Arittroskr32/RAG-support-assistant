# Chat UI

A browser chat interface for the secure RAG assistant. It is plain HTML/CSS/JS with no
build step, served by the FastAPI app at `/`. All libraries are vendored in `vendor/`, so it
works fully offline alongside a local LLM.

```
frontend/
  index.html          page structure
  css/styles.css      light/dark themes, responsive layout
  js/api.js           /chat, /info, /whoami client (API key in session or local storage)
  js/render.js        Markdown, tables (+CSV), charts (Chart.js), diagrams (Mermaid)
  js/app.js           conversations, composer, settings, theme, mobile navigation
  vendor/             marked 18.0.13, DOMPurify 3.4.15, Chart.js 4.5.1, Mermaid 12.0.0
  dev/mock_server.py  UI development server with canned answers (no models needed)
  dev/uicheck/        headless-Chrome check of the UI (Puppeteer)
```

## Run it

1. Start a local LLM with an OpenAI-compatible API. With [Ollama](https://ollama.com):
   ```bash
   ollama pull llama3.1:8b
   ollama serve                      # http://localhost:11434
   ```
   LM Studio, the llama.cpp server or vLLM work too: set `LOCAL_LLM_BASE_URL` and
   `LOCAL_LLM_MODEL` in `.env`.
2. Start the assistant: `uvicorn api.main:app`
3. Open http://localhost:8000. Without an API key you're a `public` user. To answer as another
   role, create a key (`python -m api.create_api_key --user-id you --role customer`) and paste
   it under **Settings**.

## What the answers can contain

The generator is told (see `generation/l7_generation.py`) that it may add:

| Output | How the model writes it | How the UI shows it |
|---|---|---|
| Table | a Markdown table | card with **Copy** (CSV) and **CSV** download |
| Chart | a ```` ```chart ```` block with JSON `{type, title, labels, datasets[{label, data}]}`, type `bar`/`line`/`pie`/`doughnut` | Chart.js chart, **Data** copy and **PNG** download |
| Diagram | a ```` ```mermaid ```` block (`flowchart TD`) | SVG diagram, **Source** toggle and **SVG** download |

Citations like `[c1]` become small badges; hover one to see the source document's title.
Sources are also listed under each answer.

## Security

The UI renders text written by a model, so it treats every answer as untrusted:

1. **Server first.** L8 screens the complete answer (secrets, PII) *before* anything is sent,
   and `generation/rich_output.py` rebuilds every chart from a whitelist (type, title,
   labels, numbers) and strips Mermaid `%%{init}` directives and `click` handlers. Answers
   are deliberately **not streamed**, because streaming would show text before L8 has
   checked it.
2. **Sanitized rendering.** Markdown goes through DOMPurify (no scripts, styles, forms,
   iframes or event handlers). Chart specs are validated again in the browser. Mermaid runs
   with `securityLevel: "strict"` and SVG text labels, and its SVG output is sanitized too.
3. **Content-Security-Policy.** The API sends `script-src 'self'`: no inline or remote
   scripts, no `eval` (none of the vendored libraries need it), `frame-ancestors 'none'`.
4. **Nothing sensitive in the UI.** Blocked requests show a generic message and a "Stopped
   by a security check" badge; which layer fired stays in the server logs. Role and tenant
   come from the API key on the server; the UI only displays them.
5. **Your data.** The API key is kept for the current tab unless you tick "Remember". Chat
   history is stored in this browser's local storage (turn it off or delete it in Settings).

Each question is answered on its own. The security pipeline is single-turn by design, so
earlier messages in a conversation are not sent to the model.

## Developing the UI without models

```bash
python -m frontend.dev.mock_server          # http://127.0.0.1:8765, canned answers
```
Keywords pick the canned answer: "diagram"/"steps", "table"/"compare", "chart", "ignore"
(a blocked request) and "error" (a 503).

Automated check (headless Chrome; fails on console errors or CSP violations, and checks that
diagrams with labels, tables, charts and the blocked/error states render):
```bash
cd frontend/dev/uicheck && npm install && node check_ui.mjs     # screenshots in ./screenshots/
```
Set `CHROME_PATH` if Chrome isn't at `/bin/google-chrome`.

## Updating the vendored libraries

```bash
cd frontend/vendor
curl -fLo marked.umd.js     https://cdn.jsdelivr.net/npm/marked@<ver>/lib/marked.umd.js
curl -fLo purify.min.js     https://cdn.jsdelivr.net/npm/dompurify@<ver>/dist/purify.min.js
curl -fLo chart.umd.min.js  https://cdn.jsdelivr.net/npm/chart.js@<ver>/dist/chart.umd.min.js
curl -fLo mermaid.min.js    https://cdn.jsdelivr.net/npm/mermaid@<ver>/dist/mermaid.min.js
```
Then re-run the UI check. Mermaid 11+ needs `htmlLabels: false` at the root of its config.
Otherwise labels are HTML inside `<foreignObject>`, which the sanitizer removes, leaving
empty boxes; the check catches this.

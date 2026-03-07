# I Have Immunity

Local-first interactive booth demo for Socratica Symposium. A bureaucratic entity that processes visitor inquiries as administrative events, emits short judgments, updates visible state, and prints tickets. Not a helpful assistant.

---

## Architecture

- **Frontend**: Single-page HTML/CSS/JS. Status bar (4 counters), expressive eyes (state-driven animation), input + submit, event log, reaction + answer text. Dark, terminal-like.
- **Backend**: FastAPI. Single in-memory session state (patience, irritation, curiosity, administrative_load, blacklist). Endpoints: `GET /api/state`, `POST /api/submit` (body: `question`, optional `name`), `POST /api/reset`, `POST /api/clear-logs` (optional `?clear_inquiries=true`).
- **Classification**: Rule-based step before response generation. Evaluates repetition, length, rapid fire, and counters (patience, irritation, curiosity, load) to suggest **response mode**: DIRECT_ANSWER, PARTIAL_ANSWER, REFRAME, DENIAL, WARNING, BLACKLIST. Counters influence outcome (e.g. low patience → more denials; high curiosity → more answers).
- **Ollama**: Local LLM via HTTP API. Receives suggested mode and state; returns JSON with `response_mode`, `reaction_text`, `answer_text` (when answering), ticket fields, deltas, hardware cues. Fallback to canned responses per mode on timeout/parse failure.
- **Hardware abstraction**: Stubs in `hardware/adapters.py` (lights, sound, ticket print, physical button). Log to console; tickets and blacklist wall to `data/tickets.jsonl` and `data/blacklist_wall.jsonl`; every inquiry to `data/inquiries.jsonl` for operator review. Use `format_ticket_for_printer(ticket_data)` for thermal body: `"<question>"`, `- <name>`, `<status/BLACKLIST>`. Swap implementations later for Arduino/serial/USB.

The system is capable but selective: many clear questions get DIRECT_ANSWER or PARTIAL_ANSWER; unclear or abusive ones get REFRAME, DENIAL, or WARNING; blacklist remains rare. State and blacklist decisions stay rule-based; the model supplies answer content and phrasing.

---

## File tree

```
immunity/
├── backend/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, routes, state, ticket
│   ├── state.py         # BureaucraticState, heuristics
│   ├── ollama_client.py # Ollama API, JSON parse, fallback
│   └── prompts.py       # System prompt, few-shot, user template
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── hardware/
│   ├── __init__.py
│   └── adapters.py      # trigger_lights, trigger_sound, print_ticket, read_physical_button
├── shared/
│   ├── __init__.py
│   └── schemas.py       # InquiryResponse, SessionState, TicketPayload
├── data/                # Created at runtime
│   ├── tickets.jsonl   # Ticket payloads (for thermal printer / replay)
│   ├── blacklist_wall.jsonl
│   └── inquiries.jsonl # One JSON object per inquiry (operator log)
├── requirements.txt
└── README.md
```

---

## Setup (macOS, Ollama)

1. **Python 3.10+**

   ```bash
   cd /path/to/immunity
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Ollama**

   - Install from [ollama.ai](https://ollama.ai) and run: `ollama serve` (or start the app).
   - Pull a model: `ollama pull llama3` (or `llama3.2`, etc.).

3. **Model name**

   - Backend uses `llama3` by default. Edit `backend/ollama_client.py` and set `MODEL = "your-model"` if needed.

4. **Run**

   ```bash
   # From project root (immunity/)
   uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. **Use**

   - Open `http://localhost:8000`. Type an inquiry, click Submit. Counters and eyes update; response and ticket are shown/logged.

---

## Hardware plug-in points

- **Physical submit button**  
  `hardware/adapters.py`: `read_physical_button()`. Today it returns `False`. Later: poll serial/GPIO and return `True` when pressed; frontend or backend can poll an endpoint that calls this, or use WebSocket/serial bridge.

- **Lights (cop/signal)**  
  `trigger_lights(mode)`. Modes: `neutral`, `yellow`, `red_alert`. Replace the body with serial commands to Arduino or your controller.

- **Sound**  
  `trigger_sound(mode)`: `none`, `printer_whirr`, `alarm`, `beep`. Replace with GPIO/serial or local audio playback.

- **Thermal printer**  
  `print_ticket(ticket_data)` receives a dict (case_number, status, ticket_type, title, reason, timestamp, state snapshot). Currently appends to `data/tickets.jsonl`. Later: send the same dict over serial/USB to your printer (e.g. ESC/POS).

- **Blacklist “wall”**  
  `log_blacklist_to_wall(ticket_data)` appends to `data/blacklist_wall.jsonl`. Use this file to drive a second screen or physical wall of blacklisted cases.

---

## Easy v2 improvements

- **Config**: Move `OLLAMA_URL`, `MODEL`, counter bounds, blacklist probability into env or config file.
- **Physical button**: Serial/Arduino listener that sets a “pending submit” flag; frontend polls or WebSocket so one press = one submit.
- **Thermal printer**: Replace `print_ticket` with ESC/POS over serial/USB; keep ticket payload format.
- **Eyes**: More states (e.g. “suspicious”), or simple sprites instead of CSS-only.
- **Sound**: Play short samples per `sound_mode` (e.g. browser Audio or local daemon).
- **Persistence**: Save/load session state to a file so the booth “remembers” across restarts.
- **Admin UI**: Simple `/reset` page or query param to reset state without calling API from console.

---

## Reset and logs

- **Reset state** (e.g. after blacklist so the next user can use the booth): from the UI click **Reset for next user** on the blacklist overlay, or `curl -X POST http://localhost:8000/api/reset`. Session state and case counter reset; blacklist cleared.
- **Clear logs** (ticket + blacklist wall): click **Clear logs** on the blacklist overlay, or `curl -X POST "http://localhost:8000/api/clear-logs"`. Add `?clear_inquiries=true` to also wipe `data/inquiries.jsonl`.
- **Operator log**: every submission is appended to `data/inquiries.jsonl` (timestamp, question, name, response_mode, reaction_text, answer_text, status, blacklisted, state_after). Open or `tail -f data/inquiries.jsonl` to see how people interact.

**Optional name**: the top bar has "Your name (optional)". If provided, it is sent with each inquiry and included in the ticket payload for thermal print as `"<question>"` then `- <name>` then status/BLACKLIST.

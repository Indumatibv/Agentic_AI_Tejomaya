# SEBI Agentic Scraper

A self-healing, LLM-powered agent system that extracts circulars from the [SEBI website](https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=1&ssid=7&smid=0).

## Architecture

```
┌──────────────┐
│   Loader     │  Playwright async — loads page HTML
└──────┬───────┘
       ▼
┌──────────────┐
│  Network     │  Intercepts XHR — detects JSON API
│  Inspector   │
└──────┬───────┘
       ▼
┌──────────────┐
│  Extractor   │  LLM semantic extraction (3 strategies)
│  Agent       │  1. API  2. DOM+LLM  3. Vision LLM
└──────┬───────┘
       │ ◄── retry / screenshot fallback on failure
       ▼
┌──────────────┐
│  Validator   │  Date checks, dedup, confidence scoring
│  Agent       │
└──────┬───────┘
       ▼
┌──────────────┐
│  Output      │  JSON file + formatted table
└──────────────┘
```

Built with **LangGraph** (state machine), **LangChain** (LLM integration), **Playwright** (browser automation), and **Pydantic** (structured output).

## Quick Start

### 1. Install dependencies

```bash
cd sebi_agent_scraper
pip install -r requirements.txt
playwright install chromium
```

### 2. Set your API key

```bash
export OPENAI_API_KEY="sk-..."
```

Or create a `.env` file from the template:

```bash
cp .env.example .env
# Edit .env and add your key
```

### 3. Run

```bash
python main.py
```

Results are printed as a table and saved to `output/announcements.json`.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | (required) | OpenAI API key |
| `LLM_MODEL` | `gpt-4o-mini` | Model for text extraction |
| `VISION_MODEL` | `gpt-4o` | Model for screenshot fallback |
| `HEADLESS` | `true` | Run browser headless |
| `MAX_RETRIES` | `3` | Max retry attempts |
| `PAGE_TIMEOUT_MS` | `60000` | Page load timeout (ms) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Project Structure

```
sebi_agent_scraper/
├── main.py                    # CLI entrypoint
├── graph.py                   # LangGraph workflow
├── config.py                  # Environment-based config
├── tools/
│   ├── browser.py             # Playwright page loader
│   ├── network_inspector.py   # XHR / API detection
│   └── screenshot.py          # Vision fallback screenshots
├── agents/
│   ├── extractor_agent.py     # LLM-powered extraction
│   └── validator_agent.py     # Validation & dedup
├── models/
│   └── schema.py              # Pydantic models
├── tests/
│   └── test_validator.py      # Validator unit tests
├── requirements.txt
├── .env.example
└── README.md
```

## Self-Healing Behaviour

The scraper adapts to failures automatically:

1. **Retry with refined prompt** — if LLM extraction returns 0 results
2. **Screenshot + Vision LLM** — if DOM extraction fails repeatedly
3. **API bypass** — if a backend JSON API is detected via network inspection

No hardcoded CSS selectors or XPaths are used.

## Testing

```bash
python -m pytest tests/test_validator.py -v
```

## Output Format

### Console

```
No.   Issue Date     Conf.   Title
---------------------------------------------------------------------------
1     2026-02-25     0.95    Ease of Doing Investment (EoDI)...
2     2026-02-20     0.92    Valuation of physical Gold and Silver...
```

### JSON (`output/announcements.json`)

```json
[
  {
    "title": "Ease of Doing Investment...",
    "issue_date": "2026-02-25",
    "confidence": 0.95
  }
]
```
# Agentic_AI_Tejomaya

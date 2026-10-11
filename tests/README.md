# Testing and Dev Guide

Contributor-focused instructions for local development, testing, and runtime operations.

## Dev Quick Start

```bash
# Create .venv and install dependencies (Python 3.10+, Node.js 18+)
npm run setup

# Run all example events (dev harness — no chain interaction)
npm run forecast

# Run a specific event (dev harness)
npm run forecast -- --event fed
```

## Validator Loop Notes

`scripts/run_validator.py` (`npm run validator`) is the production entrypoint. Once per hour it:

1. Syncs metagraph data for the configured subnet.
2. Optionally scores miners under the Almanac Market mechanism.
3. Optionally scores miners under the Almanac Forecasting mechanism.
4. Blends the two score vectors and emits one `set_weights` call.

Key toggles in `src/core/constants.py`:

- `VALIDATOR_LOOP.loop_enabled`
- `VALIDATOR_LOOP.market_enabled`
- `VALIDATOR_LOOP.forecasting_enabled`
- `VALIDATOR_LOOP.market_weight_share`
- `VALIDATOR_LOOP.forecasting_weight_share`

## Testing

Install dev dependencies (includes pytest), then run from repo root:

```bash
npm run setup
npm test
```

### Offline runs (default)

No API keys required. Tests that call real providers are skipped unless you opt in.

### Live / network tests

Pass `--live` and set relevant API keys (for example `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`).
See `.env.example`. Pytest loads repo-root `.env` at startup; shell exports still take precedence.

```bash
npm run test:live
npm run test:live -- tests/gateway/test_provider_live_openrouter.py
```

If a live test is skipped at runtime, it is usually missing an API key. Show skip reasons with:

```bash
pytest -rs
```

### Filter by provider id

Only runs tests tagged for that provider (`@pytest.mark.provider`), case-insensitive.

```bash
pytest --provider openrouter
pytest --provider anthropic
pytest --provider polymarket
```

`--live` + `--provider` runs all tests in that provider slice (golden + mock + live).

When you only want the network smoke tests, use `--live-only`:

```bash
pytest --live-only --provider openrouter --pretty-print -s
pytest --live-only --provider anthropic --pretty-print -s
```

Use built-in pytest substring filtering when needed:

```bash
pytest -k openrouter
```

Project-specific flags (`--provider`, `--live`, `--live-only`, `--pretty-print`) are defined in `tests/conftest.py`.

### Pretty-print raw responses

Pytest shows stdout only with `-s`. With `--pretty-print`, provider tests emit indented JSON for raw payloads.

Examples:

```bash
# Live API shape only
pytest --live-only --provider openrouter --pretty-print -s
pytest --live-only --provider anthropic --pretty-print -s

# Full provider slice (golden + mock + live)
pytest --live --provider openrouter --pretty-print -s

# Mock adapter only
pytest --provider polymarket --pretty-print -s

# Golden fixtures in offline mode
pytest --provider openrouter --pretty-print -s
```

Copy refreshed output to `tests/fixtures/raw/<provider>/<call_type>.json` (trim secrets). Provenance notes are in `tests/fixtures/raw/README.md`.

## Architecture (Developer View)

Three actors cooperate in each prediction cycle:

- **Validator**: receives events, manages agent execution, proxies data access through gateway, assembles reasoning traces, and submits to orchestrator API.
- **Agent**: a Python function that accepts an event, calls data providers (via the gateway), executes reasoning, and returns a probability prediction.
- **Provider Gateway**: logs/hashes upstream calls and performs independent evidence extraction.

## Writing a New Agent

Implement `BaseAgent` and define `predict()`:

```python
from src.agent.base import BaseAgent
from src.agent.context import ForecastingContext
from src.core.schemas import PredictionOutput, ReasoningStepType

class MyAgent(BaseAgent):
    agent_id = UUID("...")
    agent_version = "0.1.0"

    def predict(self, ctx: ForecastingContext) -> PredictionOutput:
        data = ctx.call_provider("polymarket", "get_market", {"market_slug": "..."})
        ctx.record_reasoning_step(
            step_type=ReasoningStepType.EVIDENCE_GATHERING,
            reasoning_text="...",
            input_evidence_refs=[0],
        )
        return PredictionOutput(
            final_probability=0.65,
            reasoning_summary="...",
            key_drivers=["..."],
            key_uncertainties=["..."],
        )
```

## Adding a New Provider

Implement `BaseProvider`:

```python
from src.gateway.providers.base import BaseProvider
from src.core.schemas import ProviderTier

class MyProvider(BaseProvider):
    provider_id = "my_source"
    provider_tier = ProviderTier.SEARCH

    def call(self, call_type: str, params: dict) -> dict:
        # fetch and return raw data
        ...
```

Then register provider wiring and extraction rules.

## Agent Execution + Bittensor Signing

Agents run in-process in the validator. There is no sandbox: agent code shares
the validator's memory, filesystem, network, and loaded hotkey. The only limit
is the wall-clock timeout (`VALIDATOR.sandbox_timeout_seconds`).

Provider calls are signed with the validator hotkey by the validator-local
signing proxy (`src/gateway/local_proxy.py`), which also attaches the billed
miner hotkey and records the call log for the trace.

Ad-hoc run with validator flags:

```bash
npm run validator -- \
  --netuid 172 \
  --wallet.name st-vali \
  --wallet.hotkey st-vali-hot \
  --subtensor.network test \
  --logging.debug
```

PM2:

```bash
pm2 start npm --name almanac-validator -- run validator -- --netuid 172 --wallet.name st-vali --wallet.hotkey st-vali-hot --subtensor.network test --logging.debug
```

For a local gateway, start it with `npm run gateway` and set
`GATEWAY_SERVICE_URL=http://localhost:8077`.

Notes:

- Use `--unsafe-no-signing` only for local contributor workflows.
- `npm run forecast -- --direct` calls the gateway directly, bypassing the
  signing proxy (local gateways only).

## Current Stubbed Areas

- Provider adapters may return mock data.
- Evidence extraction is currently rule-based.
- Storage defaults to JSON files.
- Central gateway signature enforcement and metagraph checks are staged.

## Project Structure

```
├── core/              Shared types, schemas, config
│   ├── schemas.py     Pydantic models for the Evidence Digest
│   ├── config.py      Configuration management
│   └── events.py      Event data structures
├── validator/         Validator orchestration
│   ├── orchestrator.py    Main execution loop
│   ├── sandbox.py         In-process agent execution (timeout + result validation)
│   └── trace_assembler.py Merges gateway evidence + agent reasoning
├── gateway/           Provider Gateway
│   ├── gateway.py     Core proxy — intercepts, logs, hashes, extracts
│   ├── extractor.py   Evidence extraction pipeline
│   └── providers/     Provider adapters
│       ├── base.py        Abstract base provider
│       ├── polymarket.py  Polymarket (mock)
│       └── web_search.py  Web search (mock)
├── agent/             Agent framework
│   ├── base.py        Abstract base agent
│   ├── context.py     ForecastingContext (agent SDK)
│   └── examples/
│       └── simple_agent.py
└── storage/           Persistence layer
    ├── store.py       Abstract storage interface
    └── json_store.py  JSON file implementation
```

## Evidence Digest Schema

Every trace is a sealed `EvidenceDigest` containing:

| Component | Source | Description |
|---|---|---|
| `execution_context` | Validator | IDs, timestamps, execution info |
| `event_snapshot` | System | Frozen copy of the event at execution time |
| `provider_calls` | Gateway | Every external data call with extracted evidence |
| `reasoning_chain` | Agent | Step-by-step reasoning with intermediate probabilities |
| `prediction_output` | Agent | Final probability, drivers, uncertainties |
| `resolution_record` | System | Post-hoc outcome (populated later) |
| `trace_integrity` | Validator | SHA-256 hash, schema version, cost totals |

The separation between gateway-produced evidence and agent-produced reasoning is enforced at the architecture level.
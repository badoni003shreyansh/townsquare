# Examples

Runnable scripts that show one feature each. They import townsquare modules directly — no HTTP calls, no Docker exec. Think of them as reference implementations for specific workflows.

## Available scripts

| Script                                  | What it does |
| --------------------------------------- | ------------ |
| _(empty — first contributor adds here)_ |              |

<!-- When adding: script name, one-line description. Update this table. -->

## How to run

First: get townsquare running. The full setup is in [docs/SELF_HOSTING.md](../docs/SELF_HOSTING.md). Quick version:

```bash
git clone https://github.com/townsquare-os/townsquare
cd townsquare
cp example.env .env
make gen-secrets         # paste into .env
# fill GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, WORKSPACE_DOMAIN, ANTHROPIC_API_KEY
make up
```

Install Python dependencies locally (examples need them):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[google,all]"
```

Run any example:

```bash
source .venv/bin/activate
python examples/<script>.py
```

Each script reads `.env` from the repo root. Some need extra connectors (`SLACK_CLIENT_ID`, GitHub PAT) — check the script's header comment for specifics.

## What makes a good example

- Demonstrates **one** workflow (federated query, connector usage, agent invocation, wiki/CRM operations, user management).
- Imports from `townsquare.*` — shows how to use the library programmatically.
- Inline comments explaining key decisions and API patterns.
- Graceful error handling with helpful messages.
- Header comment listing required `.env` variables beyond the defaults.

When you add a script, update the table above.

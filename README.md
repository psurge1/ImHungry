# ImHungry - Milestone 1

This milestone is a minimal AI dietitian built with Python 3.12, Strands Agents, and Amazon Bedrock. The four nutrition tools are local functions, and food entries live only in memory until the process exits.

## Setup

```bash
uv sync
```

Configure AWS credentials with access to Amazon Bedrock and set a region. The model defaults to `global.anthropic.claude-sonnet-4-6`; override it with `STRANDS_MODEL_ID` if needed.

`log_food` intentionally requires calories plus all three macro values. If a user only knows some of them, the agent should ask for the missing values instead of pretending that unknown macros are zero or estimated.

The project declares the optional botocore CRT support required by AWS login profiles, so `uv sync` installs it automatically.

```bash
export AWS_REGION=us-west-2
uv run pytest
uv run imhungry
```

The CLI keeps one Strands `Agent` instance alive, so a logged meal can inform a later recommendation in the same conversation. For a one-shot request:

```bash
uv run imhungry --message "What should I eat for dinner?"
```

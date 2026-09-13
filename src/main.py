"""Command-line interface for the ImHungry dietitian."""

from __future__ import annotations

import argparse

from agent import create_dietitian_agent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chat with the ImHungry AI dietitian.")
    parser.add_argument(
        "--message",
        help="Send one message and exit instead of opening the interactive chat.",
    )
    return parser.parse_args()


def main() -> None:
    """Run a conversational CLI backed by one stateful Strands agent."""

    args = _parse_args()
    print("ImHungry dietitian (type 'quit' or 'exit' to stop)")
    try:
        agent = create_dietitian_agent()
    except Exception as exc:  # pragma: no cover - depends on live AWS configuration
        print(f"Unable to initialize the Bedrock agent: {exc}")
        print("Check AWS credentials, Bedrock model access, and AWS_REGION, then try again.")
        return

    if args.message:
        print(f"You: {args.message}")
        try:
            print(f"Dietitian: {agent(args.message)}")
        except Exception as exc:  # pragma: no cover - depends on live AWS configuration
            print(f"Unable to reach the Bedrock agent: {exc}")
        return

    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if message.lower() in {"quit", "exit"}:
            break
        if not message:
            continue

        try:
            print(f"Dietitian: {agent(message)}")
        except Exception as exc:  # pragma: no cover - depends on live AWS configuration
            print(f"Unable to reach the Bedrock agent: {exc}")


if __name__ == "__main__":
    main()

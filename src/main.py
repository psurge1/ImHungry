"""Local CLI with explicit offline-demo or Bedrock mode and ephemeral data."""

import argparse
from functools import partial

from strands.storage import InMemoryStorage

from agent import create_dietitian_agent, _configured_model
from imhungry.conversations import ConversationService
from imhungry.demo import DemoModel
from imhungry.errors import AppError
from imhungry.providers import run_async, BedrockNutritionProvider
from imhungry.repository import MemoryRepository
from imhungry.services import NutritionService


def main():
    parser = argparse.ArgumentParser(description="ImHungry local CLI; data is discarded on exit.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true", help="Offline scripted model; no AWS access")
    mode.add_argument("--local", action="store_true", help="Real Bedrock model with ephemeral local data; requires existing AWS access")
    parser.add_argument("--message", help="Send one message and exit")
    args = parser.parse_args()
    services = NutritionService(MemoryRepository(), provider=None if args.demo else BedrockNutritionProvider(_configured_model))
    factory = partial(create_dietitian_agent, model=DemoModel()) if args.demo else create_dietitian_agent
    conversation = ConversationService(services, InMemoryStorage(), factory)
    user = "local-cli"
    item = conversation.create(user, {}, "local-session")
    print("ImHungry offline scripted demo" if args.demo else "ImHungry local Bedrock chat (data discarded on exit)")
    request_number = 0
    while True:
        try:
            message = args.message if args.message else input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if message.lower() in {"quit", "exit"}:
            break
        if not message:
            continue
        request_number += 1
        try:
            result = run_async(lambda: conversation.invoke(user, item["conversation_id"], message, str(request_number)))
            print("Dietitian:", result["response"])
        except AppError as error:
            print(error.message)
            return 1
        if args.message:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

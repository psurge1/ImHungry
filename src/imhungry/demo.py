"""Deterministic offline model for smoke tests, not real AI."""

import json
from strands.models.model import Model


class DemoModel(Model):
    def update_config(self, **kwargs):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("Offline demo does not estimate foods")
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        content = messages[-1]["content"]
        if any("toolResult" in block for block in content):
            block = next(b["toolResult"] for b in content if "toolResult" in b)
            result = block["content"][0]
            value = result.get("json") or json.loads(result.get("text", "{}"))
            if "error" in value:
                text = "The operation failed: " + value["error"]["message"]
            elif "nutrition" in value and "profile" in value:
                energy = value["nutrition"]["totals"]["energy_kcal"]
                text = f"You have logged {energy:g} kcal today. A rice bowl with beans and vegetables is one practical dinner option; adjust the portion to hunger. No target is assumed when none is saved."
            elif "entry_id" in value:
                text = "Saved your reported food and its nutrition values."
            else:
                text = "I retrieved your saved nutrition context."
            call = None
        else:
            message = " ".join(b.get("text", "") for b in content).casefold()
            if "log demo yogurt" in message:
                day = kwargs.get("invocation_state", {}).get("local_date", "2026-09-14")
                call = ("log_food", {"entry": {"consumed_at": day + "T12:00:00Z", "food": {"display_name": "Demo yogurt", "quantity": 1, "unit": "cup", "serving_description": "one cup"},
                    "nutrition": {"energy_kcal": 150, "protein_g": 20, "carbs_g": 10, "fat_g": 3}, "source": {"type": "user_provided"}}})
            elif "dinner" in message:
                day = kwargs.get("invocation_state", {}).get("local_date", "2026-09-14")
                call = ("get_meal_decision_context", {"local_date": day})
            else:
                call, text = None, "Hello! This is the offline scripted demo. Try 'log demo yogurt' or 'what should I eat for dinner?'."
        yield {"messageStart": {"role": "assistant"}}
        if call:
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"toolUseId": "demo-" + str(len(messages)), "name": call[0]}}}}
            yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": json.dumps(call[1])}}}}
        else:
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
            yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": text}}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "tool_use" if call else "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20}, "metrics": {"latencyMs": 1}}}

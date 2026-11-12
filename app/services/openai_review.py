"""One bounded OpenAI Responses call for a document review packet."""
import asyncio
import json
import os

import httpx
from pydantic import ValidationError

from app.services.review_drafts import INSTRUCTIONS, MAX_RESULT_BYTES, ReviewError, ReviewResult, output_schema

MODEL = "gpt-6.1-terra"
MAX_INPUT_BYTES = 1_500_000
MAX_INPUT_TOKENS = 240_000
MAX_OUTPUT_TOKENS = 12_000
MAX_COST_MICRODOLLARS = 1_000_000


def estimated_microdollars(input_tokens, output_tokens):
    # GPT-6.1 Terra standard rates below the 272K long-context tier.
    return input_tokens + 5 * output_tokens


async def _request(client, endpoint, payload):
    try:
        response = await client.post(endpoint, json=payload)
    except httpx.RequestError:
        raise ReviewError("OpenAI did not respond. Retry from Documents if you want to start a new review.") from None
    if response.status_code in {401, 403}:
        raise ReviewError("OpenAI review needs a valid project key with Responses API access.")
    if response.status_code in {402, 429}:
        raise ReviewError("OpenAI credits or rate limits blocked the review. Check the linked API project before retrying.")
    if not response.is_success:
        raise ReviewError("OpenAI could not process this review. The saved analysis is preserved.")
    try:
        data = response.json()
    except ValueError:
        raise ReviewError("OpenAI returned an unreadable response.") from None
    if not isinstance(data, dict):
        raise ReviewError("OpenAI returned an unreadable response.")
    return data


async def review_with_credits(packet):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise ReviewError("Set the OpenAI API project key to use automatic review.")
    source = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    if len(source.encode()) > MAX_INPUT_BYTES:
        raise ReviewError("This source package exceeds the automatic review size limit. Use Review with Codex from Documents.")
    common = {
        "model": MODEL, "instructions": INSTRUCTIONS, "input": source,
        "text": {"format": {"type": "json_schema", "name": "deal_review", "strict": True, "schema": output_schema()}},
    }
    try:
        async with asyncio.timeout(170):
            async with httpx.AsyncClient(base_url="https://api.openai.com/v1/",
                                         headers={"Authorization": f"Bearer {key}"}, timeout=150) as client:
                counted = await _request(client, "responses/input_tokens", common)
                tokens = counted.get("input_tokens")
                if type(tokens) is not int or tokens <= 0:
                    raise ReviewError("OpenAI could not confirm the input size. No review was started.")
                if tokens > MAX_INPUT_TOKENS or estimated_microdollars(tokens, MAX_OUTPUT_TOKENS) > MAX_COST_MICRODOLLARS:
                    raise ReviewError("This source package exceeds the automatic review budget. Use Review with Codex from Documents.")
                data = await _request(client, "responses", {
                    **common, "max_output_tokens": MAX_OUTPUT_TOKENS,
                    "reasoning": {"effort": "low"}, "service_tier": "default", "store": False,
                })
    except TimeoutError:
        raise ReviewError("OpenAI review timed out. Retry from Documents if you want to start a new review.") from None
    if data.get("status") != "completed":
        raise ReviewError("OpenAI returned an incomplete review. Use Review with Codex for this package.")
    outputs = [
        item["text"] for output in data.get("output") or [] if output.get("type") == "message"
        for item in output.get("content") or [] if item.get("type") == "output_text" and isinstance(item.get("text"), str)
    ]
    if len(outputs) != 1 or len(outputs[0].encode()) > MAX_RESULT_BYTES:
        raise ReviewError("OpenAI did not return an importable review.")
    try:
        result = ReviewResult.model_validate_json(outputs[0])
    except ValidationError:
        raise ReviewError("OpenAI returned an invalid review. No values were saved.") from None
    usage = data.get("usage") or {}
    used_input, used_output = usage.get("input_tokens"), usage.get("output_tokens")
    cost = None
    if type(used_input) is int and type(used_output) is int:
        cost = estimated_microdollars(used_input, used_output) / 1_000_000
    return result, {"model": MODEL, "estimated_cost_usd": cost}
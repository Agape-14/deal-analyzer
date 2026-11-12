"""One bounded OpenAI Responses call for a document review packet."""
import asyncio
import json
import os

import httpx
from pydantic import ValidationError

from app.services.review_drafts import INSTRUCTIONS, MAX_RESULT_BYTES, ReviewError, ReviewResult, output_schema

MODEL = "gpt-6-astra"
REASONING_EFFORT = "xhigh"
DEFAULT_BUDGET_USD = 10
MAX_INPUT_BYTES = 6_000_000
CONTEXT_WINDOW = 1_050_000
LONG_CONTEXT_THRESHOLD = 272_000
MIN_OUTPUT_TOKENS = 32_000
MAX_OUTPUT_TOKENS = 64_000
TOKEN_COUNT_BUFFER = 512


def token_rates(input_tokens):
    # GPT-6 Astra standard rates in microdollars per token. The long-context
    # tier prices the entire request, including reasoning and visible output.
    return (20, 75) if input_tokens > LONG_CONTEXT_THRESHOLD else (10, 50)


def estimated_microdollars(input_tokens, output_tokens):
    input_rate, output_rate = token_rates(input_tokens)
    return input_tokens * input_rate + output_tokens * output_rate


def review_budget_usd():
    try:
        budget = int(os.getenv("DEAL_REVIEW_MAX_USD", str(DEFAULT_BUDGET_USD)))
    except ValueError:
        budget = 0
    if budget <= 0:
        raise ReviewError("Set DEAL_REVIEW_MAX_USD to a positive whole dollar amount or use Review with Codex.")
    return budget


def output_allowance(counted_tokens, budget_usd):
    input_tokens = counted_tokens + TOKEN_COUNT_BUFFER
    input_rate, output_rate = token_rates(input_tokens)
    remaining_microdollars = budget_usd * 1_000_000 - input_tokens * input_rate
    return min(MAX_OUTPUT_TOKENS, CONTEXT_WINDOW - input_tokens, remaining_microdollars // output_rate)


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
    budget_usd = review_budget_usd()
    source = json.dumps(packet, ensure_ascii=False, separators=(",", ":"))
    if len(source.encode()) > MAX_INPUT_BYTES:
        raise ReviewError("This source package exceeds the automatic review size limit. Use Review with Codex from Documents.")
    common = {
        "model": MODEL, "instructions": INSTRUCTIONS, "input": source,
        "text": {"format": {"type": "json_schema", "name": "deal_review", "strict": True, "schema": output_schema()}},
    }
    try:
        async with asyncio.timeout(720):
            async with httpx.AsyncClient(base_url="https://api.openai.com/v1/",
                                         headers={"Authorization": f"Bearer {key}"},
                                         timeout=httpx.Timeout(700, connect=15)) as client:
                counted = await _request(client, "responses/input_tokens", common)
                tokens = counted.get("input_tokens")
                if type(tokens) is not int or tokens <= 0:
                    raise ReviewError("OpenAI could not confirm the input size. No review was started.")
                if tokens + TOKEN_COUNT_BUFFER + MIN_OUTPUT_TOKENS > CONTEXT_WINDOW:
                    raise ReviewError("This source package exceeds Astra's context window. Use Review with Codex to inspect it in parts.")
                allowance = output_allowance(tokens, budget_usd)
                if allowance < MIN_OUTPUT_TOKENS:
                    raise ReviewError(
                        f"This package needs more room for Astra to review it within the ${budget_usd} limit. "
                        "Use Review with Codex, or raise the API budget for this package."
                    )
                data = await _request(client, "responses", {
                    **common, "max_output_tokens": allowance, "truncation": "disabled",
                    "reasoning": {"effort": REASONING_EFFORT}, "service_tier": "default", "store": False,
                })
    except TimeoutError:
        raise ReviewError("OpenAI review timed out. Retry from Documents if you want to start a new review.") from None
    if data.get("status") == "incomplete" and (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens":
        raise ReviewError("Astra reached the response limit before finishing. Use Review with Codex for a complete review.")
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
    return result, {"model": MODEL, "reasoning_effort": REASONING_EFFORT, "budget_usd": budget_usd, "estimated_cost_usd": cost}
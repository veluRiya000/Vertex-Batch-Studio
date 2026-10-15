"""Verified text Batch routes and conservative prices before promotional credits."""
PROFILES = {
    "gemini-4-argon": {"label": "Gemini 4 Argon", "input_limit": 1048576, "output_limit": 1048576,
                        "shared_context": True, "rates": (2.0, 10.0),
                        "source": "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-argon"},
    "gemini-3.8-flash": {"label": "Gemini 3.8 Flash", "input_limit": 1048576, "output_limit": 65536,
                         "shared_context": False, "rates": (.75, 3.75),
                         "source": "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash"},
    "gemini-3.1-pro-preview": {"label": "Gemini 3.1 Pro Preview", "input_limit": 1048576, "output_limit": 65536,
                               "shared_context": False, "rates": (1.0, 6.0), "long_rates": (2.0, 9.0),
                               "source": "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-pro"},
}


def profile(model):
    try:
        return PROFILES[model]
    except KeyError:
        raise ValueError("Harness 不支持此 Batch 模型") from None


def price_snapshot(model):
    value = profile(model)
    return {"base": list(value["rates"]), "long": list(value.get("long_rates", value["rates"])),
            "long_input_threshold": 200000, "cache_ratio": .05 if model == "gemini-4-argon" else .1 if model == "gemini-3.8-flash" else 1,
            "basis": "global Batch before promotional/account credits; cache usage priced separately", "verified": "2026-10-15",
            "source": "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"}


def estimate_cost(tokens, output, snapshot):
    input_rate, output_rate = snapshot["long" if tokens > snapshot["long_input_threshold"] else "base"]
    return (tokens * input_rate + output * output_rate) / 1000000


def usage_cost(usage, snapshot, model, created_at):
    """Price returned usage, not the requested output cap or a Billing invoice.

    Historical snapshots retain their gross rates. Cache discounts apply only
    to cache tokens reported by Google. Promotional credits are shown separately
    and never deducted from the conservative submission budget.
    """
    if not isinstance(usage, dict) or usage.get("promptTokenCount") is None:
        return None
    names = ("promptTokenCount", "cachedContentTokenCount", "candidatesTokenCount",
             "thoughtsTokenCount", "toolUsePromptTokenCount")
    # GCS inferred result schemas can pad optional zero counters with null.
    counts = {key: 0 if usage.get(key) is None else usage[key] for key in names}
    if any(type(n) is not int or n < 0 for n in counts.values()):
        raise ValueError("云端用量字段无效，需要核对原始结果")
    prompt, cached, candidates, thoughts, tool_input = (counts[key] for key in names)
    if cached > prompt:
        raise ValueError("云端缓存用量大于输入用量，需要核对原始结果")
    input_rate, output_rate = snapshot["long" if prompt > snapshot["long_input_threshold"] else "base"]
    # Pro Batch has no published cached-input discount; retain its input rate.
    cache_ratio = snapshot.get("cache_ratio", .05 if model == "gemini-4-argon" else .1 if model == "gemini-3.8-flash" else 1)
    gross = ((prompt-cached+tool_input)*input_rate + cached*input_rate*cache_ratio + (candidates+thoughts)*output_rate) / 1000000
    expiry = "2026-11-30" if model == "gemini-4-argon" else "2026-12-31" if model == "gemini-3.8-flash" else None
    promotional = gross*.5 if expiry and created_at[:10] <= expiry else gross
    return {"estimated_usd": gross, "promotional_estimated_usd": promotional,
            "basis": "returned usage, global Batch, before promotional/account credits",
            "usage_counts": counts, "cached_input_rate": input_rate*cache_ratio,
            "input_rate": input_rate, "output_rate": output_rate}

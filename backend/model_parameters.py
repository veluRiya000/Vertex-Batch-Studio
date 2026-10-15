"""Documented model parameter restrictions, including offline compatibility.

Catalogue discovery remains dynamic. This narrow protocol rule also applies
when a cache predates capability metadata or the public catalogue is offline.
Source: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/nano-banana-2-1
"""
PARAMETER_NAMES = {
    "temperature": "temperature", "topp": "topP", "topk": "topK",
    "seed": "seed", "logprobs": "logprobs", "responselogprobs": "responseLogprobs",
}
NANO_BANANA_21_UNSUPPORTED = frozenset({"temperature", "topP", "topK", "seed", "logprobs"})


def parameter_name(value: str) -> str:
    return PARAMETER_NAMES.get(value.replace("_", "").lower(), value)


def unsupported_generation_parameters(model: str, capabilities: dict | None = None) -> frozenset[str]:
    # Accept the bare ID and publisher/project resource forms without applying
    # restrictions to an unrelated model merely containing a similar name.
    model_id = model.rsplit("/", 1)[-1].split("@", 1)[0]
    blocked = set(NANO_BANANA_21_UNSUPPORTED) if model_id == "gemini-nano-banana-2.1" else set()
    if capabilities:
        blocked.update(parameter_name(name) for name in capabilities.get("unsupported_parameters", []))
    if "logprobs" in blocked:
        # This toggle enables the same unsupported log-probability output.
        blocked.add("responseLogprobs")
    return frozenset(blocked)


def filter_generation_parameters(model: str, config: dict, capabilities: dict | None = None) -> dict:
    blocked = unsupported_generation_parameters(model, capabilities)
    return {key: value for key, value in config.items() if parameter_name(key) not in blocked}


def restricted_manifest_parameters(manifest: dict, capabilities: dict | None = None) -> set[str]:
    blocked = unsupported_generation_parameters(manifest["model"], capabilities)
    return {parameter_name(key) for row in manifest["requests"]
            for key in row["request"].get("generationConfig", {})
            if parameter_name(key) in blocked}

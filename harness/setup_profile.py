"""Build a relocatable profile overlay without editing the upstream checkout."""
from pathlib import Path
import json
import re


def generate(root: Path, output: Path | None = None):
    def bundle_file(bundle):
        source = root / "upstream/packages/bundle" / bundle / "cordis.patch.yml"
        if source.is_file():
            return source
        return root / "upstream/node_modules/@deepseek-ai" / ("dsh-" + bundle) / "cordis.patch.yml"
    rows = "\n".join(bundle_file(bundle).read_text(encoding="utf-8") for bundle in ("base", "web-app"))
    for bundle in ("web-app",):
        for preset in sorted((bundle_file(bundle).parent / "presets").glob("*.patch.yml")):
            rows += "\n" + preset.read_text(encoding="utf-8")
    ids = set(re.findall(r"^\s*- id: ([\w-]+)", rows, re.MULTILINE))
    disabled = {"llm-deepseek", "llm-deepseek-account", "llm-pi-ai", "session-title-llm", "session-log-deepseek",
                "tool-plugin-manager", "tool-subagent", "tool-subagent-fork", "tool-subagent-control", "tool-subagent-list-agents",
                "ui-subagent", "ui-settings-subagent", "tool-web", "ui-sidebar-browser",
                "ui-settings-account", "ui-settings-session-log", "web-search-deepseek",
                "plugin-package-inventory-deepseek", "deepseek-llm-api-extensions",
                "deepseek-account", "account-controller", "subagent", "subagent-spawn-in-process",
                "subagent-fork-in-process", "subagent-model-selection-settings",
                "workflow-ptc", "tool-workflow", "ptc-runtime", "ui-workflow-run",
                "office-to-pdf", "web", "web-fetch-http", "ui-settings-web-search", "preset-ptc", "preset-cordis", "preset-minimal", "schedule", "ui-schedule", "tool-schedule"}
    disabled.update(i for i in ids if "telemetry" in i or "product-analytics" in i)
    patch = [{"id": i, "disabled": True} for i in sorted(disabled & ids)]
    # Presets carry their own plugin trees; an outer disable cannot remove them.
    # Replace the standard preset with a single-agent, local-tools-only tree.
    tools = ["persona", "agent-instructions", "time-context", "tool-fs", "tool-fs-search",
             "skill-filesystem", "tool-skill", "tool-ask-user", "tool-todo", "tool-present"]
    plugins = [{"id": name, "name": "@deepseek-ai/dsh-" + name} for name in tools]
    configs = {"persona":{"prefix":"You are a coding agent powered by the {{model}} model."},
               "agent-instructions":{"maxBytes":65536},
               "tool-fs-search":{"sampleOverCapGlobResults":False},
               "tool-todo":{"allowParallelInProgress":True}}
    for plugin in plugins:
        if plugin["id"] in configs:
            plugin["config"] = configs[plugin["id"]]
    # Keep session-scoped planning, independently of removed delegation presets.
    plugins.append({"id":"planning", "name":"cordis:group", "group":True,
                    "isolate":{"planMode":True}, "config":[
                        {"id":"plan-mode", "name":"@deepseek-ai/dsh-plan-mode", "config":{
                            "section":"In plan mode, inspect without modifying files. Present the complete plan through exit_plan_mode and wait for explicit approval before executing changes. Do not run edits, commands with side effects, or implementation tools while the plan is pending."}}]})
    plugins += [{"id":"tool-pwsh", "name":"@deepseek-ai/dsh-tool-pwsh"},
                {"id":"command-goal", "name":"@deepseek-ai/dsh-command-goal"},
                {"id":"tool-goal", "name":"@deepseek-ai/dsh-tool-goal"},
                {"id":"compaction", "name":"cordis:group", "group":True,
                 "isolate":{"compaction":True, "toolResultPruner":True}, "config":[
                    {"id":"compaction-basic", "name":"@deepseek-ai/dsh-compaction-basic"},
                    {"id":"command-compact", "name":"@deepseek-ai/dsh-command-compact"},
                    {"id":"tool-result-pruner", "name":"@deepseek-ai/dsh-compaction-tool-result-pruner",
                     "config":{"thresholdChars":8192,"headChars":4096,"tailChars":1024}}]}]
    patch.append({"id":"preset-standard", "config":{"id":"standard", "order":1, "plugins":plugins}})
    patch += [{"id":"agent-default-model", "config":{"provider":"vertex-batch", "model":"gemini-4-argon", "reasoningEffort":"medium"}},
              {"id":"sandbox-policy", "config":{"mode":"workspace-write"}},
              {"insert":[{"id":"vertex-batch", "name":str(root / "plugins/vertex-batch/index.mjs").replace("\\","/")},
                         {"id":"studio-theme", "name":str(root / "plugins/studio-theme/index.mjs").replace("\\","/")}]}]
    # Keep the first-use workspace inside this application's data directory.
    # The expression is evaluated by the official profile loader at startup.
    patch.append({"id":"workspace-controller", "config":{"documentsDirectory":"__WORKSPACE_DIRECTORY__"}})
    encoded=json.dumps(patch, indent=2, ensure_ascii=False)
    encoded=encoded.replace('"__WORKSPACE_DIRECTORY__"', '!!js process.env.VBS_HARNESS_WORKSPACE_PARENT')
    target = output if output is not None else root / "studio.patch.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(encoded,encoding="utf-8")
    return target


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent)
    print("Harness profile generated.")

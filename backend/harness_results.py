"""Strict result association with documented Batch JSONL null padding."""
import json


def request_matches(expected, actual, path=()):
    # GCS infers one record shape across repeated records. A list-valued field
    # present in one part can be materialized as [] in its siblings (e.g. the
    # present tool's args.files appears on preceding write calls). Only admit
    # such padding when the frozen request itself proves that exact schema path
    # is a repeated field. Never strip arbitrary empty arguments or reorder lists.
    repeated = set()

    def collect(value, shape):
        if isinstance(value, dict):
            for key, child in value.items():
                collect(child, shape + (key,))
        elif isinstance(value, list):
            repeated.add(shape)
            for child in value:
                collect(child, shape + (None,))

    collect(expected, path)

    def matches(left, right, shape):
        if isinstance(left, dict):
            if not isinstance(right, dict) or not left.keys() <= right.keys():
                return False
            for key in right.keys() - left.keys():
                if right[key] is None:
                    continue
                if right[key] == [] and shape + (key,) in repeated:
                    continue
                # An absent required list and [] have the same schema meaning.
                if key == "required" and right[key] == [] and any(
                    p in {"parameters", "parametersJsonSchema"} for p in shape
                ):
                    continue
                return False
            return all(matches(value, right[key], shape + (key,)) for key, value in left.items())
        if isinstance(left, list):
            return isinstance(right, list) and len(left) == len(right) and all(
                matches(l, r, shape + (None,)) for l, r in zip(left, right))
        if isinstance(left, bool) or isinstance(right, bool):
            return type(left) is type(right) and left == right
        return left == right

    return matches(expected, actual, path)


def response_from_row(row, request, *, allow_continuation=False):
    if not request_matches(request, row.get("request")):
        raise ValueError("Batch 输出无法关联到冻结的请求")
    status = row.get("status")
    if isinstance(status, str) and status:
        try:
            status = json.loads(status)
        except (ValueError, TypeError):
            pass
    if status and not (isinstance(status, dict) and status.get("code") == 0):
        message = status.get("message", "") if isinstance(status, dict) else str(status)
        code = status.get("canonicalCode", status.get("code")) if isinstance(status, dict) else None
        if "parameters_json_schema" in message or "parametersJsonSchema" in message:
            raise ValueError("云端拒绝工具参数格式（INVALID_ARGUMENT），请使用更新后的 Harness 再开始新任务")
        concise = message.split("\n", 1)[0].split("; RPC", 1)[0][:240]
        raise ValueError(f"云端请求失败（{code or 'ERROR'}）：{concise or '未提供错误详情'}")
    response = row.get("response")
    if not isinstance(response, dict) or not response.get("candidates"):
        raise ValueError("模型被拦截或没有返回候选结果")
    if allow_continuation and (not isinstance(response["candidates"], list) or len(response["candidates"]) != 1 or not isinstance(response["candidates"][0], dict)):
        raise ValueError("单行续传请求必须返回且只返回一个候选结果")
    reason = response["candidates"][0].get("finishReason")
    if reason not in ({"STOP", "MAX_TOKENS", "CONTINUATION"} if allow_continuation else {"STOP", "MAX_TOKENS"}):
        raise ValueError("模型输出未完整结束：" + str(reason))
    return response

"""Gemini native long-decode protocol. No extra prompt or real-time fallback.

Keep each hop's Part distinct, like google-genai merge_continuation_responses.
In particular, never splice function-call argument strings or strip signatures.
"""
from copy import deepcopy


def sum_usage(usages):
    result = {}
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        for key, number in usage.items():
            if key.endswith('TokenCount') and type(number) is int and number >= 0:
                result[key] = result.get(key, 0) + number
    return result


def generated_tokens(responses):
    usage = sum_usage(r.get('usageMetadata') for r in responses)
    return usage.get('candidatesTokenCount', 0) + usage.get('thoughtsTokenCount', 0)


def next_request(original, active, responses, model, input_tokens, limits_enabled):
    """Return an immutable native continuation input, or an explicit stop cause."""
    candidate = responses[-1]['candidates'][0]
    token = candidate.get('continuationToken')
    reason = candidate.get('finishReason')
    if model != 'gemini-4-argon' or not isinstance(token, str) or not token:
        return None, '云端未提供此模型可用的续传令牌；结果已保存，未执行未完成的工具调用。'
    if reason not in {'CONTINUATION', 'MAX_TOKENS'}:
        return None, '云端未返回可续传的结束状态。'
    if token == active.get('continuationToken') or any(
        token == r['candidates'][0].get('continuationToken') for r in responses[:-1]
    ):
        return None, '云端重复返回相同续传令牌；已停止重复提交，已收到的内容仍保留。'
    # A non-progressing response must not create an unbounded paid loop.
    usage = responses[-1].get('usageMetadata')
    if not isinstance(usage, dict) or any(usage.get(k) is not None and (type(usage[k]) is not int or usage[k] < 0)
                                          for k in ('candidatesTokenCount', 'thoughtsTokenCount')) or generated_tokens([responses[-1]]) <= 0:
        return None, '续传段没有可核对的新增生成用量；已停止并保留原始结果。'
    initial = (responses[0].get('usageMetadata') or {}).get('promptTokenCount', input_tokens)
    if type(initial) is not int or initial < 0:
        return None, '首段输入用量无效，无法核对模型总额度。'
    maximum = 1048576 - max(input_tokens, initial)
    generated = generated_tokens(responses)
    if generated >= maximum:
        return None, '已达到 Argon 输入、思考与输出合计的 1048576 Token 总额度，无法继续本轮。'
    configured = original.get('generationConfig', {}).get('maxOutputTokens', 65536)
    target = min(configured, maximum) if limits_enabled else maximum
    if generated >= target:
        return None, '已达到启用的本轮输出额度；需提高额度或关闭运行限额后开始新请求。已收到的内容仍保留。'
    # A provider MAX_TOKENS needs a larger cap, not just the same opaque token.
    old_cap = active.get('generationConfig', {}).get('maxOutputTokens', 32768)
    if reason == 'MAX_TOKENS' and target <= old_cap:
        return None, '云端已达到当前输出额度，无法在保持此额度时继续；结果已保存。'
    result = deepcopy(original)
    result.setdefault('generationConfig', {})['maxOutputTokens'] = target
    result['continuationToken'] = token
    return result, None


def merge_responses(responses):
    """Only complete STOP may become an actionable model turn."""
    if not responses or responses[-1]['candidates'][0].get('finishReason') != 'STOP':
        raise ValueError('续传尚未完整结束，不能交付部分结果')
    if responses[-1]['candidates'][0].get('continuationToken'):
        raise ValueError('云端 STOP 仍带有续传令牌，结束状态不一致')
    result = deepcopy(responses[-1])
    parts = []
    seen_ids = set()
    for response in responses:
        if len(response.get('candidates', [])) != 1:
            raise ValueError('续传候选数量异常，不能确定同一回答')
        content = response['candidates'][0].get('content', {})
        for part in content.get('parts', []):
            if not isinstance(part, dict):
                raise ValueError('续传内容格式无效')
            call = part.get('functionCall')
            if call:
                if call.get('partialArgs') or call.get('willContinue'):
                    raise ValueError('工具参数仍未完整结束，不能执行')
                identifier = call.get('id')
                if identifier and identifier in seen_ids:
                    raise ValueError('续传中出现重复工具调用编号，不能安全重复执行')
                if identifier:
                    seen_ids.add(identifier)
            # Empty text checkpoints are protocol placeholders, not UI blocks.
            if set(part) <= {'text', 'thought'} and part.get('text') == '':
                continue
            parts.append(deepcopy(part))
    candidate = result['candidates'][0]
    candidate.pop('continuationToken', None)
    candidate['content'] = {'role': 'model', 'parts': parts}
    result['usageMetadata'] = sum_usage(r.get('usageMetadata') for r in responses)
    initial = (responses[0].get('usageMetadata') or {}).get('promptTokenCount')
    if initial is not None:
        result['initialPromptTokenCount'] = initial
    return result

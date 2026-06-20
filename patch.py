import re

with open('horizon_scanner/thesis/thesis_loop.py', 'r', encoding='utf-8-sig') as f:
    content = f.read()

old_start = 'def _parse_json(text: str) -> dict:'
idx = content.index(old_start)
# find the end of the function (next 'def ' at column 0)
after = content[idx:]
next_def = after.index('\ndef ', 5)
end_idx = idx + next_def

new_func = '''def _parse_json(text: str) -> dict:
    \"\"\"Parse JSON from LLM output, tolerant of common malformations.\"\"\"
    import re
    text = text.strip()
    if text.startswith('\\\'):
        lines = text.split('\n')
        if lines[-1].strip() == '\\\':
            text = '\n'.join(lines[1:-1])
        else:
            text = '\n'.join(lines[1:])
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        start = text.index('{')
        end = text.rindex('}') + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        pass
    try:
        repaired = text[text.index('{'):text.rindex('}')+1]
        repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)
        return json.loads(repaired)
    except (ValueError, json.JSONDecodeError):
        pass
    logger.warning(f'Could not parse JSON, returning empty dict. First 200 chars: {text[:200]}')
    return {}
'''

content = content[:idx] + new_func + content[end_idx:]

with open('horizon_scanner/thesis/thesis_loop.py', 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
print('Patched')

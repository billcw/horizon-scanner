import io
lines = io.open('config.yaml', encoding='utf-8').read().splitlines()
inblock = False
for i, ln in enumerate(lines):
    if ln.startswith('monitoring:'):
        inblock = True
    elif inblock and ln and not ln.startswith((' ', '\t')):
        break
    if inblock:
        print(repr(ln))

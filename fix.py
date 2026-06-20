with open('run.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()

insert_at = None
for i, line in enumerate(lines):
    if 'p_seed = sub.add_parser' in line:
        insert_at = i
        break

if insert_at is not None:
    new_lines = [
        '    p_thesis = sub.add_parser("thesis", help="Run L3 thesis loop for a cluster")\n',
        '    p_thesis.add_argument("--cluster", required=True, help="Cluster UUID")\n',
        '\n',
    ]
    lines = lines[:insert_at] + new_lines + lines[insert_at:]
    with open('run.py', 'w', encoding='utf-8', newline='\n') as f:
        f.writelines(lines)
    print('Done')
else:
    print('FAILED - line not found')

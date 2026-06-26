import io
with io.open('horizon_scanner/dashboard/server.py','r',encoding='utf-8') as f:
    lines = f.readlines()
for i in range(439, 475):
    if i < len(lines):
        print(str(i+1) + ': ' + lines[i].rstrip())

with open('run.py', 'r', encoding='utf-8-sig') as f:
    content = f.read()

# Move the main() call to the very end
content = content.replace('main()\n', '')
content = content.rstrip() + '\n\nif __name__ == "__main__":\n    main()\n'

with open('run.py', 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
print('Done')

import yaml
cfg = yaml.safe_load(open('config.yaml', encoding='utf-8'))
print('monitoring section:', cfg.get('monitoring'))

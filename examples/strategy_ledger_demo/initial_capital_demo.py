from _support import create

manager, key = create()
print(manager.require_snapshot(key).capital)

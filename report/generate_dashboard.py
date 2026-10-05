"""Publish only derived public data, never secrets or email recipients."""
import json
from product import dataset, OUT


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = dataset()
    (OUT / 'data.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    (OUT / 'index.html').write_text((__import__('pathlib').Path(__file__).parent / 'dashboard.html').read_text(), encoding='utf-8')
    (OUT / '.nojekyll').touch()
    print('Dashboard generated.')


if __name__ == '__main__':
    main()

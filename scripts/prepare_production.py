"""Create fresh production secrets without printing them or reading the local .env."""
import argparse
import os
from pathlib import Path
import re
import secrets


def prepare(destination, domain='change-me.example', extension_id=''):
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', domain):
        raise ValueError('Use a hostname without a URL scheme, port or path.')
    if extension_id and not re.fullmatch(r'[a-p]{32}', extension_id):
        raise ValueError('Extension ID must contain exactly 32 letters a-p.')
    template = Path(__file__).resolve().parent.parent / '.env.production.example'
    text = template.read_text(encoding='utf-8')
    values = {'DOMAIN': domain, 'EXTENSION_ALLOWED_IDS': extension_id,
              'DJANGO_SECRET_KEY': secrets.token_urlsafe(64), 'DB_PASSWORD': secrets.token_urlsafe(36),
              'POSTGRES_ADMIN_PASSWORD': secrets.token_urlsafe(36)}
    text = '\n'.join(key + '=' + values[key] if '=' in line and (key := line.split('=', 1)[0]) in values else line
                     for line in text.splitlines()) + '\n'
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', default='change-me.example')
    parser.add_argument('--extension-id', default='')
    parser.add_argument('--output', type=Path, default=Path('.env.production'))
    args = parser.parse_args()
    try:
        prepare(args.output, args.domain, args.extension_id)
    except (OSError, ValueError) as error:
        parser.exit(1, 'Not created: file already exists, destination is unavailable, or arguments are invalid.\n')
    print('Created private production environment file. Set your domain, extension ID and optional AI key; secrets were not printed.')

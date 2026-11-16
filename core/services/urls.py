import re
from urllib.parse import urlsplit


def problem_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or parsed.hostname not in {'codeforces.com', 'www.codeforces.com'} or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return None
        if not re.fullmatch(r'/(?:problemset/problem/[0-9]+/[A-Za-z][A-Za-z0-9]*|(?:contest|gym)/[0-9]+/problem/[A-Za-z][A-Za-z0-9]*)/?', parsed.path):
            return None
        return 'https://codeforces.com' + parsed.path.rstrip('/')
    except (ValueError, TypeError):
        return None

"""Small allowlist renderer for existing website AI Markdown; no new dependency."""
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit
import markdown


class Cleaner(HTMLParser):
    allowed = {'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'pre', 'code', 'strong', 'em', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'a'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.allowed:
            return
        extra = ''
        if tag == 'a':
            href = dict(attrs).get('href', '')
            try:
                safe = urlsplit(href).scheme in {'http', 'https'} or (href.startswith('/') and not href.startswith('//'))
            except ValueError:
                safe = False
            if safe:
                extra = f' href="{escape(href, quote=True)}" rel="noopener noreferrer"'
        self.parts.append(f'<{tag}{extra}>')

    def handle_endtag(self, tag):
        if tag in self.allowed and tag not in {'br', 'hr'}:
            self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        self.parts.append(escape(data))


def safe_markdown(content):
    parser = Cleaner()
    parser.feed(markdown.markdown(content or '', extensions=['fenced_code', 'tables']))
    parser.close()
    return ''.join(parser.parts)

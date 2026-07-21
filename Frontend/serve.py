"""Local static server that mimics Vercel's cleanUrls: true behavior, so
/homepage resolves to homepage.html just like the real ukusap.com deployment.
Plain `python -m http.server` doesn't do this, so links without a .html
extension would 404 locally even though they work in production.

Usage: python serve.py [port]   (defaults to 5500)
"""
import http.server
import os
import sys


class CleanUrlHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        candidate = super().translate_path(path)
        if not os.path.exists(candidate) and '.' not in os.path.basename(candidate):
            html_candidate = candidate + '.html'
            if os.path.isfile(html_candidate):
                return html_candidate
        return candidate


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5500
    http.server.test(HandlerClass=CleanUrlHandler, port=port, bind='0.0.0.0')

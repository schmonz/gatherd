#!/usr/bin/env python3
"""A local stand-in for both halves of the AUR, for tests/check-aur-deps.

One server answers the RPC (`aur query` POSTs to $AUR_LOCATION/rpc/v5/info) and
cgit (.SRCINFO GETs), because gatherd-check-aur-deps talks to both and a test
about an outage has to be able to break either one independently.

The mode is read from a file on every request rather than taken at startup, so
one server covers every case in the suite and no test has to race a port.

Usage: stub-aur.py <statedir>
  <statedir>/stub-mode    one of the MODES below (default: healthy)
  <statedir>/stub-absent  a package name the RPC pretends not to know
  <statedir>/stub-port    written by this script once it is listening
"""
import http.server
import json
import os
import socketserver
import sys
import urllib.parse

STATE = sys.argv[1]

# healthy    the AUR answers everything, with no dependencies to violate
# rpc429     HTTP 429 from the RPC -- what a rate-limited burst gets
# rpchtml    HTTP 200 from the RPC carrying an HTML page, not JSON: a proxy,
#            a captive portal, or a rate limiter answering in aurweb's place
# rpcjson    HTTP 200 from the RPC carrying aurweb's own JSON error body
# cgit429    the RPC answers, cgit 429s
# cgit404    the RPC answers, cgit says the package does not exist


def state(name, default=''):
    try:
        with open(os.path.join(STATE, name)) as handle:
            return handle.read().strip()
    except OSError:
        return default


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def reply(self, status, ctype, body):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        mode = state('stub-mode', 'healthy')
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length).decode('utf-8', 'replace')
        if mode == 'rpc429':
            return self.reply(429, 'text/html', b'<html>429 Too Many Requests</html>')
        if mode == 'rpchtml':
            return self.reply(200, 'text/html',
                              b'<html><body>Too many requests, slow down.</body></html>')
        if mode == 'rpcjson':
            return self.reply(200, 'application/json', json.dumps(
                {'error': 'Rate limit reached', 'resultcount': 0, 'results': [],
                 'type': 'error', 'version': 5}).encode())
        absent = state('stub-absent')
        asked = urllib.parse.parse_qs(raw).get('arg[]', [])
        # LastModified is 1 so the .SRCINFO cache key can never collide with a
        # real one; the fetch below is then always exercised.
        results = [{'Name': name, 'PackageBase': name, 'LastModified': 1}
                   for name in asked if name != absent]
        self.reply(200, 'application/json', json.dumps(
            {'resultcount': len(results), 'results': results,
             'type': 'multiinfo', 'version': 5}).encode())

    def do_GET(self):
        mode = state('stub-mode', 'healthy')
        if mode == 'cgit429':
            return self.reply(429, 'text/html', b'<html>429 Too Many Requests</html>')
        if mode == 'cgit404':
            return self.reply(404, 'text/html', b'<html>404 Not Found</html>')
        pkgbase = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query).get('h', ['unknown'])[0]
        # No depends at all, so a healthy stub run finds nothing to violate and
        # a red result in this suite can only come from the mode under test.
        self.reply(200, 'text/plain',
                   f'pkgbase = {pkgbase}\n\tpkgname = {pkgbase}\n'.encode())


class Server(socketserver.TCPServer):
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # curl -f aborts the connection the moment it sees a 4xx status, so the
        # error modes above always end in a reset. socketserver's default is to
        # print a traceback for it, which lands in the test suite's output and
        # reads as a failure in a run where every assertion passed.
        pass


server = Server(('127.0.0.1', 0), Handler)
with open(os.path.join(STATE, 'stub-port'), 'w') as handle:
    handle.write(str(server.server_address[1]))
server.serve_forever()

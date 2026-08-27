import json
import sqlite3
import sys
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

DB_FILE = 'evidence_mobile.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''CREATE TABLE IF NOT EXISTS evidence 
                    (id TEXT PRIMARY KEY, payload TEXT, status TEXT)''')
    conn.commit()
    return conn

class MobileGateway(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/verify':
            length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(length))
            
            conn = init_db()
            conn.execute('INSERT OR REPLACE INTO evidence VALUES (?, ?, ?)', 
                         (payload.get('id'), json.dumps(payload), 'VERIFIED'))
            conn.commit()
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "evidence_id": payload.get('id')}).encode('utf-8'))

class TestMobileGateway(unittest.TestCase):
    def test_db_wal_mode(self):
        conn = init_db()
        mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
        self.assertEqual(mode.lower(), 'wal')
        
    def test_payload_insert(self):
        conn = init_db()
        conn.execute('INSERT OR REPLACE INTO evidence VALUES (?, ?, ?)', 
                     ('evd-vivo-001', '{"data":"test"}', 'VERIFIED'))
        row = conn.execute('SELECT status FROM evidence WHERE id="evd-vivo-001"').fetchone()
        self.assertEqual(row[0], 'VERIFIED')

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        sys.argv.pop()
        unittest.main()
    else:
        init_db()
        print("🚀 Mobile Gateway running on http://127.0.0.1:8080")
        HTTPServer(('127.0.0.1', 8080), MobileGateway).serve_forever()

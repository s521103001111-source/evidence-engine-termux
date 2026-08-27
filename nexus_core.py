import json
import sqlite3
import hash-chain if 'hashlib' in globals() else None
import hashlib
import time
import sys
import os
import unittest
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'evidence_mobile.db')

def init_nexus_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('''CREATE TABLE IF NOT EXISTS nexus_ledger (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tombstone_hash TEXT,
                    created_at REAL NOT NULL
                    )''')
    conn.commit()
    return conn

class PermissionPolicy:
    @staticmethod
    def validate(request_context: dict) -> bool:
        # Fail-closed enforcement
        if not request_context or not isinstance(request_context, dict):
            return False
        if not request_context.get("authenticated", False):
            return False
        if request_context.get("role") not in ["admin", "engine_operator"]:
            return False
        return True

class AuditGate:
    def __init__(self, db_conn):
        self.conn = db_conn

    def process_forget(self, evidence_id: str) -> dict:
        """Forget = ลบ Payload จริงจาก DB แต่คง Hash Tombstone ไว้"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT payload FROM nexus_ledger WHERE id=?", (evidence_id,))
        row = cursor.fetchone()
        if not row:
            return {"status": "NOT_FOUND"}
        
        tombstone_hash = hashlib.sha256(row[0].encode('utf-8')).hexdigest()
        cursor.execute("UPDATE nexus_ledger SET payload='', status='FORGOTTEN', tombstone_hash=? WHERE id=?",
                       (tombstone_hash, evidence_id))
        self.conn.commit()
        return {"status": "FORGOTTEN", "tombstone_hash": tombstone_hash}

    def process_retract(self, evidence_id: str, reason: str) -> dict:
        """Retract = เก็บ Row ไว้ แต่เปลี่ยนสถานะเป็น RETRACTED ไม่ให้เชื่อ Claim เดิม"""
        cursor = self.conn.cursor()
        cursor.execute("UPDATE nexus_ledger SET status='RETRACTED' WHERE id=?", (evidence_id,))
        self.conn.commit()
        return {"status": "RETRACTED", "reason": reason}

class HardenedHTTPServer(ThreadingMixIn, HTTPServer):
    request_queue_size = 128
    daemon_threads = True

class TestNexusCore(unittest.TestCase):
    def setUp(self):
        self.conn = init_nexus_db()
        self.gate = AuditGate(self.conn)

    def test_01_permission_fail_closed_empty(self):
        self.assertFalse(PermissionPolicy.validate({}))

    def test_02_permission_fail_closed_unauth(self):
        self.assertFalse(PermissionPolicy.validate({"authenticated": False, "role": "admin"}))

    def test_03_permission_pass(self):
        self.assertTrue(PermissionPolicy.validate({"authenticated": True, "role": "admin"}))

    def test_04_forget_tombstone(self):
        self.conn.execute("INSERT OR REPLACE INTO nexus_ledger VALUES (?, ?, ?, ?, ?)",
                          ("evd-test-1", '{"claim":"data"}', 'VERIFIED', None, time.time()))
        self.conn.commit()
        res = self.gate.process_forget("evd-test-1")
        self.assertEqual(res["status"], "FORGOTTEN")
        self.assertIsNotNone(res["tombstone_hash"])

    def test_05_retract_claim(self):
        self.conn.execute("INSERT OR REPLACE INTO nexus_ledger VALUES (?, ?, ?, ?, ?)",
                          ("evd-test-2", '{"claim":"invalid"}', 'VERIFIED', None, time.time()))
        self.conn.commit()
        res = self.gate.process_retract("evd-test-2", "invalidated_by_user")
        self.assertEqual(res["status"], "RETRACTED")

if __name__ == '__main__':
    unittest.main()

import os
import sqlite3
import json
import unittest
from engine import EvidenceEngine, EvidenceEvent, LedgerIntegrityError

class TestEngineTamperVerification(unittest.TestCase):
    def setUp(self):
        self.db = "test_tamper.db"
        self.ledger = "test_tamper_events.jsonl"
        self._cleanup()
        self.engine = EvidenceEngine(db_path=self.db, ledger_path=self.ledger)

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for f in [self.db, self.ledger, self.db + "-wal", self.db + "-shm", self.ledger + ".lock"]:
            if os.path.exists(f):
                os.remove(f)

    def test_01_l0_intake_pass(self):
        evt = self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {"device": "Vivo X300 Pro"})
        self.assertEqual(evt.evidence_level, "L0_CLAIMED")
        valid, msg, count = self.engine.verify_ledger_integrity()
        self.assertTrue(valid)
        self.assertEqual(count, 1)

    def test_02_promotion_pass(self):
        self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {})
        evt1 = self.engine.promote_level("CLAIM-01", "L1_STATIC_VERIFIED", "Montri", {"static": "OK"})
        evt2 = self.engine.promote_level("CLAIM-01", "L2_TEST_VERIFIED", "Montri", {"unit_tests": "PASS"})
        self.assertEqual(evt2.evidence_level, "L2_TEST_VERIFIED")
        valid, _, count = self.engine.verify_ledger_integrity()
        self.assertTrue(valid)
        self.assertEqual(count, 3)

    def test_03_chain_continuity_pass(self):
        self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {})
        self.engine.promote_level("CLAIM-01", "L1_STATIC_VERIFIED", "Montri", {})
        valid, msg, count = self.engine.verify_ledger_integrity()
        self.assertTrue(valid)
        self.assertEqual(count, 2)

    def test_04_restart_recovery_pass(self):
        self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {})
        self.engine.promote_level("CLAIM-01", "L1_STATIC_VERIFIED", "Montri", {})
        restarted_engine = EvidenceEngine(db_path=self.db, ledger_path=self.ledger)
        evt = restarted_engine.promote_level("CLAIM-01", "L2_TEST_VERIFIED", "Montri", {})
        self.assertEqual(evt.evidence_level, "L2_TEST_VERIFIED")
        valid, _, count = restarted_engine.verify_ledger_integrity()
        self.assertTrue(valid)
        self.assertEqual(count, 3)

    def test_05_tamper_payload_fail(self):
        self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {"status": "original"})
        with open(self.ledger, "r", encoding="utf-8") as f:
            lines = f.readlines()
        tampered_line = lines[0].replace("original", "tampered")
        with open(self.ledger, "w", encoding="utf-8") as f:
            f.write(tampered_line)
        valid, msg, _ = self.engine.verify_ledger_integrity()
        self.assertFalse(valid)
        self.assertIn("Tamper detected", msg)

    def test_06_tamper_previous_hash_fail(self):
        self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {})
        self.engine.promote_level("CLAIM-01", "L1_STATIC_VERIFIED", "Montri", {})
        with open(self.ledger, "r", encoding="utf-8") as f:
            lines = f.readlines()
        data = json.loads(lines[1])
        data["previous_hash"] = "f" * 64
        lines[1] = json.dumps(data, sort_keys=True, separators=(',', ':')) + "\n"
        with open(self.ledger, "w", encoding="utf-8") as f:
            f.writelines(lines)
        valid, msg, _ = self.engine.verify_ledger_integrity()
        self.assertFalse(valid)
        self.assertIn("Tamper detected", msg)

    def test_07_tamper_deleted_event_fail(self):
        self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {})
        self.engine.promote_level("CLAIM-01", "L1_STATIC_VERIFIED", "Montri", {})
        self.engine.promote_level("CLAIM-01", "L2_TEST_VERIFIED", "Montri", {})
        with open(self.ledger, "r", encoding="utf-8") as f:
            lines = f.readlines()
        del lines[1]
        with open(self.ledger, "w", encoding="utf-8") as f:
            f.writelines(lines)
        valid, msg, _ = self.engine.verify_ledger_integrity()
        self.assertFalse(valid)
        self.assertIn("Broken hash chain", msg)

    def test_08_duplicate_event_fail(self):
        self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {})
        with open(self.ledger, "r", encoding="utf-8") as f:
            line = f.readline()
        with open(self.ledger, "a", encoding="utf-8") as f:
            f.write(line)
        valid, msg, _ = self.engine.verify_ledger_integrity()
        self.assertFalse(valid)
        self.assertIn("Duplicate event_id detected", msg)

    def test_09_uuid_uniqueness_pass(self):
        evt1 = self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {})
        evt2 = self.engine.submit_intake("CLAIM-02", "Mobile Engine Test 2", "Montri", {})
        self.assertNotEqual(evt1.event_id, evt2.event_id)
        self.assertTrue(evt1.event_id.startswith("EVT-"))

    def test_10_canonical_json_determinism_pass(self):
        payload_a = {"b": 2, "a": 1, "nested": {"y": "val", "x": "val"}}
        payload_b = {"a": 1, "b": 2, "nested": {"x": "val", "y": "val"}}
        evt1 = EvidenceEvent("E1", "C1", "0"*64, 100.0, "actor", "SYS", "ACT", "L0", payload_a)
        evt2 = EvidenceEvent("E1", "C1", "0"*64, 100.0, "actor", "SYS", "ACT", "L0", payload_b)
        self.assertEqual(evt1.calculate_hash(), evt2.calculate_hash())

    def test_11_startup_integrity_check_fail_on_corrupted_ledger(self):
        self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {"status": "good"})
        with open(self.ledger, "w", encoding="utf-8") as f:
            f.write("CORRUPTED_NON_JSON_LINE\n")
        with self.assertRaises(LedgerIntegrityError):
            EvidenceEngine(db_path=self.db, ledger_path=self.ledger)

    def test_12_sqlite_title_exact_reconstruction_pass(self):
        original_title = "Vivo X300 Pro Production Audit Title"
        self.engine.submit_intake("CLAIM-99", original_title, "Montri", {"param": 123})
        self.engine.promote_level("CLAIM-99", "L1_STATIC_VERIFIED", "Montri", {})
        os.remove(self.db)
        recovered_engine = EvidenceEngine(db_path=self.db, ledger_path=self.ledger, auto_recover=True)
        with sqlite3.connect(self.db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title, current_level FROM claims WHERE claim_id = 'CLAIM-99'")
            row = cursor.fetchone()
            self.assertEqual(row[0], original_title)
            self.assertEqual(row[1], "L1_STATIC_VERIFIED")

    def test_13_duplicate_block_hash_fail(self):
        evt = self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {})
        from dataclasses import asdict
        data = asdict(evt)
        data["event_id"] = "EVT-DIFFERENT-ID"
        with open(self.ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, sort_keys=True, separators=(',', ':')) + "\n")
        valid, msg, _ = self.engine.verify_ledger_integrity()
        self.assertFalse(valid)
        self.assertIn("Duplicate block_hash detected", msg)

    def test_14_corrupted_jsonl_line_fail(self):
        self.engine.submit_intake("CLAIM-01", "Mobile Engine Test", "Montri", {})
        with open(self.ledger, "a", encoding="utf-8") as f:
            f.write("{invalid json line\n")
        valid, msg, _ = self.engine.verify_ledger_integrity()
        self.assertFalse(valid)
        self.assertIn("Corrupted JSON format", msg)

    def test_15_strict_lock_sequence_race_prevention_pass(self):
        evt1 = self.engine.submit_intake("CLAIM-01", "Lock Sequence Test 1", "Montri", {})
        evt2 = self.engine.submit_intake("CLAIM-01", "Lock Sequence Test 2", "Montri", {})
        self.assertEqual(evt2.previous_hash, evt1.block_hash)
        valid, _, count = self.engine.verify_ledger_integrity()
        self.assertTrue(valid)
        self.assertEqual(count, 2)

if __name__ == "__main__":
    unittest.main()

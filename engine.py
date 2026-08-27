import os
import sqlite3
import hashlib
import json
import time
import uuid
import fcntl
from dataclasses import dataclass, asdict
from typing import Dict, Any, Tuple

class LedgerIntegrityError(Exception):
    pass

class EvidenceLevel:
    L0_CLAIMED = "L0_CLAIMED"
    L1_STATIC_VERIFIED = "L1_STATIC_VERIFIED"
    L2_TEST_VERIFIED = "L2_TEST_VERIFIED"
    L3_HOST_VERIFIED = "L3_HOST_VERIFIED"
    ORDER = [L0_CLAIMED, L1_STATIC_VERIFIED, L2_TEST_VERIFIED, L3_HOST_VERIFIED]

@dataclass
class EvidenceEvent:
    event_id: str
    claim_id: str
    previous_hash: str
    timestamp: float
    actor: str
    recorded_by: str
    action: str
    evidence_level: str
    payload: Dict[str, Any]
    block_hash: str = ""

    def calculate_hash(self) -> str:
        content = {
            "event_id": self.event_id,
            "claim_id": self.claim_id,
            "previous_hash": self.previous_hash,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "recorded_by": self.recorded_by,
            "action": self.action,
            "evidence_level": self.evidence_level,
            "payload": self.payload
        }
        raw_bytes = json.dumps(content, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(raw_bytes).hexdigest()

class EvidenceEngine:
    def __init__(self, db_path: str = "memory.db", ledger_path: str = "events.jsonl", auto_recover: bool = True):
        self.db_path = db_path
        self.ledger_path = ledger_path
        self.lock_path = ledger_path + ".lock"
        self._init_db()
        
        is_valid, msg, _ = self.verify_ledger_integrity()
        if not is_valid:
            raise LedgerIntegrityError(f"Startup check failed: {msg}")
            
        if auto_recover:
            self.rebuild_sqlite_from_ledger()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    current_level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    block_hash TEXT UNIQUE NOT NULL,
                    timestamp REAL NOT NULL,
                    actor TEXT NOT NULL,
                    recorded_by TEXT NOT NULL,
                    action TEXT NOT NULL,
                    evidence_level TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(claim_id) REFERENCES claims(claim_id)
                );
            """)
            conn.commit()

    def _get_latest_ledger_hash(self) -> str:
        if not os.path.exists(self.ledger_path):
            return "0" * 64
        last_line = ""
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last_line = line
        if not last_line:
            return "0" * 64
        try:
            data = json.loads(last_line)
            return data.get("block_hash", "0" * 64)
        except Exception:
            return "0" * 64

    def submit_intake(self, claim_id: str, title: str, actor: str, raw_payload: Dict[str, Any]) -> EvidenceEvent:
        payload_with_meta = dict(raw_payload)
        payload_with_meta["_title"] = title

        return self._append_event_atomic(
            claim_id=claim_id,
            title=title,
            actor=actor,
            action="SUBMIT_INTAKE",
            target_level=EvidenceLevel.L0_CLAIMED,
            payload=payload_with_meta,
            status="PENDING"
        )

    def promote_level(self, claim_id: str, target_level: str, actor: str, proof_payload: Dict[str, Any]) -> EvidenceEvent:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT current_level, title FROM claims WHERE claim_id = ?", (claim_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Claim {claim_id} not found.")
            current_level, title = row[0], row[1]

        cur_idx = EvidenceLevel.ORDER.index(current_level)
        tgt_idx = EvidenceLevel.ORDER.index(target_level)

        if tgt_idx != cur_idx + 1:
            raise ValueError(f"Invalid level transition from {current_level} to {target_level}.")

        payload_with_meta = dict(proof_payload)
        payload_with_meta["_title"] = title

        status = "VERIFIED" if target_level == EvidenceLevel.L3_HOST_VERIFIED else "IN_PROGRESS"
        return self._append_event_atomic(
            claim_id=claim_id,
            title=title,
            actor=actor,
            action=f"PROMOTE_{target_level}",
            target_level=target_level,
            payload=payload_with_meta,
            status=status
        )

    def _append_event_atomic(self, claim_id: str, title: str, actor: str, action: str, target_level: str, payload: Dict[str, Any], status: str) -> EvidenceEvent:
        with open(self.lock_path, "w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                prev_hash = self._get_latest_ledger_hash()
                timestamp = time.time()
                event_id = f"EVT-{uuid.uuid4().hex[:12].upper()}"

                event = EvidenceEvent(
                    event_id=event_id,
                    claim_id=claim_id,
                    previous_hash=prev_hash,
                    timestamp=timestamp,
                    actor=actor,
                    recorded_by="SYSTEM",
                    action=action,
                    evidence_level=target_level,
                    payload=payload
                )
                event.block_hash = event.calculate_hash()

                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("BEGIN TRANSACTION;")
                    conn.execute("""
                        INSERT INTO claims (claim_id, title, current_level, status, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(claim_id) DO UPDATE SET
                            current_level = excluded.current_level,
                            status = excluded.status,
                            updated_at = excluded.updated_at;
                    """, (event.claim_id, title, target_level, status, event.timestamp))

                    conn.execute("""
                        INSERT INTO events (event_id, claim_id, previous_hash, block_hash, timestamp, actor, recorded_by, action, evidence_level, payload)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (event.event_id, event.claim_id, event.previous_hash, event.block_hash, event.timestamp, event.actor, event.recorded_by, event.action, event.evidence_level, json.dumps(event.payload)))

                    with open(self.ledger_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(asdict(event), sort_keys=True, separators=(',', ':')) + "\n")
                        f.flush()
                        os.fsync(f.fileno())

                    conn.commit()
                return event
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def verify_ledger_integrity(self) -> Tuple[bool, str, int]:
        if not os.path.exists(self.ledger_path):
            return True, "Ledger empty", 0

        prev_hash = "0" * 64
        count = 0
        seen_event_ids = set()
        seen_block_hashes = set()

        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    return False, f"Corrupted JSON format at line {line_no}", count

                if data["event_id"] in seen_event_ids:
                    return False, f"Duplicate event_id detected at line {line_no}: {data['event_id']}", count
                if data["block_hash"] in seen_block_hashes:
                    return False, f"Duplicate block_hash detected at line {line_no}: {data['block_hash']}", count

                seen_event_ids.add(data["event_id"])
                seen_block_hashes.add(data["block_hash"])

                evt = EvidenceEvent(
                    event_id=data["event_id"],
                    claim_id=data["claim_id"],
                    previous_hash=data["previous_hash"],
                    timestamp=data["timestamp"],
                    actor=data["actor"],
                    recorded_by=data["recorded_by"],
                    action=data["action"],
                    evidence_level=data["evidence_level"],
                    payload=data["payload"]
                )
                if evt.calculate_hash() != data["block_hash"]:
                    return False, f"Tamper detected: Payload/Block hash mismatch at line {line_no}", count
                if data["previous_hash"] != prev_hash:
                    return False, f"Tamper detected: Broken hash chain sequence at line {line_no}", count

                prev_hash = data["block_hash"]
                count += 1

        return True, "Ledger integrity 100% verified", count

    def rebuild_sqlite_from_ledger(self):
        if not os.path.exists(self.ledger_path):
            return
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM events;")
            conn.execute("DELETE FROM claims;")
            
            claims_map = {}
            with open(self.ledger_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    claim_id = data["claim_id"]
                    level = data["evidence_level"]
                    status = "VERIFIED" if level == EvidenceLevel.L3_HOST_VERIFIED else ("PENDING" if level == EvidenceLevel.L0_CLAIMED else "IN_PROGRESS")
                    
                    title = data["payload"].get("_title", f"Claim {claim_id}")
                    claims_map[claim_id] = (claim_id, title, level, status, data["timestamp"])
                    
                    conn.execute("""
                        INSERT INTO events (event_id, claim_id, previous_hash, block_hash, timestamp, actor, recorded_by, action, evidence_level, payload)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (data["event_id"], data["claim_id"], data["previous_hash"], data["block_hash"], data["timestamp"], data["actor"], data["recorded_by"], data["action"], data["evidence_level"], json.dumps(data["payload"])))
            
            for c_id, t, lev, st, ts in claims_map.values():
                conn.execute("""
                    INSERT INTO claims (claim_id, title, current_level, status, updated_at)
                    VALUES (?, ?, ?, ?, ?);
                """, (c_id, t, lev, st, ts))
            conn.commit()

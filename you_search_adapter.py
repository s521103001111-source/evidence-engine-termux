import json
import time
import urllib.request
import urllib.error
import unittest

GATEWAY_URL = "http://127.0.0.1:8080/verify"

def submit_to_gateway(payload: dict) -> dict:
    """ส่ง Canonical Payload เข้า Local Gateway (Tier 1)"""
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(GATEWAY_URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {"status": "gateway_unreachable", "error": str(e)}

def normalize_search_evidence(query: str, search_results: list) -> dict:
    """แปลงข้อมูลจาก Agent (you-search) ให้เป็น Evidence Event"""
    return {
        "id": f"evd-src-{int(time.time()*1000)}",
        "type": "SearchEvidence",
        "query": query,
        "provider": "you-search",
        "results": search_results,
        "timestamp": time.time()
    }

def create_retrieval_failed_event(provider: str, reason: str, retryable: bool = True) -> dict:
    """สร้าง Fallback Event เมื่อเกิด Network Failure/429/Timeout"""
    return {
        "id": f"evd-fail-{int(time.time()*1000)}",
        "type": "RetrievalFailed",
        "provider": provider,
        "reason": reason,
        "retryable": retryable,
        "timestamp": time.time()
    }

class TestAdapter(unittest.TestCase):
    def test_normalize_payload(self):
        evt = normalize_search_evidence("test", [{"title": "example", "url": "https://example.com"}])
        self.assertEqual(evt["type"], "SearchEvidence")
        self.assertTrue(evt["id"].startswith("evd-src-"))

    def test_failed_event_payload(self):
        evt = create_retrieval_failed_event("you-search", "quota_exceeded_429", retryable=False)
        self.assertEqual(evt["type"], "RetrievalFailed")
        self.assertFalse(evt["retryable"])

if __name__ == '__main__':
    unittest.main()

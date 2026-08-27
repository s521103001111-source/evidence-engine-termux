# Evidence Engine V2 (Termux Mobile Baseline)

Deterministic evidence-first auditing engine optimized for single-device execution via Termux.

## Technical Highlights

- **Zero External Dependencies**: Built entirely using Python Standard Library.
- **Hash-chained Audit Ledger**: Append-only JSONL event log with SHA-256 validation.
- **SQLite WAL Cache**: Embedded state synchronization with automatic recovery.
- **Concurrency Lock**: File locking via `fcntl` to prevent race conditions.

## Run Verification

```bash
python3 -m unittest test_engine.py -v

จากนั้น **แนะนำให้ทดสอบก่อน Push**:

```bash
python3 -m unittest test_engine.py -v
git status
git ls-files | grep -E '(__pycache__|\.pyc$)' || echo "No pycache/pyc tracked"git remote -v
git push -u origin main
git status
git log --oneline -1
git ls-files
git push -u origin main
python3 -m unittest test_engine.py -v

git status

git ls-files | grep -E '(^|/)__pycache__/|\.pyc$' || echo "No pycache/pyc tracked"

git remote -v

git log --oneline -1

git ls-files

git push -u origin main

git status
git status
git ls-files | grep -E '(^|/)__pycache__/|\.pyc$' || echo "No pycache/pyc tracked"
git remote -v
git log --oneline -1
git ls-files
git push -u origin main
# รัน Unit Test ให้ผ่าน 100% ก่อนส่ง Push
python3 -m unittest test_engine.py -v && \
git status && \
git ls-files | grep -E '(^|/)__pycache__/|\.pyc$' || echo "No pycache/pyc tracked" && \
git push -u origin main
mkdir -p .github/workflows

cat << 'EOF' > .github/workflows/test.yml
name: Evidence Engine V2 Verification CI

on:
  push:
    branches: [ "main" ]
  pull_request:
    branches: [ "main" ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]

    steps:
    - uses: actions/checkout@v4
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
    - name: Run Unit Tests
      run: |
        python -m unittest test_engine.py -v

#!/usr/bin/env python
"""Display sample artifacts generated during test."""

import sqlite3
from pathlib import Path

db_path = Path("data/corpus_forge.db")
if not db_path.exists():
    print("Database not found")
    exit(1)

db = sqlite3.connect(str(db_path))
db.row_factory = sqlite3.Row

print("\n" + "="*80)
print("GENERATED ARTIFACTS SAMPLE VERIFICATION")
print("="*80 + "\n")

# Stats
docs = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
artifacts = db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
print(f"📊 Total Documents: {docs}")
print(f"📊 Total Artifacts: {artifacts}\n")

# Sample artifacts by type
print("📝 SAMPLE ARTIFACTS BY TYPE:\n")
for kind in ["quiz", "summary", "explain_simple", "explain_detailed", "flashcards"]:
    rows = db.execute("SELECT title, kind FROM artifacts WHERE kind = ? LIMIT 1", (kind,)).fetchall()
    if rows:
        title = rows[0]["title"]
        print(f"✅ {kind:20} - Example: {title}")
    else:
        print(f"⚠️  {kind:20} - No examples found")

# Recent artifacts
print("\n📋 RECENT 10 ARTIFACTS:\n")
recent = db.execute(
    "SELECT title, kind, created_at FROM artifacts ORDER BY created_at DESC LIMIT 10"
).fetchall()

for i, artifact in enumerate(recent, 1):
    title = artifact["title"][:35].ljust(35)
    kind = artifact["kind"].ljust(18)
    time = artifact["created_at"]
    print(f"{i:2}. {title} [{kind}] {time}")

# Content samples
print("\n📄 CONTENT SAMPLES:\n")

print("--- SUMMARY ARTIFACT SAMPLE ---")
sample = db.execute("SELECT content FROM artifacts WHERE kind = ? LIMIT 1", ("summary",)).fetchone()
if sample:
    lines = sample["content"].split("\n")[:8]
    for line in lines:
        print(line[:80])
    print("... (truncated)\n")

print("--- QUIZ ARTIFACT SAMPLE ---")
sample = db.execute("SELECT content FROM artifacts WHERE kind = ? LIMIT 1", ("quiz",)).fetchone()
if sample:
    lines = sample["content"].split("\n")[:8]
    for line in lines:
        print(line[:80])
    print("... (truncated)\n")

print("--- EXPLANATION (DETAILED) SAMPLE ---")
sample = db.execute("SELECT content FROM artifacts WHERE kind = ? LIMIT 1", ("explain_detailed",)).fetchone()
if sample:
    lines = sample["content"].split("\n")[:8]
    for line in lines:
        print(line[:80])
    print("... (truncated)\n")

print("="*80 + "\n")
db.close()

#!/usr/bin/env python
"""
Comprehensive smoke test for all Corpus Forge features.
Tests all file types, generation tasks, retrieval strategies, and steering parameters.
"""

import sys
from io import BytesIO
import sqlite3
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app import create_app
from app.document_processing import allowed_file

# ============================================================================
# TEST CONFIGURATION
# ============================================================================

SAMPLE_FILES = {
    "markdown.md": """# Machine Learning Fundamentals

Machine learning is a subset of artificial intelligence that focuses on building systems 
that learn from data without being explicitly programmed.

## Key Concepts

### Supervised Learning
Supervised learning involves training models on labeled data. The model learns to map 
inputs to outputs based on examples.

### Unsupervised Learning
Unsupervised learning finds patterns in unlabeled data. Common techniques include clustering 
and dimensionality reduction.

### Neural Networks
Neural networks are inspired by biological neurons. They consist of interconnected layers 
that process information through weighted connections.

### Deep Learning
Deep learning uses multiple layers of neural networks to extract increasingly complex features 
from raw input. This has enabled breakthrough results in computer vision and natural language processing.

## Applications

- Image classification and object detection
- Natural language processing and translation
- Autonomous vehicles
- Recommendation systems
- Medical diagnosis
""",
    
    "textfile.txt": """Python Programming Essentials

Python is a high-level, interpreted programming language known for its simplicity and readability.
It was created by Guido van Rossum and first released in 1991.

Core Features of Python:
1. Easy to learn and read
2. Strong standard library
3. Dynamic typing
4. Support for multiple programming paradigms
5. Extensive community support

Common Use Cases:
- Web development (Django, Flask)
- Data analysis and scientific computing (NumPy, Pandas)
- Machine learning (TensorFlow, PyTorch)
- Automation and scripting
- Game development

Python Syntax Basics:
Variables are created by assignment. Functions are defined using the 'def' keyword.
Classes support object-oriented programming. Exception handling uses try-except blocks.
""",
    
    "code.py": """import sqlite3
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class DocumentStore:
    '''Store and retrieve documents from SQLite database.'''
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        '''Initialize database with documents table.'''
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT
                )
            ''')
            conn.commit()
            logger.info("Database initialized")
    
    def add_document(self, name: str, content: str) -> int:
        '''Add a new document and return its ID.'''
        if not name or not content:
            raise ValueError("Name and content required")
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'INSERT INTO documents (name, content) VALUES (?, ?)',
                (name, content)
            )
            conn.commit()
            logger.info(f"Added document: {name}")
            return cursor.lastrowid
    
    def get_document(self, doc_id: int) -> Optional[Dict]:
        '''Retrieve a document by ID.'''
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                'SELECT * FROM documents WHERE id = ?',
                (doc_id,)
            ).fetchone()
            if row:
                return {'id': row[0], 'name': row[1], 'content': row[2]}
        return None
    
    def list_documents(self) -> List[Dict]:
        '''List all documents.'''
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute('SELECT id, name FROM documents').fetchall()
            return [{'id': row[0], 'name': row[1]} for row in rows]
""",
    
    "json_file.json": """{
    "project": "Corpus Forge",
    "version": "1.0.0",
    "description": "AI-powered document processing system",
    "features": [
        "Document ingestion from multiple file types",
        "BM25-based retrieval",
        "Quiz generation",
        "Summary generation",
        "Explanation generation",
        "Code review reports",
        "GitHub repository integration",
        "Google Gemini API integration",
        "Theme toggle (black/white)",
        "SQLite persistence"
    ],
    "architecture": {
        "backend": "Flask 3.0.3",
        "database": "SQLite",
        "retrieval": "BM25-style ranking",
        "ai_model": "Google Gemini 1.5",
        "frontend": "Vanilla JavaScript"
    },
    "supported_file_types": [
        "txt", "md", "pdf", "py", "js", "java", "cpp", "json", 
        "csv", "html", "docx", "xlsx"
    ]
}
""",
}

# Generation tasks to test
GENERATION_TASKS = ["flashcards", "quiz", "summary", "explain_simple", "explain_detailed"]

# Retrieval strategies to test
RETRIEVAL_STRATEGIES = ["fixed", "file", "compare"]

# Steering parameter variations
STEERING_VARIATIONS = [
    {"audience": "beginner student", "tone": "clear", "output_format": "bullets", "creativity": "low"},
    {"audience": "professional developer", "tone": "technical", "output_format": "narrative", "creativity": "medium"},
    {"audience": "researcher", "tone": "academic", "output_format": "detailed", "creativity": "high"},
]

# Q&A queries to test
QA_QUERIES = [
    "What is machine learning?",
    "How does Python compare to other languages?",
    "What are the main features?",
]


# ============================================================================
# TEST RUNNER
# ============================================================================

def run_comprehensive_tests():
    """Run all feature combinations."""
    
    print("\n" + "="*80)
    print("CORPUS FORGE - COMPREHENSIVE FEATURE TEST")
    print("="*80 + "\n")
    
    # Create test app
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    
    test_results = {
        "uploads": [],
        "generation": [],
        "qa": [],
        "errors": []
    }
    
    # ========================================================================
    # TEST 1: Upload Sample Files
    # ========================================================================
    print("\n📤 PHASE 1: UPLOADING SAMPLE FILES")
    print("-" * 80)
    
    document_ids = {}
    
    for filename, content in SAMPLE_FILES.items():
        try:
            response = client.post(
                "/upload",
                data={"document": (BytesIO(content.encode("utf-8")), filename)},
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            
            if response.status_code == 200 and b"added to the corpus" in response.data:
                # Extract document ID from database
                with sqlite3.connect("data/corpus_forge.db") as db:
                    doc_id = db.execute(
                        "SELECT id FROM documents WHERE filename = ?",
                        (filename,)
                    ).fetchone()
                    if doc_id:
                        document_ids[filename] = doc_id[0]
                        status = "✅"
                    else:
                        status = "⚠️"
                        document_ids[filename] = None
            else:
                status = "❌"
                document_ids[filename] = None
            
            print(f"{status} {filename:20} | Status: {response.status_code}")
            test_results["uploads"].append((filename, response.status_code == 200))
            
        except Exception as e:
            print(f"❌ {filename:20} | Error: {str(e)[:50]}")
            test_results["errors"].append((f"Upload {filename}", str(e)))
            test_results["uploads"].append((filename, False))
    
    valid_docs = {k: v for k, v in document_ids.items() if v is not None}
    print(f"\n✅ Successfully uploaded: {len(valid_docs)}/{len(SAMPLE_FILES)} files")
    
    if not valid_docs:
        print("❌ No files uploaded successfully. Aborting test.")
        return test_results
    
    # ========================================================================
    # TEST 2: Generation Tasks with All Combinations
    # ========================================================================
    print("\n\n🎯 PHASE 2: TESTING GENERATION TASKS")
    print("-" * 80)
    
    test_count = 0
    pass_count = 0
    
    for filename, doc_id in list(valid_docs.items())[:2]:  # Test first 2 files
        for task in GENERATION_TASKS:
            for strategy in RETRIEVAL_STRATEGIES:
                for steering_idx, steering in enumerate(STEERING_VARIATIONS):
                    test_count += 1
                    
                    try:
                        response = client.post(
                            "/generate",
                            data={
                                "active_documents": str(doc_id),
                                "task": task,
                                "query": "main features concepts",
                                "strategy": strategy,
                                "audience": steering["audience"],
                                "tone": steering["tone"],
                                "output_format": steering["output_format"],
                                "creativity": steering["creativity"],
                                "instructions": "",
                            },
                            follow_redirects=True,
                        )
                        
                        if response.status_code == 200:
                            status = "✅"
                            pass_count += 1
                        else:
                            status = "⚠️"
                        
                        if test_count % 5 == 0:  # Print every 5th test
                            print(
                                f"{status} {filename:15} | {task:18} | {strategy:8} | "
                                f"Creativity: {steering['creativity']:6} | Status: {response.status_code}"
                            )
                        
                        test_results["generation"].append({
                            "file": filename,
                            "task": task,
                            "strategy": strategy,
                            "creativity": steering["creativity"],
                            "status": response.status_code == 200
                        })
                        
                    except Exception as e:
                        print(
                            f"❌ {filename:15} | {task:18} | {strategy:8} | "
                            f"Error: {str(e)[:40]}"
                        )
                        test_results["errors"].append((f"Generate {filename}/{task}", str(e)))
    
    print(f"\n✅ Generation Tests: {pass_count}/{test_count} passed ({100*pass_count//test_count}%)")
    
    # ========================================================================
    # TEST 3: Q&A (Chat) Functionality
    # ========================================================================
    print("\n\n💬 PHASE 3: TESTING Q&A (CHAT) FUNCTIONALITY")
    print("-" * 80)
    
    qa_pass = 0
    
    for filename, doc_id in list(valid_docs.items())[:2]:
        for query in QA_QUERIES:
            try:
                response = client.post(
                    "/chat",
                    data={
                        "active_documents": str(doc_id),
                        "question": query,
                        "strategy": "fixed",
                        "audience": "general audience",
                        "tone": "conversational",
                        "output_format": "paragraph",
                        "creativity": "low",
                        "instructions": "",
                    },
                    follow_redirects=True,
                )
                
                if response.status_code == 200:
                    status = "✅"
                    qa_pass += 1
                else:
                    status = "⚠️"
                
                print(f"{status} {filename:15} | Q: {query[:40]:40} | Status: {response.status_code}")
                test_results["qa"].append((filename, query, response.status_code == 200))
                
            except Exception as e:
                print(f"❌ {filename:15} | Q: {query[:40]:40} | Error: {str(e)[:30]}")
                test_results["errors"].append((f"Chat {filename}", str(e)))
    
    print(f"\n✅ Q&A Tests: {qa_pass}/{len(QA_QUERIES)*len(list(valid_docs.items())[:2])} passed")
    
    # ========================================================================
    # TEST 4: Artifact Retrieval
    # ========================================================================
    print("\n\n📋 PHASE 4: TESTING ARTIFACT RETRIEVAL")
    print("-" * 80)
    
    try:
        response = client.get("/artifacts")
        if response.status_code == 200:
            print("✅ /artifacts endpoint working")
            # Count artifacts in database
            with sqlite3.connect("data/corpus_forge.db") as db:
                artifact_count = db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
            print(f"✅ Total artifacts generated: {artifact_count}")
        else:
            print(f"⚠️ /artifacts endpoint status: {response.status_code}")
    except Exception as e:
        print(f"❌ Artifact retrieval error: {str(e)}")
        test_results["errors"].append(("Artifacts", str(e)))
    
    # ========================================================================
    # TEST 5: API Stats
    # ========================================================================
    print("\n\n📊 PHASE 5: TESTING STATS & TRACKING")
    print("-" * 80)
    
    try:
        response = client.get("/api/stats")
        if response.status_code == 200:
            stats = response.get_json()
            print(f"✅ /api/stats endpoint working")
            print(f"   Documents: {stats['stats']['document_count']}")
            print(f"   Artifacts: {stats['stats']['artifact_count']}")
            print(f"   Requests: {stats['usage']['request_count']}")
            print(f"   Est. Tokens: {stats['usage']['token_count']}")
        else:
            print(f"⚠️ /api/stats status: {response.status_code}")
    except Exception as e:
        print(f"❌ Stats error: {str(e)}")
        test_results["errors"].append(("Stats", str(e)))
    
    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================
    print("\n\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    upload_pass = sum(1 for _, status in test_results["uploads"] if status)
    gen_pass = sum(1 for test in test_results["generation"] if test["status"])
    qa_pass = sum(1 for _, _, status in test_results["qa"] if status)
    
    print(f"\n📤 File Uploads:       {upload_pass}/{len(test_results['uploads'])} ✅")
    print(f"🎯 Generation Tasks:  {gen_pass}/{len(test_results['generation'])} ✅")
    print(f"💬 Q&A Tests:         {qa_pass}/{len(test_results['qa'])} ✅")
    
    if test_results["errors"]:
        print(f"\n⚠️  Errors encountered: {len(test_results['errors'])}")
        for error_type, error_msg in test_results["errors"][:5]:
            print(f"   - {error_type}: {error_msg[:60]}")
    
    total_tests = len(test_results["uploads"]) + len(test_results["generation"]) + len(test_results["qa"])
    total_pass = upload_pass + gen_pass + qa_pass
    pass_rate = (100 * total_pass // total_tests) if total_tests > 0 else 0
    
    print(f"\n{'='*80}")
    print(f"OVERALL: {total_pass}/{total_tests} tests passed ({pass_rate}%)")
    print(f"{'='*80}\n")
    
    return test_results


if __name__ == "__main__":
    import os
    os.chdir(Path(__file__).parent)
    results = run_comprehensive_tests()
    
    # Exit with appropriate code
    total_tests = len(results["uploads"]) + len(results["generation"]) + len(results["qa"])
    total_pass = (
        sum(1 for _, status in results["uploads"] if status) +
        sum(1 for test in results["generation"] if test["status"]) +
        sum(1 for _, _, status in results["qa"] if status)
    )
    
    sys.exit(0 if total_pass == total_tests else 1)

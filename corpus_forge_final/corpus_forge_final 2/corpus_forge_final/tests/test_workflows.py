from io import BytesIO
import sqlite3

from app import create_app
from app.generator import generate_quiz, unique_evidence_text, generate_summary, generate_explain


def make_client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # These workflow tests validate the LOCAL generation pipeline and assert its
    # flash message, so force the Gemini path off regardless of any ambient
    # environment or auto-loaded .env file.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import app.routes as routes_module
    monkeypatch.setattr(routes_module, "gemini_is_enabled", lambda *args, **kwargs: False)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client(), tmp_path / "data" / "corpus_forge.db"


def test_upload_generate_and_stats_workflow(tmp_path, monkeypatch):
    client, db_path = make_client(tmp_path, monkeypatch)
    content = (
        "Corpus Forge uses retrieval architecture evaluation and grounded evidence. "
        "The retrieval workflow creates flashcards and quizzes from selected documents."
    )

    upload_response = client.post(
        "/upload",
        data={"document": (BytesIO(content.encode("utf-8")), "notes.md")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert upload_response.status_code == 200
    assert b"notes.md was added to the corpus." in upload_response.data
    assert b"1</strong" in upload_response.data

    with sqlite3.connect(db_path) as db:
        document_id = db.execute("SELECT id FROM documents WHERE filename = ?", ("notes.md",)).fetchone()[0]

    generate_response = client.post(
        "/generate",
        data={
            "active_documents": str(document_id),
            "task": "flashcards",
            "query": "retrieval architecture",
            "strategy": "fixed",
            "audience": "beginner student",
            "tone": "clear and direct",
            "output_format": "structured bullets",
            "creativity": "low",
            "instructions": "",
        },
        follow_redirects=True,
    )

    assert generate_response.status_code == 200
    assert b"Flashcards was generated and saved." in generate_response.data
    assert b"Generated artifacts" in generate_response.data

    stats_response = client.get("/api/stats")
    payload = stats_response.get_json()

    assert stats_response.status_code == 200
    assert payload["stats"]["document_count"] == 1
    assert payload["stats"]["artifact_count"] == 1
    assert payload["usage"]["request_count"] == 1
    assert payload["usage"]["token_count"] > 0


def test_unsupported_upload_shows_feedback_without_insert(tmp_path, monkeypatch):
    client, db_path = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/upload",
        data={"document": (BytesIO(b"not allowed"), "malware.exe")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Unsupported" in response.data or b"file type" in response.data
    with sqlite3.connect(db_path) as db:
        count = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    assert count == 0


def test_generate_summary_from_document(tmp_path, monkeypatch):
    """Test that summary generation works end-to-end."""
    client, db_path = make_client(tmp_path, monkeypatch)
    content = (
        "Machine learning is a subset of artificial intelligence. "
        "It focuses on building systems that learn from data. "
        "Neural networks are inspired by biological brains. "
        "Deep learning uses multiple layers of neural networks."
    )

    # Upload document
    upload_response = client.post(
        "/upload",
        data={"document": (BytesIO(content.encode("utf-8")), "ml_intro.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert upload_response.status_code == 200

    # Get document ID
    with sqlite3.connect(db_path) as db:
        document_id = db.execute("SELECT id FROM documents WHERE filename = ?", ("ml_intro.txt",)).fetchone()[0]

    # Generate summary
    generate_response = client.post(
        "/generate",
        data={
            "active_documents": str(document_id),
            "task": "summary",
            "query": "machine learning",
            "strategy": "fixed",
            "audience": "student",
            "tone": "clear",
            "output_format": "bullets",
            "creativity": "low",
            "instructions": "",
        },
        follow_redirects=True,
    )

    assert generate_response.status_code == 200
    assert b"Summary was generated and saved." in generate_response.data
    
    # Verify artifact was created
    with sqlite3.connect(db_path) as db:
        artifact = db.execute("SELECT * FROM artifacts WHERE kind = ?", ("summary",)).fetchone()
    assert artifact is not None
    # artifact is a tuple: (id, title, kind, content, created_at)
    assert "Summary" in artifact[1]  # title is index 1


def test_generate_explain_simple(tmp_path, monkeypatch):
    """Test simple explanation generation."""
    client, db_path = make_client(tmp_path, monkeypatch)
    content = (
        "Python is a high-level programming language. "
        "It emphasizes code readability and simplicity. "
        "Python supports multiple programming paradigms."
    )

    # Upload document
    upload_response = client.post(
        "/upload",
        data={"document": (BytesIO(content.encode("utf-8")), "python_guide.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert upload_response.status_code == 200

    # Get document ID
    with sqlite3.connect(db_path) as db:
        document_id = db.execute("SELECT id FROM documents WHERE filename = ?", ("python_guide.txt",)).fetchone()[0]

    # Generate simple explanation
    generate_response = client.post(
        "/generate",
        data={
            "active_documents": str(document_id),
            "task": "explain_simple",
            "query": "Python basics",
            "strategy": "fixed",
            "audience": "beginner",
            "tone": "friendly",
            "output_format": "narrative",
            "creativity": "low",
            "instructions": "",
        },
        follow_redirects=True,
    )

    assert generate_response.status_code == 200
    assert b"Explanation (Simple) was generated and saved." in generate_response.data
    
    # Verify artifact
    with sqlite3.connect(db_path) as db:
        artifact = db.execute("SELECT * FROM artifacts WHERE kind = ?", ("explain_simple",)).fetchone()
    assert artifact is not None
    assert "Explanation" in artifact[1]  # title is index 1


def test_generate_explain_detailed(tmp_path, monkeypatch):
    """Test detailed explanation generation."""
    client, db_path = make_client(tmp_path, monkeypatch)
    content = (
        "Flask is a lightweight web framework for Python. "
        "It provides routing, templating, and request handling. "
        "Flask applications can handle HTTP requests and return responses. "
        "Blueprint is a way to organize Flask applications into modules."
    )

    # Upload document
    upload_response = client.post(
        "/upload",
        data={"document": (BytesIO(content.encode("utf-8")), "flask_guide.txt")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert upload_response.status_code == 200

    # Get document ID
    with sqlite3.connect(db_path) as db:
        document_id = db.execute("SELECT id FROM documents WHERE filename = ?", ("flask_guide.txt",)).fetchone()[0]

    # Generate detailed explanation
    generate_response = client.post(
        "/generate",
        data={
            "active_documents": str(document_id),
            "task": "explain_detailed",
            "query": "Flask framework",
            "strategy": "fixed",
            "audience": "developer",
            "tone": "technical",
            "output_format": "detailed",
            "creativity": "medium",
            "instructions": "",
        },
        follow_redirects=True,
    )

    assert generate_response.status_code == 200
    assert b"Explanation (Detailed) was generated and saved." in generate_response.data
    
    # Verify artifact contains detailed structure
    with sqlite3.connect(db_path) as db:
        artifact = db.execute("SELECT * FROM artifacts WHERE kind = ?", ("explain_detailed",)).fetchone()
    assert artifact is not None
    assert "Explanation" in artifact[1]  # title is index 1
    # Check for detailed structure markers in content (index 3)
    assert any(marker in artifact[3] for marker in ["Overview", "Details", "Concepts", "Evidence"])


def test_summary_function_with_empty_chunks():
    """Test that summary function handles empty chunks gracefully."""
    steering = {
        "audience": "student",
        "tone": "clear",
        "output_format": "bullets",
        "creativity": "low",
        "instructions": "none"
    }
    result = generate_summary([], steering)
    assert "Summary" in result
    assert "No relevant content" in result


def test_explain_function_with_retrieved_chunks():
    """Test that explain function produces different outputs for simple vs detailed."""
    chunks = [
        {
            "document": "test.txt",
            "chunk": "This is test content about an important concept. The concept involves multiple layers of understanding. First, there is a foundational layer. Second, there is an application layer. Third, there is an advanced layer. Each layer builds on the previous.",
            "strategy": "fixed",
            "confidence": "high",
            "matched_terms": ["test", "content", "concept"]
        },
        {
            "document": "test2.txt",
            "chunk": "The implementation of this concept requires careful planning. Testing is essential for validation. Documentation helps future maintainers. Performance metrics should be tracked throughout development.",
            "strategy": "fixed",
            "confidence": "medium",
            "matched_terms": ["implementation", "testing"]
        }
    ]
    steering = {
        "audience": "student",
        "tone": "clear",
        "output_format": "narrative",
        "creativity": "low",
        "instructions": "none"
    }
    
    simple = generate_explain(chunks, steering, detail_level="simple")
    detailed = generate_explain(chunks, steering, detail_level="detailed")
    
    assert "Explanation (Simple Overview)" in simple
    assert "Explanation (Detailed)" in detailed
    # Detailed should have more structured sections
    assert "1. Overview" in detailed
    assert "2. Supporting Details" in detailed or "2. Key Concepts" in detailed


def test_high_creativity_quiz_changes_question_style():
    quiz = generate_quiz(
        [
            {
                "chunk": (
                    "Corpus Forge uses BM25 retrieval diagnostics, confidence labels, "
                    "matched terms, and grounded evidence to make generated answers auditable."
                )
            }
        ],
        {
            "audience": "capstone examiner",
            "tone": "polished academic",
            "output_format": "structured quiz",
            "creativity": "high",
            "instructions": "make the questions challenging but grounded",
        },
    )

    assert "Creativity: high" in quiz
    assert "Question style: scenario-based" in quiz
    assert "Scenario: a reviewer" in quiz
    assert "unsupported assumptions" in quiz


def test_artifact_generation_deduplicates_compare_evidence():
    chunks = [
        {"chunk": "Repeated retrieval evidence supports grounded quiz generation."},
        {"chunk": "Repeated retrieval evidence supports grounded quiz generation."},
    ]

    assert unique_evidence_text(chunks) == "Repeated retrieval evidence supports grounded quiz generation."


def test_dashboard_counts_all_artifacts_not_only_recent_ten(tmp_path, monkeypatch):
    client, db_path = make_client(tmp_path, monkeypatch)
    with sqlite3.connect(db_path) as db:
        for index in range(12):
            db.execute(
                "INSERT INTO artifacts (title, kind, content, created_at) VALUES (?, ?, ?, ?)",
                (f"Artifact {index}", "test", "content", "2026-05-22 00:00:00"),
            )
        db.commit()

    payload = client.get("/api/stats").get_json()

    assert payload["stats"]["artifact_count"] == 12

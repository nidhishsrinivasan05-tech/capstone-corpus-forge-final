import os
import logging
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for, jsonify
from werkzeug.utils import secure_filename

from .document_processing import DocumentProcessingError, allowed_file
from .processor import process_uploaded_file, process_github_repo, ingest
from .github_fetcher import (
    GitHubFetchError,
    RateLimitError,
    RepoNotFoundError,
    InvalidURLError
)
from .generator import answer_question, architecture_report, code_review, generate_flashcards, generate_quiz, generate_summary, generate_explain
from .llm import (
    GeminiError,
    build_answer_prompt,
    build_artifact_prompt,
    build_assistant_prompt,
    gemini_generate,
    gemini_is_enabled,
)
from .retrieval import (
    choose_retrieval_engine,
    corpus_word_count,
    complexity_threshold,
    estimate_tokens,
    retrieval_diagnostics,
    retrieve,
    top_terms,
)
from .vector_store import VectorStoreError, chroma_is_available, chroma_retrieval
from .llm import GeminiError as _GeminiError
from .storage import add_usage, get_connection, now

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


def retrieve_grounded(documents, query, strategy, creativity, api_key=None):
    """Route retrieval between the local BM25 engine and the ChromaDB vector engine.

    Small / simple corpora (below the creativity-adjusted word threshold) use the
    local BM25 retriever. Larger / more complex corpora use ChromaDB semantic
    vector retrieval backed by the Google GenAI embeddings API. If the vector
    path is unavailable (chromadb missing, no API key, or any runtime error) the
    function transparently falls back to local retrieval so the app keeps working.

    Returns a tuple of (retrieved_chunks, engine_used) where engine_used is one of
    "chromadb vector" or "local bm25".
    """
    engine = choose_retrieval_engine(documents, creativity)
    if engine == "chroma" and chroma_is_available() and gemini_is_enabled(api_key):
        try:
            retrieved = chroma_retrieval(documents, query, api_key=api_key)
            if retrieved:
                return retrieved, "chromadb vector"
            # No vector hits: fall through to local retrieval as a safety net.
        except (VectorStoreError, _GeminiError) as error:
            logger.warning("ChromaDB retrieval failed, falling back to local: %s", error)
    return retrieve(documents, query, strategy), "local bm25"


def enrich_documents(rows):
    """Enrich document records with computed fields for display."""
    documents = []
    for row in rows:
        document = dict(row)
        words = document.get("text", "").split()
        document["word_count"] = len(words)
        full = document.get("text", "")

        # Create short preview (~100 chars or 2 lines)
        text_for_preview = " ".join(words)
        if len(text_for_preview) > 120:
            # Find a good break point
            short = text_for_preview[:117].rsplit(" ", 1)[0] + "..."
        else:
            short = text_for_preview

        document["short_preview"] = short
        document["full_preview"] = full
        document["is_code"] = _is_code_file(document.get("filename", ""))

        documents.append(document)
    return documents


def _is_code_file(filename: str) -> bool:
    """Check if file is a code file for syntax styling."""
    code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".go", ".rb", ".php"}
    ext = os.path.splitext(filename)[1].lower()
    return ext in code_exts


def dashboard_context(selected_ids=None, **extra):
    selected_ids = selected_ids or set()
    with get_connection() as db:
        documents = enrich_documents(db.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall())
        artifacts = db.execute("SELECT * FROM artifacts ORDER BY created_at DESC LIMIT 10").fetchall()
        artifact_count = db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        usage = db.execute("SELECT * FROM usage_stats WHERE id = 1").fetchone()
    stats = {
        "document_count": len(documents),
        "artifact_count": artifact_count,
        "indexed_words": sum(document["word_count"] for document in documents),
        "selected_count": len(selected_ids),
    }
    context = {
        "documents": documents,
        "artifacts": artifacts,
        "usage": usage,
        "stats": stats,
        "selected_ids": selected_ids,
        "assistant_messages": session.get("assistant_messages", []),
    }
    context.update(extra)
    return context


def _save_assistant_messages(messages):
    session["assistant_messages"] = messages[-16:]
    session.modified = True


def get_documents_by_ids(ids):
    clean_ids = []
    for value in ids:
        try:
            clean_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not clean_ids:
        return []
    placeholders = ",".join("?" for _ in clean_ids)
    with get_connection() as db:
        rows = db.execute(
            f"SELECT * FROM documents WHERE id IN ({placeholders}) ORDER BY created_at DESC",
            clean_ids,
        ).fetchall()
    return [dict(row) for row in rows]


def steering_from_form():
    return {
        "audience": request.form.get("audience", "beginner student"),
        "tone": request.form.get("tone", "clear and direct"),
        "output_format": request.form.get("output_format", "structured bullets"),
        "creativity": request.form.get("creativity", "low"),
        "instructions": request.form.get("instructions", ""),
    }


def _is_ajax():
    """Check if request is AJAX (XMLHttpRequest)."""
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _json_error(message: str, status: int = 400):
    """Return JSON error response."""
    return jsonify({"status": "error", "error": message}), status


def _json_success(count: int, message: str = None):
    """Return JSON success response."""
    return jsonify({
        "status": "ok",
        "count": count,
        "message": message or f"{count} documents added"
    })


@bp.route("/")
def index():
    return render_template("index.html", **dashboard_context())


@bp.route("/upload", methods=["POST"])
def upload():
    uploaded_file = request.files.get("document")
    if not uploaded_file or uploaded_file.filename == "":
        msg = "Choose a document before uploading."
        if _is_ajax():
            return _json_error(msg)
        flash(msg, "warning")
        return redirect(url_for("main.index"))

    filename = secure_filename(uploaded_file.filename)

    if not allowed_file(filename):
        msg = f"Unsupported file type '{os.path.splitext(filename)[1]}'. Use txt, md, pdf, py, js, html, css, java, c, cpp, json, or xml."
        if _is_ajax():
            return _json_error(msg)
        flash(msg, "error")
        return redirect(url_for("main.index"))

    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    counter = 1
    base, extension = os.path.splitext(filename)
    while os.path.exists(path):
        filename = f"{base}_{counter}{extension}"
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
        counter += 1

    uploaded_file.save(path)
    logger.info(f"Saved uploaded file: {filename}")

    try:
        doc = process_uploaded_file(path)
    except DocumentProcessingError as error:
        logger.error(f"Failed to process uploaded file: {error}")
        if os.path.exists(path):
            os.remove(path)
        msg = f"Could not process file: {error}"
        if _is_ajax():
            return _json_error(msg)
        flash(msg, "error")
        return redirect(url_for("main.index"))

    with get_connection() as db:
        db.execute(
            "INSERT INTO documents (filename, filetype, path, text, created_at) VALUES (?, ?, ?, ?, ?)",
            (doc["filename"], doc["filetype"], path, doc["text"], now()),
        )
        db.commit()

    msg = f"{filename} was added to the corpus."
    logger.info(msg)

    if _is_ajax():
        return _json_success(1, msg)
    flash(msg, "success")
    return redirect(url_for("main.index"))


@bp.route('/import_repo', methods=['POST'])
def import_repo():
    """
    Import documents from a GitHub repository.

    Accepts both form POST and AJAX (X-Requested-With: XMLHttpRequest).
    """
    repo_url = request.form.get('repo_url', '').strip()
    token = request.form.get('github_token', '').strip() or None

    if not repo_url:
        msg = 'Provide a GitHub repository URL.'
        if _is_ajax():
            return _json_error(msg)
        flash(msg, "warning")
        return redirect(url_for('main.index'))

    # Determine if this is an AJAX request
    ajax = _is_ajax()

    try:
        docs = process_github_repo(
            repo_url,
            token=token,
            upload_folder=current_app.config['UPLOAD_FOLDER']
        )
    except InvalidURLError as e:
        logger.warning(f"Invalid GitHub URL: {repo_url} - {e}")
        msg = f"Invalid GitHub URL: {e}"
        if ajax:
            return _json_error(msg)
        flash(msg, "error")
        return redirect(url_for("main.index"))

    except RepoNotFoundError as e:
        logger.warning(f"Repository not found: {repo_url} - {e}")
        msg = f"Repository not found. Check the URL and ensure the repo is public or you have access."
        if ajax:
            return _json_error(msg)
        flash(msg, "error")
        return redirect(url_for("main.index"))

    except RateLimitError as e:
        logger.warning(f"GitHub rate limit exceeded: {repo_url} - {e}")
        msg = "GitHub API rate limit exceeded. Try again later or provide a GitHub token."
        if ajax:
            return _json_error(msg, 429)  # Too Many Requests
        flash(msg, "error")
        return redirect(url_for("main.index"))

    except GitHubFetchError as e:
        logger.error(f"GitHub fetch error: {repo_url} - {e}")
        msg = f"Could not fetch repository: {e}"
        if ajax:
            return _json_error(msg)
        flash(msg, "error")
        return redirect(url_for("main.index"))

    if not docs:
        msg = "No supported files were found or processed from the repository."
        if ajax:
            return _json_error(msg)
        flash(msg, "warning")
        return redirect(url_for("main.index"))

    # Insert docs into DB
    with get_connection() as db:
        for doc in docs:
            db.execute(
                "INSERT INTO documents (filename, filetype, path, text, created_at) VALUES (?, ?, ?, ?, ?)",
                (doc['filename'], doc['filetype'], doc.get('path', ''), doc['text'], now()),
            )
        db.commit()

    msg = f"Imported {len(docs)} files from repository."
    logger.info(msg)

    if ajax:
        return _json_success(len(docs), msg)
    flash(msg, "success")
    return redirect(url_for("main.index"))


@bp.route("/api/ingest", methods=["POST"])
def api_ingest():
    """
    API endpoint for unified ingestion.

    Expects JSON body:
    {
        "source_type": "file" | "github",
        "data": { ... source-specific data ... }
    }

    For file:
        {"source_type": "file", "data": {"path": "/path/to/file"}}

    For GitHub:
        {"source_type": "github", "data": {"url": "https://github.com/owner/repo", "token": "optional"}}
    """
    if not request.is_json:
        return jsonify({"status": "error", "error": "Expected JSON body"}), 400

    body = request.get_json()
    source_type = body.get("source_type")
    data = body.get("data", {})

    if not source_type:
        return jsonify({"status": "error", "error": "Missing source_type"}), 400

    try:
        docs = ingest(
            source_type,
            data,
            upload_folder=current_app.config["UPLOAD_FOLDER"]
        )
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 400
    except DocumentProcessingError as e:
        return jsonify({"status": "error", "error": f"Processing error: {e}"}), 400
    except RateLimitError as e:
        return jsonify({"status": "error", "error": str(e)}), 429
    except RepoNotFoundError as e:
        return jsonify({"status": "error", "error": str(e)}), 404
    except GitHubFetchError as e:
        return jsonify({"status": "error", "error": f"GitHub error: {e}"}), 400

    # Store documents
    with get_connection() as db:
        for doc in docs:
            db.execute(
                "INSERT INTO documents (filename, filetype, path, text, created_at) VALUES (?, ?, ?, ?, ?)",
                (doc['filename'], doc['filetype'], doc.get('path', ''), doc['text'], now()),
            )
        db.commit()

    return jsonify({
        "status": "ok",
        "count": len(docs),
        "documents": [{"id": i+1, "filename": d['filename']} for i, d in enumerate(docs)]
    })


@bp.route("/delete/<int:document_id>", methods=["POST"])
def delete_document(document_id):
    with get_connection() as db:
        document = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if document:
            if os.path.exists(document["path"]):
                os.remove(document["path"])
            db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            db.commit()
            flash(f"{document['filename']} was removed.", "success")
        else:
            flash("Document not found.", "warning")
    return redirect(url_for("main.index"))


@bp.route("/chat", methods=["POST"])
def chat():
    ids = request.form.getlist("active_documents")
    question = request.form.get("question", "").strip()
    strategy = request.form.get("strategy", "fixed")
    steering = steering_from_form()
    documents = get_documents_by_ids(ids)
    selected_ids = set(int(item) for item in ids if item.isdigit()) if ids else set()
    if not selected_ids:
        flash("Select at least one active document for grounded answers.", "warning")
    retrieved, engine_used = retrieve_grounded(
        documents, question, strategy, steering.get("creativity", "low")
    )
    diagnostics = retrieval_diagnostics(documents, question, retrieved)
    diagnostics["engine"] = engine_used
    diagnostics["corpus_words"] = corpus_word_count(documents)
    diagnostics["complexity_threshold"] = complexity_threshold(steering.get("creativity", "low"))
    used_gemini = False
    answer = answer_question(question, retrieved, steering, diagnostics)
    if gemini_is_enabled():
        try:
            answer = gemini_generate(
                build_answer_prompt(question, retrieved, steering, diagnostics),
                creativity=steering.get("creativity", "low"),
            )
            used_gemini = True
        except GeminiError as error:
            flash(f"Gemini unavailable, used local fallback: {error}", "warning")
    add_usage(estimate_tokens(question + answer + " ".join(item["chunk"] for item in retrieved)))
    fallback_used = any(
        ("substring" in item.get("strategy", "") or "fuzzy" in item.get("strategy", ""))
        for item in retrieved
    )
    return render_template(
        "index.html",
        **dashboard_context(
            selected_ids=selected_ids,
            answer=answer,
            retrieved=retrieved,
            diagnostics=diagnostics,
            fallback_used=fallback_used,
            used_gemini=used_gemini,
        ),
    )


@bp.route("/assistant_chat", methods=["POST"])
def assistant_chat():
    message = request.form.get("assistant_message", "").strip()
    api_key = request.form.get("api_key", "").strip() or None
    model = request.form.get("model", "").strip() or None
    creativity = request.form.get("creativity", "low")
    history = list(session.get("assistant_messages", []))

    if not message:
        flash("Enter a message before chatting.", "warning")
        return redirect(url_for("main.index"))

    if not gemini_is_enabled(api_key):
        flash("Add a Gemini API key or set GEMINI_API_KEY before using assistant chat.", "warning")
        return render_template(
            "index.html",
            **dashboard_context(
                assistant_messages=history,
                assistant_error="Missing Gemini API key.",
            ),
        )

    try:
        prompt = build_assistant_prompt(message, history)
        reply = gemini_generate(
            prompt,
            creativity=creativity,
            api_key=api_key,
            model=model,
        )
    except GeminiError as error:
        flash(f"Assistant chat failed: {error}", "error")
        return render_template(
            "index.html",
            **dashboard_context(
                assistant_messages=history,
                assistant_error=str(error),
            ),
        )

    history.extend([
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ])
    _save_assistant_messages(history)
    add_usage(estimate_tokens(prompt + reply))

    return render_template(
        "index.html",
        **dashboard_context(
            assistant_messages=history,
            assistant_used_model=model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        ),
    )


@bp.route("/assistant_chat/clear", methods=["POST"])
def clear_assistant_chat():
    session.pop("assistant_messages", None)
    session.modified = True
    flash("Chat cleared.", "success")
    return redirect(url_for("main.index"))


@bp.route("/generate", methods=["POST"])
def generate():
    ids = request.form.getlist("active_documents")
    task = request.form.get("task", "flashcards")
    query = request.form.get("query", "main ideas")
    strategy = request.form.get("strategy", "fixed")
    steering = steering_from_form()
    documents = get_documents_by_ids(ids)
    if not documents:
        flash("Select at least one active document before generating an artifact.", "warning")
        return redirect(url_for("main.index"))
    retrieved, engine_used = retrieve_grounded(
        documents, query, strategy, steering.get("creativity", "low")
    )
    diagnostics = retrieval_diagnostics(documents, query, retrieved)
    diagnostics["engine"] = engine_used
    diagnostics["corpus_words"] = corpus_word_count(documents)
    diagnostics["complexity_threshold"] = complexity_threshold(steering.get("creativity", "low"))
    if not retrieved:
        flash(diagnostics["failure_reason"] or "No evidence found for this artifact.", "warning")
        return redirect(url_for("main.index"))
    
    if task == "quiz":
        content = generate_quiz(retrieved, steering)
        title = "Quiz"
    elif task == "summary":
        content = generate_summary(retrieved, steering)
        title = "Summary"
    elif task == "explain_simple":
        content = generate_explain(retrieved, steering, detail_level="simple")
        title = "Explanation (Simple)"
    elif task == "explain_detailed":
        content = generate_explain(retrieved, steering, detail_level="detailed")
        title = "Explanation (Detailed)"
    elif task == "code_review":
        content = code_review(documents, steering)
        title = "Code Review Report"
    elif task == "architecture":
        content = architecture_report(documents, steering)
        title = "Architecture and Control Flow Report"
    else:
        content = generate_flashcards(retrieved, steering)
        title = "Flashcards"

    if gemini_is_enabled():
        try:
            content = gemini_generate(
                build_artifact_prompt(task, query, retrieved, documents, steering),
                creativity=steering.get("creativity", "low"),
            )
            flash(f"{title} was generated using Gemini and saved.", "success")
        except GeminiError as error:
            flash(f"Gemini unavailable, used local fallback: {error}", "warning")

    add_usage(estimate_tokens(query + content + " ".join(item["chunk"] for item in retrieved)))
    with get_connection() as db:
        db.execute(
            "INSERT INTO artifacts (title, kind, content, created_at) VALUES (?, ?, ?, ?)",
            (title, task, content, now()),
        )
        db.commit()
    if not gemini_is_enabled():
        flash(f"{title} was generated and saved.", "success")
    return redirect(url_for("main.artifacts"))


@bp.route("/artifacts")
def artifacts():
    with get_connection() as db:
        rows = db.execute("SELECT * FROM artifacts ORDER BY created_at DESC").fetchall()
    return render_template("artifacts.html", artifacts=rows)


@bp.route("/visualization")
def visualization():
    with get_connection() as db:
        documents = [dict(row) for row in db.execute("SELECT * FROM documents").fetchall()]
    terms = top_terms(documents, 40)
    return render_template("visualization.html", terms=terms)


@bp.route('/api/stats')
def api_stats():
    """Return basic dashboard stats as JSON for live refresh."""
    ctx = dashboard_context()
    stats = ctx.get('stats', {})
    usage = ctx.get('usage')
    usage_dict = None
    try:
        usage_dict = dict(usage) if usage else None
    except Exception:
        usage_dict = None
    return jsonify({'stats': stats, 'usage': usage_dict})

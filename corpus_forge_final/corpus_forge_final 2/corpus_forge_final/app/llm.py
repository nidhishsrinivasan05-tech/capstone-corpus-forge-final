import os
import textwrap
import requests

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"

# Embedding model used for the ChromaDB vector-retrieval path.
DEFAULT_EMBED_MODEL = "gemini-embedding-001"


class GeminiError(RuntimeError):
    pass


def gemini_is_enabled(api_key: str | None = None) -> bool:
    return bool(api_key or os.environ.get("GEMINI_API_KEY"))


def _embed_model(model: str | None = None) -> str:
    return (model or os.environ.get("GEMINI_EMBED_MODEL", DEFAULT_EMBED_MODEL)).strip()


def gemini_embed_texts(
    texts: list[str],
    api_key: str | None = None,
    model: str | None = None,
) -> list[list[float]]:
    """Embed a list of texts with the Google GenAI embeddings API.

    Used by the ChromaDB vector store so that larger / more complex corpora are
    retrieved with semantic vector search instead of local BM25. Returns one
    embedding vector per input text, in order. Uses the ``embedContent`` endpoint
    (one request per text) which is the method supported by the gemini-embedding
    models.
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("Missing GEMINI_API_KEY")
    if not texts:
        return []

    model_name = _embed_model(model)
    qualified = model_name if model_name.startswith("models/") else f"models/{model_name}"
    url = GEMINI_EMBED_URL.format(model=model_name)
    headers = {"Content-Type": "application/json"}

    vectors: list[list[float]] = []
    for text in texts:
        payload = {
            "model": qualified,
            "content": {"parts": [{"text": text[:8000]}]},
        }
        try:
            response = requests.post(
                f"{url}?key={api_key}",
                headers=headers,
                json=payload,
                timeout=45,
            )
        except requests.RequestException as error:
            raise GeminiError(f"Gemini embedding request failed: {error}") from error

        if response.status_code >= 400:
            raise GeminiError(
                f"Gemini embedding API error {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        try:
            vectors.append([float(value) for value in data["embedding"]["values"]])
        except (KeyError, IndexError, TypeError) as error:
            raise GeminiError("Gemini embedding API returned an unexpected payload") from error

    if len(vectors) != len(texts):
        raise GeminiError("Gemini embedding count did not match the number of inputs")
    return vectors


def _gemini_model(model: str | None = None) -> str:
    return (model or os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")).strip()


def _gemini_temperature(creativity: str) -> float:
    value = (creativity or "low").lower()
    if value == "high":
        return 0.9
    if value == "medium":
        return 0.6
    return 0.2


def gemini_generate(
    prompt: str,
    creativity: str = "low",
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("Missing GEMINI_API_KEY")

    model_name = _gemini_model(model)
    url = GEMINI_API_URL.format(model=model_name)
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": _gemini_temperature(creativity),
            "maxOutputTokens": 2048,
        },
    }

    try:
        response = requests.post(
            f"{url}?key={api_key}",
            headers=headers,
            json=payload,
            timeout=35,
        )
    except requests.RequestException as error:
        raise GeminiError(f"Gemini request failed: {error}") from error

    if response.status_code >= 400:
        raise GeminiError(f"Gemini API error {response.status_code}: {response.text[:300]}")

    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as error:
        raise GeminiError("Gemini API returned an unexpected response payload") from error


def build_answer_prompt(question: str, retrieved: list[dict], steering: dict, diagnostics: dict | None) -> str:
    evidence = []
    for item in retrieved[:8]:
        evidence.append(
            f"Document: {item.get('document')} | Strategy: {item.get('strategy')} | "
            f"Score: {item.get('score')} | Chunk:\n{item.get('chunk', '')[:1200]}"
        )
    evidence_text = "\n\n".join(evidence) if evidence else "No evidence retrieved."

    diagnostics_line = ""
    if diagnostics:
        diagnostics_line = (
            f"Diagnostics: selected_docs={diagnostics.get('selected_documents')}, "
            f"results={diagnostics.get('results_returned')}, top_score={diagnostics.get('top_score')}."
        )

    return textwrap.dedent(
        f"""
        You are a retrieval-grounded assistant. Use ONLY the evidence below.
        If evidence is insufficient, explicitly say so.

        Style:
        - Audience: {steering.get('audience')}
        - Tone: {steering.get('tone')}
        - Format: {steering.get('output_format')}
        - Extra instructions: {steering.get('instructions') or 'none'}

        User question:
        {question}

        {diagnostics_line}

        Evidence:
        {evidence_text}

        Output format:
        1) Direct answer
        2) Evidence bullets with document names
        3) If uncertain, say exactly what is missing
        """
    ).strip()


def build_artifact_prompt(task: str, query: str, retrieved: list[dict], documents: list[dict], steering: dict) -> str:
    task_map = {
        "flashcards": "Create high quality flashcards with question-answer pairs",
        "quiz": "Create a multiple-choice quiz with 4-5 questions and clear answer explanations",
        "summary": "Create a concise summary extracting the main ideas and key concepts from the provided content",
        "explain_simple": "Create a simple, high-level explanation suitable for quick understanding with 1-2 key takeaways",
        "explain_detailed": "Create a detailed explanation with multiple sections: Overview, Supporting Details, Key Concepts, and Evidence Summary",
        "code_review": "Create a code review report",
        "architecture": "Create an architecture and control-flow report",
    }
    instruction = task_map.get(task, "Create an artifact")

    evidence = []
    for item in retrieved[:10]:
        evidence.append(f"[{item.get('document')}] {item.get('chunk', '')[:1100]}")

    if not evidence:
        for doc in documents[:4]:
            evidence.append(f"[{doc.get('filename')}] {doc.get('text', '')[:1400]}")
    evidence_text = "\n\n".join(evidence)

    return textwrap.dedent(
        f"""
        You are generating a corpus-grounded artifact for a software-engineering study tool.
        {instruction} grounded strictly in the provided corpus evidence.

        Focus query: {query}

        Style:
        - Audience: {steering.get('audience')}
        - Tone: {steering.get('tone')}
        - Format: {steering.get('output_format')}
        - Extra instructions: {steering.get('instructions') or 'none'}

        Evidence:
        {evidence_text}

        Requirements:
        - Do not invent sources.
        - Mention file names when relevant.
        - Keep content practical and clear.
        """
    ).strip()


def build_assistant_prompt(message: str, history: list[dict] | None = None) -> str:
    history_lines = []
    for item in (history or [])[-10:]:
        role = "User" if item.get("role") == "user" else "Assistant"
        content = str(item.get("content", "")).strip()
        if content:
            history_lines.append(f"{role}: {content}")

    history_text = "\n".join(history_lines) if history_lines else "No previous messages."

    return textwrap.dedent(
        f"""
        You are the Corpus Forge chat assistant.
        Help the user clearly and practically. If the user asks for code, be specific.
        Do not claim to have read uploaded documents unless the user provides their content in chat.

        Conversation so far:
        {history_text}

        New user message:
        {message}

        Reply as the assistant.
        """
    ).strip()

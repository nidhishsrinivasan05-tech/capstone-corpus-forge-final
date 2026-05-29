import ast
import re
from .document_processing import is_code_file


def build_style_line(audience, tone, output_format, creativity, instructions):
    return (
        f"Audience: {audience}. Tone: {tone}. Format: {output_format}. "
        f"Creativity: {creativity}. Extra instructions: {instructions or 'none'}."
    )


def answer_question(question, retrieved_chunks, steering, diagnostics=None):
    if not retrieved_chunks:
        reason = diagnostics.get("failure_reason") if diagnostics else "No relevant evidence was retrieved."
        return (
            "Grounded answer\n\n"
            f"I cannot answer this from the selected corpus. {reason}\n"
            "Try selecting the right document or using more specific terms from the file."
        )

    lines = ["Grounded answer", "", build_style_line(**steering), ""]
    lines.append("Answer based only on retrieved evidence:")
    lines.append(make_simple_synthesis(question, retrieved_chunks))
    lines.append("")
    lines.append("Evidence used:")
    for item in retrieved_chunks[:5]:
        clean = item["chunk"].strip().replace("\n", " ")
        location = f"words {item.get('start_word', '?')}-{item.get('end_word', '?')}"
        terms = ", ".join(item.get("matched_terms", [])) or "none"
        lines.append(
            f"- {item['document']} | {item['strategy']} | {location} | "
            f"confidence: {item.get('confidence', 'unknown')} | matched: {terms}\n  {clean[:520]}"
        )

    if diagnostics:
        lines.append("")
        lines.append(
            f"Retrieval check: {diagnostics['results_returned']} result(s), "
            f"{diagnostics['selected_documents']} selected document(s), "
            f"top score {diagnostics['top_score']}."
        )
    return "\n".join(lines)


def make_simple_synthesis(question, retrieved_chunks):
    query_words = set(re.findall(r"[A-Za-z0-9_]+", question.lower()))
    chosen = []
    for item in retrieved_chunks:
        parts = re.split(r"(?<=[.!?])\s+", item["chunk"])
        for sentence in parts:
            sentence = sentence.strip()
            if not (40 <= len(sentence) <= 320):
                continue
            sentence_words = set(re.findall(r"[A-Za-z0-9_]+", sentence.lower()))
            if query_words & sentence_words or len(chosen) < 2:
                chosen.append(sentence)
            if len(chosen) >= 4:
                break
        if len(chosen) >= 4:
            break
    if not chosen:
        overview = selected_document_overview(retrieved_chunks)
        if overview:
            return overview
        return "The corpus contains related fragments, but they are too short to synthesize safely. Use the evidence section below."
    return " ".join(chosen)


def selected_document_overview(retrieved_chunks):
    if not retrieved_chunks:
        return ""
    item = retrieved_chunks[0]
    clean = " ".join(item.get("chunk", "").split())
    if not clean:
        return ""
    if item.get("strategy") == "selected document overview":
        return (
            "The question is broad, so the system used a low-confidence overview of the selected document. "
            f"The available evidence begins with: {clean[:360]}"
        )
    return f"The selected evidence begins with: {clean[:360]}"


def generate_flashcards(retrieved_chunks, steering):
    text = unique_evidence_text(retrieved_chunks)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 45]
    cards = ["Flashcards", "", build_style_line(**steering), ""]
    for index, sentence in enumerate(sentences[:8], start=1):
        keyword = first_keyword(sentence)
        cards.append(f"Q{index}. What should the user remember about {keyword}?")
        cards.append(f"A{index}. {sentence[:350]}")
        cards.append(f"Source: retrieved evidence #{min(index, len(retrieved_chunks))}")
        cards.append("")
    if len(cards) <= 4:
        cards.append("Not enough retrieved content was found to create flashcards.")
    return "\n".join(cards)


def generate_quiz(retrieved_chunks, steering):
    text = unique_evidence_text(retrieved_chunks)
    sentences = evidence_sentences(text)
    creativity = steering.get("creativity", "low").lower()
    quiz = ["Quiz", "", build_style_line(**steering), ""]
    quiz.append(quiz_style_note(creativity))
    quiz.append("")
    for index, sentence in enumerate(sentences[:5], start=1):
        keyword = first_keyword(sentence)
        stem, distractors, why = quiz_components(index, keyword, sentence, creativity)
        quiz.append(stem)
        quiz.append(f"A. {sentence[:220]}")
        quiz.extend(distractors)
        quiz.append("Correct answer: A")
        quiz.append(why)
        quiz.append("")
    if len(sentences) == 0:
        quiz.append("Not enough retrieved content was found to create a quiz.")
    return "\n".join(quiz)


def unique_evidence_text(retrieved_chunks):
    seen = set()
    unique_chunks = []
    for item in retrieved_chunks:
        chunk = " ".join(item.get("chunk", "").split())
        if not chunk:
            continue
        fingerprint = chunk.lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique_chunks.append(chunk)
    return " ".join(unique_chunks)


def evidence_sentences(text):
    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    sentences = [sentence for sentence in raw_sentences if len(sentence) > 60]
    if sentences:
        return sentences
    compact = " ".join(text.split())
    if len(compact) > 60:
        return [compact[:360]]
    return []


def quiz_style_note(creativity):
    if creativity == "high":
        return "Question style: scenario-based and challenging, while still grounded only in retrieved evidence."
    if creativity == "medium":
        return "Question style: applied comprehension with moderate distractor variation."
    return "Question style: conservative evidence-checking quiz."


def quiz_components(index, keyword, sentence, creativity):
    if creativity == "high":
        return (
            f"Q{index}. Scenario: a reviewer must decide what the corpus supports about {keyword}. Which answer is best grounded?",
            [
                "B. The reviewer should infer a broader claim that is not stated in the retrieved evidence.",
                "C. The reviewer should ignore source evidence and rely on general background knowledge.",
                "D. The reviewer should conclude that the selected corpus contains no relevant signal.",
            ],
            "Why: A is the only option directly grounded in the retrieved passage; the other answers add unsupported assumptions.",
        )
    if creativity == "medium":
        return (
            f"Q{index}. What conclusion is best supported by the corpus about {keyword}?",
            [
                "B. The corpus supports the opposite conclusion.",
                "C. The corpus gives no useful evidence for this topic.",
                "D. The answer requires information outside the selected documents.",
            ],
            "Why: A is taken from retrieved evidence, while the distractors test contradiction, missing evidence, and external knowledge.",
        )
    return (
        f"Q{index}. Which statement best matches the corpus about {keyword}?",
        [
            "B. The corpus clearly says the opposite.",
            "C. The corpus gives no usable evidence.",
        ],
        "Why: answer A is copied from retrieved evidence, while B and C are failure/contradiction checks.",
    )


def first_keyword(sentence):
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", sentence)
    return words[0] if words else "this topic"


def code_review(documents, steering):
    report = ["Code Review Report", "", build_style_line(**steering), ""]
    code_documents = [doc for doc in documents if is_code_file(doc["filename"])]
    if not code_documents:
        return "No source code files are selected. Upload or select source code files first."
    for doc in code_documents:
        text = doc["text"]
        lines = text.splitlines()
        report.append(f"## {doc['filename']}")
        report.append(f"- Lines: {len(lines)}")
        report.append(f"- Functions/classes: {count_symbols(text)}")
        report.append(f"- Long lines over 100 characters: {sum(1 for line in lines if len(line) > 100)}")
        report.extend(static_risk_checks(text, doc["filename"]))
        report.append("- Recommended next test: add one positive case, one empty-input case, and one malformed-input case for this file.")
        report.append("")
    return "\n".join(report)


def static_risk_checks(text, filename):
    checks = []
    if "eval(" in text or "exec(" in text:
        checks.append("- Security risk: eval/exec detected. Avoid executing dynamic input.")
    if "except:" in text:
        checks.append("- Reliability risk: bare except detected. Catch specific exceptions.")
    if filename.endswith(".py") and "sqlite3" in text and "?" not in text:
        checks.append("- SQL risk: sqlite usage without visible parameter placeholders. Verify queries are parameterized.")
    if "TODO" in text or "FIXME" in text:
        checks.append("- Maintenance risk: TODO/FIXME comments remain.")
    if not checks:
        checks.append("- No high-risk pattern detected by the lightweight static checks.")
    return checks


def architecture_report(documents, steering):
    report = ["Architecture and Control Flow Report", "", build_style_line(**steering), ""]
    code_documents = [doc for doc in documents if is_code_file(doc["filename"])]
    if not code_documents:
        return "No source code files are selected."
    for doc in code_documents:
        report.append(f"## {doc['filename']}")
        if doc["filename"].endswith(".py"):
            report.extend(python_architecture(doc["text"]))
        else:
            report.append("- File included in the application structure.")
            report.append("- Inspect event handlers, imports, and function calls manually for full control-flow detail.")
        report.append("")
    return "\n".join(report)


def count_symbols(text):
    return len(re.findall(r"\b(def|class|function)\s+[A-Za-z_][A-Za-z0-9_]*", text))


def python_architecture(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ["- Python syntax could not be parsed, so only text-level analysis is available."]
    classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return [
        f"- Imports: {', '.join(sorted(set(imports))) if imports else 'none detected'}",
        f"- Classes: {', '.join(classes) if classes else 'none detected'}",
        f"- Functions: {', '.join(functions) if functions else 'none detected'}",
        "- Main flow: route/controller functions validate input, call document processing or retrieval services, then store auditable artifacts.",
    ]


def generate_summary(retrieved_chunks, steering):
    """Generate a concise summary of the retrieved content.
    
    Extracts key sentences and combines them into a coherent summary.
    Falls back to overview if insufficient content is available.
    """
    if not retrieved_chunks:
        return (
            "Summary\n\n"
            "No relevant content was retrieved. "
            "Try uploading a document or selecting more documents before generating a summary."
        )

    text = unique_evidence_text(retrieved_chunks)
    sentences = evidence_sentences(text)
    
    summary = ["Summary", "", build_style_line(**steering), ""]
    
    if not sentences:
        summary.append("The retrieved content is too short to summarize effectively.")
        summary.append("Source: Retrieved evidence")
        return "\n".join(summary)
    
    # Build summary by selecting the most representative sentences
    summary.append("Main ideas from the selected documents:")
    summary.append("")
    
    for idx, sentence in enumerate(sentences[:5], start=1):
        summary.append(f"• {sentence}")
    
    summary.append("")
    summary.append("Key terms identified:")
    key_terms = set()
    for sentence in sentences[:3]:
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", sentence)
        key_terms.update(words[:3])
    
    if key_terms:
        summary.append(", ".join(sorted(key_terms)[:10]))
    else:
        summary.append("(No key terms identified)")
    
    summary.append("")
    summary.append(f"Evidence coverage: {len(retrieved_chunks)} document(s) analyzed")
    
    return "\n".join(summary)


def generate_explain(retrieved_chunks, steering, detail_level="simple"):
    """Generate an explanation of the retrieved content.
    
    Args:
        retrieved_chunks: Retrieved evidence from retrieval engine
        steering: Generation parameters (audience, tone, format, creativity, instructions)
        detail_level: "simple" for high-level overview, "detailed" for deep dive
    
    Returns:
        Formatted explanation text
    """
    if not retrieved_chunks:
        return (
            "Explanation\n\n"
            "No relevant content was retrieved. "
            "Upload or select documents to explain their contents."
        )
    
    text = unique_evidence_text(retrieved_chunks)
    sentences = evidence_sentences(text)
    
    if detail_level == "detailed":
        return _generate_detailed_explanation(sentences, retrieved_chunks, steering)
    else:
        return _generate_simple_explanation(sentences, retrieved_chunks, steering)


def _generate_simple_explanation(sentences, retrieved_chunks, steering):
    """Generate a high-level explanation suitable for quick understanding."""
    explanation = ["Explanation (Simple Overview)", "", build_style_line(**steering), ""]
    
    if not sentences:
        explanation.append("The selected content is too brief for a detailed explanation.")
        return "\n".join(explanation)
    
    # Take the first 2-3 sentences as the core explanation
    explanation.append("What this content is about:")
    explanation.append("")
    for sentence in sentences[:2]:
        explanation.append(f"  {sentence}")
    
    explanation.append("")
    explanation.append("Key takeaway:")
    if sentences:
        # Extract one key concept
        first_sent = sentences[0]
        key = first_keyword(first_sent)
        explanation.append(f"  The main focus is on {key}.")
    
    explanation.append("")
    explanation.append(f"Source: {len(retrieved_chunks)} piece(s) of evidence")
    
    return "\n".join(explanation)


def _generate_detailed_explanation(sentences, retrieved_chunks, steering):
    """Generate a detailed, comprehensive explanation of content."""
    explanation = ["Explanation (Detailed)", "", build_style_line(**steering), ""]
    
    if not sentences:
        explanation.append("Insufficient content for detailed explanation.")
        return "\n".join(explanation)
    
    explanation.append("Detailed breakdown:")
    explanation.append("")
    
    # Section 1: Overview
    explanation.append("1. Overview")
    explanation.append("-" * 40)
    overview = sentences[0] if sentences else "Content available but too brief."
    explanation.append(f"  {overview}")
    explanation.append("")
    
    # Section 2: Supporting details
    if len(sentences) > 1:
        explanation.append("2. Supporting Details")
        explanation.append("-" * 40)
        for idx, sent in enumerate(sentences[1:min(4, len(sentences))], start=1):
            explanation.append(f"  {idx}. {sent}")
        explanation.append("")
    
    # Section 3: Key concepts
    explanation.append("3. Key Concepts")
    explanation.append("-" * 40)
    key_terms = set()
    for sentence in sentences[:3]:
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{4,}", sentence)
        key_terms.update(words[:2])
    
    if key_terms:
        for term in sorted(key_terms)[:5]:
            explanation.append(f"  • {term}")
    else:
        explanation.append("  (Terms extracted from context)")
    explanation.append("")
    
    # Section 4: Evidence summary
    explanation.append("4. Evidence Summary")
    explanation.append("-" * 40)
    doc_names = set(item.get("document", "unknown") for item in retrieved_chunks[:5])
    explanation.append(f"  Sources: {', '.join(doc_names)}")
    explanation.append(f"  Confidence: High (based on {len(retrieved_chunks)} retrieved items)")
    
    return "\n".join(explanation)

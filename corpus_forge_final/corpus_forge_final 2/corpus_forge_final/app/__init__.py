import os
from flask import Flask
from .document_processing import MAX_FILE_SIZE_BYTES
from .routes import bp
from .storage import init_db


def _load_env():
    """Load environment variables from a local .env file if present.

    Keeps secrets like GEMINI_API_KEY out of source code. The .env file is
    gitignored, so it never reaches the public team repository.
    """
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv()


def create_app():
    _load_env()
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = os.environ.get("CORPUS_FORGE_SECRET", "corpus-forge-dev-key")
    app.config["UPLOAD_FOLDER"] = os.environ.get("CORPUS_FORGE_UPLOADS", "data/uploads")
    app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE_BYTES
    init_db()
    app.register_blueprint(bp)
    return app

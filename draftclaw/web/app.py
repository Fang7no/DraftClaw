"""
DraftClaw Web UI - Flask Application
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, redirect
from flask_cors import CORS

from web.api import register_routes


def create_app():
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB max upload
    CORS(app)

    # Register API routes
    register_routes(app)

    # Serve Vue app
    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/task/<task_id>")
    def task_page(task_id):
        return redirect(f"/#/task/{task_id}")

    return app


if __name__ == "__main__":
    app = create_app()
    host = os.getenv("DRAFTCLAW_WEB_HOST", "0.0.0.0")
    port = int(os.getenv("DRAFTCLAW_WEB_PORT", "5000"))
    debug = os.getenv("DRAFTCLAW_WEB_DEBUG", "true").strip().lower() == "true"
    use_reloader = os.getenv(
        "DRAFTCLAW_WEB_RELOAD",
        "true" if debug else "false",
    ).strip().lower() == "true"
    app.run(debug=debug, host=host, port=port, use_reloader=use_reloader)

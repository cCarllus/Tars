"""Flask application factory for the private TARS Dashboard."""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from flask import Flask

from bot.config import settings
from bot.logger import logger
from bot.services.core_config_service import CoreConfigService, core_config_service
from dashboard.blueprints.auth import auth_blueprint
from dashboard.blueprints.config import config_blueprint
from dashboard.security import csrf_token

DASHBOARD_AUDIT_LOG = Path("dashboard/dashboard_audit.log")


def create_app(config_service: CoreConfigService | None = None) -> Flask:
    """Create and configure the Flask Dashboard application."""

    app = Flask(__name__)
    app.secret_key = settings.dashboard_secret_key or secrets.token_hex(32)
    app.extensions["core_config_service"] = config_service or core_config_service

    _configure_dashboard_audit_logger()
    app.jinja_env.globals["csrf_token"] = csrf_token

    app.register_blueprint(auth_blueprint)
    app.register_blueprint(config_blueprint)
    return app


def _configure_dashboard_audit_logger() -> None:
    DASHBOARD_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    audit_logger = logging.getLogger("tars.dashboard.audit")
    audit_logger.setLevel(logging.INFO)

    if any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == DASHBOARD_AUDIT_LOG.resolve()
        for handler in audit_logger.handlers
    ):
        return

    handler = logging.FileHandler(DASHBOARD_AUDIT_LOG, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    audit_logger.addHandler(handler)
    logger.info("Dashboard audit log configured at %s", DASHBOARD_AUDIT_LOG)


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)

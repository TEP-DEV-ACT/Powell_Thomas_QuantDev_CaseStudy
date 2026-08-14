import logging

from flask import Blueprint, render_template

from tracker.config import UNIVERSE
from tracker.logging_config import get_recent_logs

logger = logging.getLogger(__name__)

ui = Blueprint("ui", __name__)


@ui.get("/")
def index():
    logger.info("GET / (dashboard load)")
    return render_template("index.html", universe=UNIVERSE)


@ui.get("/logs")
def logs():
    return render_template("logs.html", records=get_recent_logs())

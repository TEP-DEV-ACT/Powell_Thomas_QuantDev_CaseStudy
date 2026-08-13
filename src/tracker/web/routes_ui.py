from flask import Blueprint, render_template

from tracker.config import UNIVERSE

ui = Blueprint("ui", __name__)


@ui.get("/")
def index():
    return render_template("index.html", universe=UNIVERSE)

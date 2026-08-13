from flask import Flask

from tracker.web.jsonutil import TrackerJSONProvider
from tracker.web.routes_api import api
from tracker.web.routes_ui import ui


def create_app() -> Flask:
    app = Flask(__name__)
    app.json = TrackerJSONProvider(app)
    app.register_blueprint(ui)
    app.register_blueprint(api)
    return app


app = create_app()

if __name__ == "__main__":
    from tracker.config import FLASK_PORT

    app.run(host="0.0.0.0", port=FLASK_PORT, debug=True)

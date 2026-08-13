"""Flask JSON provider that knows how to serialize the Decimal/date types
psycopg hands back from Postgres numeric/date columns."""
import datetime
from decimal import Decimal

from flask.json.provider import DefaultJSONProvider


class TrackerJSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        return DefaultJSONProvider.default(obj)

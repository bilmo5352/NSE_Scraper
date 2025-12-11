from flask import Flask, request, jsonify
from werkzeug.exceptions import BadRequest

from scraper import (
    get_event_calendar_for_symbol,
    get_board_meetings_for_symbol,
    get_corporate_actions_for_symbol,
)


def create_app():
    app = Flask(__name__)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    @app.route("/event-calendar", methods=["GET"])
    def event_calendar():
        """
        GET /event-calendar?symbol=RELIANCE

        Response:
        {
          "symbol": "RELIANCE",
          "count": 60,
          "rows": [
            {
              "symbol": "RELIANCE",
              "company": "Reliance Industries Limited",
              "purpose": "Financial Results",
              "details": "...",
              "date": "19-Jul-2024"
            },
            ...
          ]
        }
        """
        symbol = request.args.get("symbol", "").strip()
        if not symbol:
            raise BadRequest("Query parameter 'symbol' is required")

        try:
            rows = get_event_calendar_for_symbol(symbol, headless=True)
        except Exception as e:
            # In real life, log the stack trace
            return jsonify(
                {
                    "symbol": symbol.upper(),
                    "error": "scrape_failed",
                    "message": str(e),
                }
            ), 500

        return jsonify(
            {
                "symbol": symbol.upper(),
                "count": len(rows),
                "rows": rows,
            }
        )

    @app.route("/board-meetings", methods=["GET"])
    def board_meetings():
        """
        GET /board-meetings?symbol=RELIANCE

        Response:
        {
          "symbol": "RELIANCE",
          "count": 20,
          "rows": [
            {
              "symbol": "RELIANCE",
              "company": "Reliance Industries Limited",
              "purpose": "Board Meeting Intimation",
              "details_link": "https://...",
              "meeting_date": "17-Oct-2025",
              "attachment_link": "https://...",
              "broadcast_datetime": "10-Oct-2025 11:55:48",
            },
            ...
          ]
        }
        """
        symbol = request.args.get("symbol", "").strip()
        if not symbol:
            raise BadRequest("Query parameter 'symbol' is required")

        try:
            rows = get_board_meetings_for_symbol(symbol, headless=True)
        except Exception as e:
            return (
                jsonify(
                    {
                        "symbol": symbol.upper(),
                        "error": "scrape_failed",
                        "message": str(e),
                    }
                ),
                500,
            )

        return jsonify(
            {
                "symbol": symbol.upper(),
                "count": len(rows),
                "rows": rows,
            }
        )

    @app.route("/corporate-actions", methods=["GET"])
    def corporate_actions():
        """
        GET /corporate-actions?symbol=RELIANCE

        Response:
        {
          "symbol": "RELIANCE",
          "count": 20,
          "rows": [
            {
              "symbol": "RELIANCE",
              "company": "Reliance Industries Limited",
              "series": "EQ",
              "purpose": "Dividend - Rs 5.5 Per Share",
              "face_value": "10",
              "ex_date": "14-Aug-2025",
              "record_date": "14-Aug-2025",
              "book_closure_start": "-",
              "book_closure_end": "-",
            },
            ...
          ]
        }
        """
        symbol = request.args.get("symbol", "").strip()
        if not symbol:
            raise BadRequest("Query parameter 'symbol' is required")

        try:
            rows = get_corporate_actions_for_symbol(symbol, headless=True)
        except Exception as e:
            return (
                jsonify(
                    {
                        "symbol": symbol.upper(),
                        "error": "scrape_failed",
                        "message": str(e),
                    }
                ),
                500,
            )

        return jsonify(
            {
                "symbol": symbol.upper(),
                "count": len(rows),
                "rows": rows,
            }
        )

    return app


# WSGI entrypoint for process managers (gunicorn, etc.)
app = create_app()


if __name__ == "__main__":
    # For dev: threaded True so multiple requests can run in parallel
    app.run(host="0.0.0.0", port=8000, debug=True, threaded=True)

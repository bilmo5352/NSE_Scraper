from flask import Flask, request, jsonify
from werkzeug.exceptions import BadRequest

from scraper import (
    get_event_calendar_for_symbol,
    get_board_meetings_for_symbol,
    get_corporate_actions_for_symbol,
    get_announcements_for_symbol,
    get_equity_quote_for_symbol,
    get_financial_results_for_symbol,
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

    @app.route("/announcements", methods=["GET"])
    def announcements():
        """
        GET /announcements?symbol=RELIANCE

        Response:
        {
          "symbol": "RELIANCE",
          "count": 20,
          "rows": [
            {
              "symbol": "RELIANCE",
              "company": "Reliance Industries Limited",
              "subject": "Copy of Newspaper Publication",
              "details": "...",
              "attachment_link": "https://...",
              "xbrl_link": "https://...",
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
            rows = get_announcements_for_symbol(symbol, headless=True)
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

    @app.route("/equity-quote", methods=["GET"])
    def equity_quote():
        """
        GET /equity-quote?symbol=RELIANCE

        Response:
        {
          "symbol": "RELIANCE",
          "data": {
            "symbol": "RELIANCE",
            "last_price": "2,534.00",
            "change": "+12.50",
            "percent_change": "+0.50%",
            "open": "2,520.00",
            "high": "2,550.00",
            "low": "2,515.00",
            "prev_close": "2,521.50",
            "vwap": "2,535.00",
            "traded_volume_lakhs": "1,234.56",
            "traded_value_cr": "3,123.45",
            "total_market_cap_cr": "17,12,345.67",
            "pe": "28.50",
            "52_week_high": "2,800.00",
            "52_week_low": "2,200.00",
            "returns": {
              "YTD": "15.25%",
              "1M": "2.50%",
              "3M": "5.75%",
              "1Y": "18.50%"
            },
            ...
          }
        }
        """
        symbol = request.args.get("symbol", "").strip()
        if not symbol:
            raise BadRequest("Query parameter 'symbol' is required")

        try:
            data = get_equity_quote_for_symbol(symbol, headless=True)
            if "error" in data:
                return (
                    jsonify(
                        {
                            "symbol": symbol.upper(),
                            "error": "scrape_failed",
                            "message": data.get("error", "Unknown error"),
                        }
                    ),
                    500,
                )
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
                "data": data,
            }
        )

    @app.route("/financial-results", methods=["GET"])
    def financial_results():
        """
        GET /financial-results?symbol=RELIANCE

        Response:
        {
          "symbol": "RELIANCE",
          "data": {
            "status": "success",
            "company": {
              "name": "Reliance Industries Limited",
              "symbol": "RELIANCE"
            },
            "quarters": ["31-Mar-2024", "31-Dec-2023", ...],
            "audit_status": ["Audited", "Audited", ...],
            "currency": "₹ Lakhs",
            "sections": [
              {
                "section_name": "Income",
                "line_items": [
                  {
                    "name": "Revenue from Operations",
                    "values": ["1,23,456", "1,20,000", ...],
                    "is_total": false
                  },
                  ...
                ]
              },
              ...
            ],
            "metadata": {
              "total_quarters": 5,
              "total_sections": 8,
              "note": "..."
            }
          }
        }
        """
        symbol = request.args.get("symbol", "").strip()
        if not symbol:
            raise BadRequest("Query parameter 'symbol' is required")

        try:
            data = get_financial_results_for_symbol(symbol, headless=True)
            if data.get("status") == "error":
                return (
                    jsonify(
                        {
                            "symbol": symbol.upper(),
                            "error": "scrape_failed",
                            "message": data.get("message", "Unknown error"),
                        }
                    ),
                    500,
                )
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
                "data": data,
            }
        )

    return app


# WSGI entrypoint for process managers (gunicorn, etc.)
app = create_app()


if __name__ == "__main__":
    # For dev: threaded True so multiple requests can run in parallel
    app.run(host="0.0.0.0", port=8000, debug=True, threaded=True)

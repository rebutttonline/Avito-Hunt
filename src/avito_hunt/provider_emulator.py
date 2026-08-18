import argparse
import json
import os
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen


def scenario_payload(scenario: str, step: int = 0) -> tuple[int, dict[str, object]]:
    if scenario == "error":
        return 503, {"error": "simulated provider outage"}
    if scenario == "invalid":
        return 200, {"items": [*baseline_items(), {"id": "broken-payload", "price": -1}]}
    if scenario == "empty":
        return 200, {"items": []}
    if scenario == "timeline":
        items = baseline_items()
        if step >= 1:
            deal = deal_item(price=78_000)
            if step == 2:
                deal["price"] = 72_000
            elif step >= 3:
                deal["status"] = "removed"
            items.append(deal)
        return (
            (503, {"error": "simulated timeline outage"}) if step >= 4 else (200, {"items": items})
        )
    return 200, {"items": [*baseline_items(), deal_item()]}


def baseline_items() -> list[dict[str, object]]:
    now = datetime.now(UTC).isoformat()
    prices = (98_000, 99_000, 99_500, 100_000, 100_500, 101_000, 101_500, 102_000, 103_000, 104_000)
    return [
        {
            "id": f"emulator-market-{index}",
            "title": "iPhone 15 Pro 256 ГБ",
            "price": price,
            "url": f"https://example.test/emulator-market-{index}",
            "condition": "used",
            "region": "Москва",
            "published_at": now,
            "status": "active",
        }
        for index, price in enumerate(prices, start=1)
    ]


def deal_item(*, price: int = 78_000) -> dict[str, object]:
    return {
        "id": "emulator-deal-1",
        "title": "iPhone 15 Pro 256 ГБ · тест поставщика",
        "price": price,
        "url": "https://example.test/emulator-deal-1",
        "condition": "used",
        "region": "Москва",
        "published_at": datetime.now(UTC).isoformat(),
        "description": "Аккумулятор 88%, полный комплект, без предоплаты",
        "status": "active",
    }


class EmulatorServer(ThreadingHTTPServer):
    timeline_step = 0
    timeline_lock = threading.Lock()

    def next_timeline_step(self) -> int:
        with self.timeline_lock:
            step = self.timeline_step
            self.timeline_step += 1
            return step


class EmulatorHandler(BaseHTTPRequestHandler):
    server: EmulatorServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._respond(200, {"status": "ok"})
            return
        if parsed.path != "/items":
            self._respond(404, {"error": "not found"})
            return
        scenario = parse_qs(parsed.query).get("scenario", ["baseline"])[0]
        step = self.server.next_timeline_step() if scenario == "timeline" else 0
        status, payload = scenario_payload(scenario, step)
        self._respond(status, payload)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _respond(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server() -> None:
    port = int(os.getenv("EMULATOR_PORT", "8080"))
    server = EmulatorServer(("0.0.0.0", port), EmulatorHandler)
    server.serve_forever()


def healthcheck() -> None:
    port = int(os.getenv("EMULATOR_PORT", "8080"))
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
            if response.status != 200:
                raise SystemExit(1)
    except URLError as error:
        raise SystemExit(1) from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    arguments = parser.parse_args()
    healthcheck() if arguments.healthcheck else run_server()


if __name__ == "__main__":
    main()

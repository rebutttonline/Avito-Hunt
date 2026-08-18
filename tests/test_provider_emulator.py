import json
import threading
from urllib.request import urlopen

from avito_hunt.provider_emulator import EmulatorHandler, EmulatorServer, scenario_payload


def test_timeline_simulates_price_drop_removal_and_outage() -> None:
    status, first = scenario_payload("timeline", 0)
    assert status == 200
    assert len(first["items"]) == 10

    _, appeared = scenario_payload("timeline", 1)
    assert appeared["items"][-1]["price"] == 78_000

    _, reduced = scenario_payload("timeline", 2)
    assert reduced["items"][-1]["price"] == 72_000

    _, removed = scenario_payload("timeline", 3)
    assert removed["items"][-1]["status"] == "removed"

    status, outage = scenario_payload("timeline", 4)
    assert status == 503
    assert "error" in outage


def test_emulator_can_return_invalid_provider_data() -> None:
    status, payload = scenario_payload("invalid")
    assert status == 200
    assert payload["items"][-1]["price"] == -1


def test_emulator_serves_internal_http_contract() -> None:
    server = EmulatorServer(("127.0.0.1", 0), EmulatorHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/items?scenario=baseline",
            timeout=2,
        ) as response:
            payload = json.load(response)
        assert response.status == 200
        assert len(payload["items"]) == 11
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

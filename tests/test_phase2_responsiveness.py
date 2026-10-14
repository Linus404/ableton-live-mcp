from __future__ import annotations

import threading
import scheduling_model as model


def test_framework_negative_delay_costs_one_extra_tick():
    for delay, expected in ((0, 2), (1, 1), (2, 2)):
        ticks = model.FrameworkTicks()
        called = []
        ticks.schedule_message(delay, lambda: called.append(ticks.ticks))
        while ticks.pending:
            ticks.tick()
        assert called == [expected]


def test_remote_dispatch_finishes_on_first_tick_on_main_thread():
    remote, ticks = model.make_remote()
    executed = []
    remote._rpc_marker = lambda params: executed.append(threading.get_ident()) or {"ok": True}
    worker, results = model.start_request(remote)
    try:
        assert ticks.scheduled.wait(2)
        assert ticks.delays == [1]
        assert not executed
        ticks.tick()
        worker.join(2)
        assert not worker.is_alive()
        assert executed == [threading.get_ident()]
        assert results == [{"jsonrpc": "2.0", "id": 17, "result": {"ok": True}, "outcome": "success"}]
    finally:
        while ticks.pending:
            ticks.tick()
        worker.join(2)


def test_blocked_display_timeout_never_executes_abandoned_work():
    remote, ticks = model.make_remote()
    executed = []
    remote._rpc_marker = lambda params: executed.append(True)
    worker, results = model.start_request(remote, params={"timeout": 0.01, "strict_timeout": True})
    assert ticks.scheduled.wait(2)
    worker.join(2)
    assert not worker.is_alive()
    assert results[0]["id"] == 17
    assert results[0]["error"]["data"]["outcome"] == "failed"
    assert remote._rpc_bridge_status({})["main_thread"]["stall_cooldown_remaining"] > 0
    remote._main_thread_id = -1
    refused = remote._dispatch({"id": 18, "method": "marker", "params": {}})
    assert refused["error"]["data"]["outcome"] == "failed"
    assert ticks.delays == [1]
    ticks.tick()
    assert executed == [] and ticks.pending == []


def test_running_callback_timeout_retains_gate_and_socket_status():
    remote, ticks = model.make_remote()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    executed = []

    def blocking(params):
        executed.append(threading.get_ident())
        started.set()
        assert release.wait(3)
        return {"ok": True}

    remote._rpc_marker = blocking
    worker, results = model.start_request(remote, params={"timeout": 0.03, "strict_timeout": True})
    assert ticks.scheduled.wait(2)

    def probe_while_callback_runs():
        try:
            assert started.wait(2)
            worker.join(2)
            assert not worker.is_alive()
            assert results[0]["error"]["data"]["outcome"] == "uncertain"
            status = remote._dispatch({"id": 18, "method": "bridge_status"})
            assert status["result"]["main_thread"]["in_flight_timed_out"]
            refused = remote._dispatch({"id": 19, "method": "marker", "params": {"force_main_thread_probe": True}})
            assert refused["error"]["data"]["outcome"] == "failed"
            assert ticks.delays == [1]
            finished.set()
        finally:
            release.set()

    probe = threading.Thread(target=probe_while_callback_runs)
    probe.start()
    try:
        ticks.tick()  # Execute the callback only on the test's main thread.
    finally:
        release.set()
        probe.join(3)
        worker.join(3)
    assert finished.is_set()
    assert executed == [threading.get_ident()]
    assert remote._rpc_bridge_status({})["main_thread"]["outcome"] == "idle"


def test_set_signature_guard_still_runs_before_callback():
    remote, ticks = model.make_remote()
    executed = []
    remote._rpc_marker = lambda params: executed.append(True)

    def reject(params):
        assert params["expected_set_signature"] == "old"
        raise RuntimeError("Live set changed")

    remote._check_expected_set_signature = reject
    worker, results = model.start_request(remote, params={"expected_set_signature": "old"})
    assert ticks.scheduled.wait(2)
    ticks.tick()
    worker.join(2)
    assert not worker.is_alive()
    assert "Live set changed" in results[0]["error"]["message"]
    assert not executed

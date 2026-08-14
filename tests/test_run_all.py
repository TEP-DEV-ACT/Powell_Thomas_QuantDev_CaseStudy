"""One ingestion source being down (e.g. FRED unreachable) must not block the
other sources from ingesting — each step in run_all.run() is independently
caught and logged rather than aborting the whole pipeline. Pure unit test,
monkeypatches the step functions; no network or DB.
"""
import tracker.ingest.run_all as run_all


def test_run_continues_past_a_failing_step(monkeypatch):
    calls = []

    def make_step(name, fail=False):
        def step():
            calls.append(name)
            if fail:
                raise RuntimeError(f"{name} boom")
        return step

    monkeypatch.setattr(
        run_all,
        "STEPS",
        [
            ("a", make_step("a")),
            ("b", make_step("b", fail=True)),
            ("c", make_step("c")),
        ],
    )
    ok = run_all.run()
    assert calls == ["a", "b", "c"]  # b's failure didn't stop c from running
    assert ok is False  # but the overall result still reports the failure


def test_run_reports_success_when_every_step_succeeds(monkeypatch):
    monkeypatch.setattr(
        run_all,
        "STEPS",
        [("a", lambda: None), ("b", lambda: None)],
    )
    assert run_all.run() is True

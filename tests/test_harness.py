import json
from pathlib import Path

from harness import conditions as C, trajectory as T, sanity, run

TASK = "3d-scan-calc"


def test_conditions_shapes_and_determinism():
    assert C.select("none", TASK, "1k", 0, 0) == []
    assert C.select("oracle", TASK, "1k", 0, 0) == C.curated(TASK)
    assert len(C.select("full-list", TASK, "1k", 0, 0)) == 1000
    for sel in ("bm25", "embedding", "skillret"):
        a = C.select(sel, TASK, "35k", 0, 0)
        assert len(a) == 3 and a == C.select(sel, TASK, "35k", 2, 0)  # same pick every run
    for p in (25, 50, 75):
        a = C.select(f"degraded-{p}", "court-form-filling", "1k", 1, 0)
        assert len(a) == 3 and len(set(a)) == 3
        assert a == C.select(f"degraded-{p}", "court-form-filling", "1k", 1, 0)  # replayable
        assert set(a) <= set(C.library("1k"))


def test_degraded_rate_close_to_p():
    lib_cur = C.tasks_curated_all()
    for p in (25, 75):
        n = hit = 0
        for t in list(C.tasks())[:80]:
            for i in range(3):
                s = C.select(f"degraded-{p}", t, "1k", i, 0)
                n += 3; hit += sum(x in lib_cur for x in s)
        # curated supply is capped by |curated| (many tasks have 1-2), so the rate sits at or below p
        assert hit / n <= p / 100 + 0.05 and hit / n > p / 100 - 0.25, (p, hit / n)


def test_run_id_stable_and_size_free():
    assert run.run_id("m", "oracle", "1k", 0, TASK, 0) == run.run_id("m", "oracle", "35k", 0, TASK, 0)
    assert run.run_id("m", "bm25", "1k", 0, TASK, 0) != run.run_id("m", "bm25", "35k", 0, TASK, 0)


def test_trajectory_parse(tmp_path: Path):
    traj = {"steps": [
        {"source": "user", "message": "<available_skills><skill><name>a</name><location>/app/skills/sb__t__a/SKILL.md</location></skill>"
                                      "<skill><name>b</name><location>/app/skills/skillsmp__b/SKILL.md</location></skill></available_skills>"},
        {"source": "agent", "tool_calls": [{"arguments": {"keystrokes": "cat /app/skills/sb__t__a/SKILL.md | head\n"}}]},
        {"source": "agent", "tool_calls": [{"arguments": {"keystrokes": "python3 /app/skills/sb__t__a/scripts/run.py && head -3 '/app/skills/skillsmp__b/SKILL.md'\n"}}]},
    ]}
    (tmp_path / "trajectory.json").write_text(json.dumps(traj))
    out = T.parse(tmp_path)
    assert out["skills_listed"] == ["sb__t__a", "skillsmp__b"]
    assert out["skills_opened_dirs"] == ["sb__t__a", "skillsmp__b"]
    assert out["skills_used_dirs"] == ["sb__t__a"]


def test_sanity_catches_problems():
    base = {"agent_model": "m", "library_size": "-", "status": "ok", "seed": 0, "run_idx": 0, "k": 3}
    rows = [{**base, "run_id": "1", "condition": "none", "task_id": "a", "passed": True},
            {**base, "run_id": "2", "condition": "oracle", "task_id": "a", "passed": False, "curated_present": False},
            {**base, "run_id": "3", "condition": "oracle", "task_id": "b", "passed": False, "curated_present": True}]
    errs = sanity.check(rows)
    assert any("oracle pass rate" in e for e in errs)
    assert any("missing tasks" in e for e in errs)
    assert any("not listed" in e for e in errs)
    ok = [{**base, "run_id": "4", "condition": "bm25", "library_size": "1k", "task_id": TASK, "passed": True,
           "skills_selected": C.select("bm25", TASK, "1k", 0, 0)}]
    assert sanity.check(ok) == []
    assert sanity.check([{**ok[0], "skills_selected": ["x"]}])  # replay mismatch is caught


def test_normalize_skill_md(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(run, "_INDEX", {"skillsmp/x": {"name": "x", "description": "from index"}}, raising=False)
    crlf = tmp_path / "crlf"; crlf.mkdir()
    (crlf / "skill.md").write_text("﻿---\r\nname: a\r\ndescription: b\r\n---\r\nbody\r\n")
    run.normalize_skill_md(crlf, "skillsmp/a")
    t = (crlf / "SKILL.md").read_text()
    assert not (crlf / "skill.md").exists() or (crlf / "skill.md").samefile(crlf / "SKILL.md")
    assert run._FM.match(t) and "\r" not in t and "name: a" in t
    bad = tmp_path / "bad"; bad.mkdir()
    (bad / "SKILL.md").write_text("no frontmatter here\n")
    run.normalize_skill_md(bad, "skillsmp/x")
    import yaml
    fm = yaml.safe_load(run._FM.match((bad / "SKILL.md").read_text()).group(1))
    assert fm == {"name": "x", "description": "from index"}


def test_sanity_flags_unlisted_skills():
    r = {"agent_model": "m", "library_size": "1k", "status": "ok", "seed": 0, "run_idx": 0, "k": 3, "run_id": "9",
         "condition": "embedding", "task_id": TASK, "passed": True, "skills_selected": C.select("embedding", TASK, "1k", 0, 0),
         "skills_unlisted": ["skillsmp__x"]}
    assert any("not listed" in e for e in sanity.check([r]))


def test_status_of():
    assert run.status_of(None, 1.0) == "ok" and run.status_of(None, 0.0) == "ok"
    assert run.status_of({"exception_type": "AgentTimeoutError"}, 0.0) == "ok"     # agent ran out of time: a real failure
    assert run.status_of({"exception_type": "BadRequestError"}, 0.0) == "error"    # provider rejected the request: retry
    assert run.status_of(None, None) == "error"


def test_is_ok_reclassifies_old_rows():
    assert run.is_ok({"status": "ok", "error": None})
    assert run.is_ok({"status": "ok", "error": "AgentTimeoutError: Agent execution timed out"})
    assert not run.is_ok({"status": "ok", "error": "RuntimeError: x__env: failed to send keys"})  # pre-fix row
    assert not run.is_ok({"status": "error", "error": "CancelledError: "})

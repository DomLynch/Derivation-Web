from __future__ import annotations

import json

import pytest

from scripts.dw_producer import build_dw_scaffold


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_build_dw_scaffold_is_idempotent_and_ordered(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sha = "a" * 64
    _write_json(run_dir / "manifest.json", {"run_id": "r1", "stages": ["infer", "audit"]})
    _write_json(
        run_dir / "full_paper.final_verdict.json",
        {"paper": {"title": "T"}, "final_verdict": "certify", "review": {"ok": True}},
    )
    _write_json(run_dir / "citation_registry.json", {"sources": [{"id": "s1"}]})
    _write_json(run_dir / "run_mode_contract.json", {"mode": "final"})
    _write_json(run_dir / "bundle_snapshot.json", {"files": [{"path": "paper.md", "sha256": sha}]})

    out = tmp_path / "dw.json"
    build_dw_scaffold(run_dir, out)
    first = out.read_bytes()
    build_dw_scaffold(run_dir, out)
    second = out.read_bytes()

    payload = json.loads(first)
    assert first == second
    assert payload["network"] == {"outbound_publishing": False, "secrets": False}
    assert [step["step_type"] for step in payload["steps"]] == [
        "infer",
        "audit",
        "review",
        "certify",
    ]
    assert payload["snapshot_sha_refs"] == [{"path": "files[0].sha256", "sha256": sha}]
    assert {artifact["role"] for artifact in payload["artifacts"]} == {
        "source",
        "manifest",
        "paper",
        "verdict",
        "register-ready",
    }


def test_missing_optional_files_fail_gracefully(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_json(run_dir / "manifest.json", {"run_id": "r1"})
    _write_json(run_dir / "full_paper.final_verdict.json", {"paper": "body"})

    out = build_dw_scaffold(run_dir)
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["optional_files"]["citation_registry.json"] == {"present": False}
    source = next(artifact for artifact in payload["artifacts"] if artifact["role"] == "source")
    assert source["present"] is False
    assert source["body"] is None


def test_required_files_are_required(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_json(run_dir / "manifest.json", {"run_id": "r1"})

    with pytest.raises(FileNotFoundError, match=r"full_paper\.final_verdict\.json"):
        build_dw_scaffold(run_dir)


def test_redacts_secret_keys_and_does_not_read_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DW_TEST_TOKEN", "env-token-should-not-appear")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_json(run_dir / "manifest.json", {"run_id": "r1", "api_key": "file-secret"})
    _write_json(
        run_dir / "full_paper.final_verdict.json",
        {"paper": "body", "nested": {"authorization": "Bearer file-secret"}},
    )

    out = build_dw_scaffold(run_dir)
    text = out.read_text(encoding="utf-8")

    assert "file-secret" not in text
    assert "env-token-should-not-appear" not in text
    assert text.count("[REDACTED]") == 2

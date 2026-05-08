"""Build a local Derivation Web JSON scaffold from a finalized run directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from derivation_web.core.canonical import canonicalize

REQUIRED_FILES = ("manifest.json", "full_paper.final_verdict.json")
OPTIONAL_FILES = ("citation_registry.json", "run_mode_contract.json", "bundle_snapshot.json")
SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|bearer|credential|password|secret|token)", re.I
)
SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
STEP_ORDER = ("infer", "audit", "review", "certify")


def build_dw_scaffold(run_dir: str | Path, out_path: str | Path | None = None) -> Path:
    """Write a DW-ready local JSON scaffold and return its path."""
    root = Path(run_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"run dir not found: {root}")

    loaded = _load_run_files(root)
    missing_required = [name for name in REQUIRED_FILES if name not in loaded]
    if missing_required:
        raise FileNotFoundError(f"missing required run file(s): {', '.join(missing_required)}")

    scaffold = make_dw_scaffold(loaded)
    destination = Path(out_path) if out_path else root / "dw_producer.json"
    destination.write_bytes(_json_bytes(scaffold))
    return destination


def make_dw_scaffold(files: dict[str, Any]) -> dict[str, Any]:
    """Create the deterministic scaffold payload from already-loaded run JSON."""
    manifest = files["manifest.json"]
    verdict = files["full_paper.final_verdict.json"]
    citations = files.get("citation_registry.json")
    contract = files.get("run_mode_contract.json")
    snapshot = files.get("bundle_snapshot.json")
    sha_refs = _snapshot_sha_refs(snapshot) if snapshot is not None else []

    artifacts = [
        _artifact("source", "citation_registry.json", citations, citations is not None, sha_refs),
        _artifact("manifest", "manifest.json", manifest, True, sha_refs),
        _artifact("paper", "full_paper.final_verdict.json", _paper_body(verdict), True, sha_refs),
        _artifact("verdict", "full_paper.final_verdict.json", verdict, True, sha_refs),
        _register_ready_artifact(files, sha_refs),
    ]
    artifact_ids = {artifact["role"]: artifact["id"] for artifact in artifacts}

    steps = _steps(verdict, manifest, contract, artifact_ids)
    return {
        "schema": "dw-producer.local.v1",
        "network": {"outbound_publishing": False, "secrets": False},
        "required_files": list(REQUIRED_FILES),
        "optional_files": {
            name: {"present": name in files} for name in OPTIONAL_FILES
        },
        "snapshot_sha_refs": sha_refs,
        "artifacts": artifacts,
        "steps": steps,
    }


def _load_run_files(root: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for name in (*REQUIRED_FILES, *OPTIONAL_FILES):
        path = root / name
        if path.exists():
            files[name] = _sanitize(json.loads(path.read_text(encoding="utf-8")))
    return files


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            clean[str(key)] = "[REDACTED]" if SENSITIVE_KEY_RE.search(str(key)) else _sanitize(item)
        return clean
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _artifact(
    role: str,
    file_name: str,
    body: Any,
    present: bool,
    sha_refs: list[dict[str, str]],
) -> dict[str, Any]:
    content = {
        "role": role,
        "file": file_name,
        "present": present,
        "body": body if present else None,
    }
    if sha_refs:
        content["snapshot_sha_refs"] = sha_refs
    digest = _sha256(content)
    return {
        "id": f"local:artifact:{digest[:16]}",
        "role": role,
        "kind": _kind(role),
        "content_type": "application/json",
        "content_sha256": digest,
        "file": file_name,
        "present": present,
        "body": body if present else None,
        "metadata": {"snapshot_sha_refs": sha_refs} if sha_refs else {},
    }


def _register_ready_artifact(
    files: dict[str, Any], sha_refs: list[dict[str, str]]
) -> dict[str, Any]:
    body = {
        "ready": True,
        "files": {name: name in files for name in (*REQUIRED_FILES, *OPTIONAL_FILES)},
    }
    return _artifact("register-ready", "dw_producer.json", body, True, sha_refs)


def _kind(role: str) -> str:
    if role == "source":
        return "source"
    if role == "paper":
        return "claim"
    return "revision"


def _paper_body(verdict: Any) -> Any:
    if not isinstance(verdict, dict):
        return verdict
    for key in ("paper", "full_paper", "article", "content", "text"):
        if key in verdict:
            return verdict[key]
    return {"source": "full_paper.final_verdict.json", "available": False}


def _steps(
    verdict: Any,
    manifest: Any,
    contract: Any,
    artifact_ids: dict[str, str],
) -> list[dict[str, Any]]:
    available = _available_steps(verdict, manifest, contract)
    step_inputs = {
        "infer": ["source", "manifest"],
        "audit": ["paper", "source"],
        "review": ["paper", "verdict"],
        "certify": ["manifest", "verdict"],
    }
    step_outputs = {
        "infer": "paper",
        "audit": "verdict",
        "review": "verdict",
        "certify": "register-ready",
    }
    return [
        _step(name, step_inputs[name], step_outputs[name], artifact_ids, available[name])
        for name in STEP_ORDER
    ]


def _available_steps(verdict: Any, manifest: Any, contract: Any) -> dict[str, bool]:
    text = json.dumps(
        {"verdict": verdict, "manifest": manifest, "contract": contract},
        sort_keys=True,
        default=str,
    ).lower()
    return {name: name in text for name in STEP_ORDER}


def _step(
    name: str,
    input_roles: list[str],
    output_role: str,
    artifact_ids: dict[str, str],
    available: bool,
) -> dict[str, Any]:
    payload = {
        "step_type": name,
        "input_artifact_ids": [artifact_ids[role] for role in input_roles],
        "output_artifact_id": artifact_ids[output_role],
        "target_artifact_id": None,
        "available": available,
    }
    return {"id": f"local:step:{_sha256(payload)[:16]}", **payload}


def _snapshot_sha_refs(snapshot: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                has_sha_key = "sha" in str(key).lower()
                if isinstance(item, str) and (SHA256_RE.fullmatch(item) or has_sha_key):
                    refs.append({"path": child_path, "sha256": item})
                walk(item, child_path)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
        elif isinstance(value, str) and SHA256_RE.fullmatch(value):
            refs.append({"path": path, "sha256": value})

    walk(snapshot, "")
    deduped = {(ref["path"], ref["sha256"]): ref for ref in refs}
    return sorted(deduped.values(), key=lambda r: r["path"])


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonicalize(value)).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", help="Finalized run directory")
    parser.add_argument("--out", help="Output JSON path; defaults to RUN_DIR/dw_producer.json")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    print(build_dw_scaffold(args.run_dir, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

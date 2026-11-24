import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "name",
    ["meta", "surface", "audit-disposition", "audit", "deploy-log", "verify", "cnvd-form"],
)
def test_fixture_contract_and_export(name):
    from auditflow.core.schemas import export_schemas, load_artifact

    path = FIXTURES / f"{name}.json"
    data = load_artifact(path).model_dump(mode="json", exclude_unset=True)
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == set(expected)
    assert export_schemas()[path.name]["additionalProperties"] is False


def test_schema_rejects_path_escape_and_reversed_range():
    from auditflow.core.schemas import Audit

    audit = json.loads((FIXTURES / "audit.json").read_text(encoding="utf-8"))
    audit["code_evidence"][0]["file"] = "../private.py"
    audit["code_evidence"][0]["end_line"] = 1
    with pytest.raises(ValidationError):
        Audit.model_validate(audit)


def test_validate_cli_rejects_unknown_fields(tmp_path):
    from auditflow.cli import app

    path = tmp_path / "meta.json"
    payload = json.loads((FIXTURES / path.name).read_text(encoding="utf-8"))
    payload["unexpected"] = "ignored?"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = CliRunner().invoke(app, ["validate", str(path)])
    assert result.exit_code == 1
    assert "unexpected" in result.output


def test_manifest_rejects_a_single_image_assigned_to_two_different_steps():
    from auditflow.core.schemas import Verify

    verify = json.loads((FIXTURES / "verify.json").read_text(encoding="utf-8"))
    verify["evidence_manifest"]["code_shots"][0]["path"] = "evidence/http.png"
    with pytest.raises(ValidationError, match="same image"):
        Verify.model_validate_json(json.dumps(verify))

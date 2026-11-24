import json
import shutil
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from openpyxl import Workbook, load_workbook
from PIL import Image
from typer.testing import CliRunner

FIXTURES = Path(__file__).parent / "fixtures"


def test_report_cli_creates_real_word_and_forms(tmp_path):
    from auditflow.cli import app

    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURES, fixture)
    verify_path = fixture / "verify.json"
    verify = json.loads(verify_path.read_text(encoding="utf-8"))
    verify["steps"][1]["stdout"] = "\x1b[32m1 passed\x1b[0m"
    verify_path.write_text(json.dumps(verify), encoding="utf-8")
    out = tmp_path / "out"
    result = CliRunner().invoke(app, ["report", "--workspace", str(fixture), "--out", str(out)])
    assert result.exit_code == 0, result.output
    docs = list(out.glob("*.docx"))
    assert len(docs) == 1
    for name in ("code.png", "http.png", "term.png"):
        with Image.open(fixture / "evidence" / name) as image:
            assert image.width == 1440
    with ZipFile(docs[0]) as package:
        assert sum(name.startswith("word/media/") for name in package.namelist()) == 3
    document = Document(docs[0])
    paragraphs = "\n".join(p.text for p in document.paragraphs)
    assert "代码审计" in paragraphs and "【此处插入截图" in paragraphs
    assert any("1 passed" in table.cell(0, 0).text for table in document.tables)
    form = json.loads(next(out.glob("*_cnvd_form.json")).read_text(encoding="utf-8"))
    assert form["product"] == "示例服务"
    assert form["attachment_docx"] == docs[0].name
    assert "## 涉及厂商" in next(out.glob("*_cnvd_form.md")).read_text(encoding="utf-8")


def test_excel_append_creates_backup_and_preserves_original_cell(tmp_path):
    from auditflow.core.schemas import load_artifact
    from auditflow.reporting.excel_sync import append_report

    path = tmp_path / "ledger.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "Existing header"
    workbook.active["A1"].number_format = "0.00"
    workbook.save(path)
    backup = append_report(path, load_artifact(FIXTURES / "cnvd-form.json"))
    assert load_workbook(backup).active.max_row == 1
    updated = load_workbook(path).active
    assert updated["A1"].number_format == "0.00"
    assert updated.max_row == 2

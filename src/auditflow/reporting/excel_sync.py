import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from openpyxl import load_workbook

from auditflow.core.schemas import CnvdForm


def append_report(path: Path, form: CnvdForm) -> Path:
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("Excel ledger must use .xlsx or .xlsm")
    lock = path.with_name(f".{path.name}.auditflow.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError("Excel ledger is already being updated") from exc
    os.close(descriptor)
    try:
        return _append(path, form)
    finally:
        lock.unlink(missing_ok=True)


def _append(path: Path, form: CnvdForm) -> Path:
    date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.stem}.{date}-{uuid4().hex[:8]}.bak{path.suffix}")
    workbook = load_workbook(path, keep_vba=path.suffix.lower() == ".xlsm")
    try:
        sheet = workbook.active
        if sheet is None:
            raise ValueError("Excel workbook has no active sheet")
        values = [
            form.vuln_title, form.vendor, form.product, form.affected_versions,
            str(form.repo_url), form.vuln_category, form.cwe, form.severity, form.attachment_docx,
        ]
        sheet.append(values)
        for cell in sheet[sheet.max_row][:len(values)]:
            cell.data_type = "s"
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=path.suffix, delete=False) as temp:
            temporary = Path(temp.name)
        try:
            workbook.save(temporary)
            shutil.copy2(path, backup)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        workbook.close()
    return backup

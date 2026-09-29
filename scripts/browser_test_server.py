"""Real app, temporary synthetic database, loopback only; never a staging import.

Invoked by Playwright in Linux CI. Auth stays enabled with test-only identities.
No provider credentials, existing database or external connections are allowed.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import secrets
import socket
import sys
import tempfile

if os.getenv("BROWSER_TEST_MODE") != "synthetic":
    raise RuntimeError("This helper requires explicit synthetic browser-test mode")
if any(os.getenv(key) for key in ("DATABASE_URL", "DB_DIR", "UPLOADS_DIR", "ANTHROPIC_API_KEY", "BRAVE_API_KEY", "OPENAI_API_KEY")):
    raise RuntimeError("Refusing existing data paths or provider credentials")

workspace = tempfile.TemporaryDirectory(prefix="deal-analyzer-browser-")
root = Path(workspace.name)
uploads = root / "uploads"
uploads.mkdir()
os.environ.update({
    "DB_DIR": str(root), "UPLOADS_DIR": str(uploads),
    "REVIEW_WORKERS_ENABLED": "0", "DEAL_REVIEW_AUTO_AFTER_UPLOAD": "0",
    "AUTH_DISABLED": "0", "AUTH_USERNAME": "browser-admin",
    "AUTH_PASSWORD": "synthetic-browser-password", "VIEWER_USERNAME": "browser-viewer",
    "VIEWER_PASSWORD": "synthetic-viewer-password", "AUTH_SECRET": secrets.token_hex(32),
    "SESSION_HTTPS_ONLY": "0",
})
for key in ("AUTH_PASSWORD_HASH", "VIEWER_PASSWORD_HASH", "TEAM_PASSWORD_HASH", "_KENYON_ADMIN_PASSWORD_HASH_CACHE", "_KENYON_VIEWER_PASSWORD_HASH_CACHE"):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# External market/provider calls must not escape this synthetic test process.
original_connect = socket.socket.connect
def local_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1"):
        raise OSError("External networking is disabled in synthetic browser tests")
    return original_connect(sock, address)
socket.socket.connect = local_connect

from app.database import async_session, engine, init_db
from app.models import Deal, DealChat, DealDocument, Developer, Investment, Distribution
from app.main import app


def metrics(yield_value, *, missing_minimum=False, sale=False):
    data = {
        "deal_structure": {"total_project_cost": 1000000, "total_equity_required": 400000,
            "debt_amount": 600000, "hold_period_years": 5, "minimum_investment": None if missing_minimum else 25000,
            "structure_description": "Class A and Class B with refinancing distributions"},
        "project_details": {"unit_count": 20},
        "target_returns": {"primary_strategy": "sale" if sale else "hold_with_sale_option",
            "target_irr": 15.5 if sale else 27.5, "target_equity_multiple": 1.8 if sale else 4.25,
            "hold_scenario": {"cash_on_cash_return": yield_value},
            "sale_scenario": {"sale_irr": 27.5, "sale_equity_multiple": 4.25, "is_hypothetical": True}},
    }
    provenance = {}
    def visit(obj, prefix=""):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict): visit(value, path)
            elif value is not None:
                provenance[path] = {"status": "manual", "source": "manual", "note": "Synthetic fixture decision"}
    visit(data)
    data["_provenance"] = provenance
    return data


async def seed():
    from datetime import date
    from reportlab.pdfgen import canvas
    await init_db()
    async with async_session() as db:
        sponsor = Developer(id=1, name="Synthetic Sponsor")
        db.add(sponsor)
        deals = [
            Deal(id=1, project_name="Sample Hold", developer_id=1, city="Example City", state="CA", metrics=metrics(8.5)),
            Deal(id=2, project_name="Sample Questions", developer_id=1, metrics=metrics(6, missing_minimum=True)),
            Deal(id=3, project_name="Sample Sale", developer_id=1, metrics=metrics(7, sale=True)),
        ]
        db.add_all(deals)
        await db.flush()
        pdf_path = uploads / "sample-hold.pdf"
        pdf = canvas.Canvas(str(pdf_path))
        pdf.drawString(60, 760, "Synthetic test document - Sample Hold")
        pdf.drawString(60, 730, "Hold cash-on-cash return: 8.5%. Optional sale IRR: 27.5%.")
        pdf.save()
        digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        for doc_id in (1, 2):
            db.add(DealDocument(id=doc_id, deal_id=1, filename="sample-hold.pdf", file_path=str(pdf_path),
                file_sha256=digest, content_fingerprint=digest, page_count=1, doc_type="offering_memo",
                extracted_text="--- Page 1 ---\nHold cash-on-cash return: 8.5%. Optional sale IRR: 27.5%."))
        csv_path = uploads / "sample-terms.csv"
        csv_path.write_text("Metric,Value\nUnits,20\n", encoding="utf-8")
        db.add(DealDocument(id=3, deal_id=2, filename="sample-terms.csv", file_path=str(csv_path),
            file_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(), page_count=1,
            extracted_text="--- Sheet: sample-terms ---\nA1=Metric | B1=Value\nA2=Units | B2=20",
            extraction_quality={"document_kind": "spreadsheet", "page_diagnostics": [{"external_workbook_links": 2, "truncated": True}]}))
        db.add(DealChat(deal_id=1, role="assistant", content="Synthetic saved conversation. Summary holds the accepted figures."))
        position = Investment(id=1, deal_id=1, project_name="Synthetic Position", sponsor_name="Synthetic Sponsor",
            amount_invested=10000, investment_date=date(2024, 1, 1), status="active")
        db.add(position)
        await db.flush()
        db.add(Distribution(investment_id=1, amount=500, date=date(2025, 1, 1)))
        await db.commit()
    await engine.dispose()


if __name__ == "__main__":
    import uvicorn
    asyncio.run(seed())
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

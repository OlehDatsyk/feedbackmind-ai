"""CSV / XLSX / JSON imports: mapping, validation, duplicates, dates, rejected rows, safety."""

from __future__ import annotations

import io
import json
import zipfile

from tests.conftest import add_feedback, csv_bytes, import_file, xlsx_bytes

HEADER = ["Review", "Date", "Stars", "Product", "Channel", "Customer"]
ROWS = [
    ["Delivery was late and the box was damaged", "2026-03-01", "1", "Lamp", "Trustpilot", "C1"],
    ["Love the product, great quality", "2026-03-02", "5", "Lamp", "Trustpilot", "C2"],
    ["", "2026-03-03", "3", "Lamp", "Email", "C3"],  # empty text -> invalid
    ["Support never answered", "not a date", "2", "App", "Email", "C4"],  # invalid date
    ["Rating out of range", "2026-03-04", "9", "App", "Email", "C5"],  # invalid rating
    ["Love the product, great quality", "2026-03-02", "5", "Lamp", "Trustpilot", "C2"],  # duplicate of row 2
    ['=HYPERLINK("http://evil","x") fine', "2026-03-05", "4", "App", "Email", "C6"],
]


def test_csv_import_end_to_end(alice):
    res = import_file(alice, "reviews.csv", csv_bytes(ROWS, HEADER))
    up, val, final = res["upload"], res["validation"], res["final"]
    assert up["columns"] == HEADER
    assert up["mapping"]["text"] == "Review" and up["mapping"]["received_at"] == "Date" and up["mapping"]["rating"] == "Stars"
    assert up["mapping"]["product"] == "Product" and up["mapping"]["source"] == "Channel" and up["mapping"]["customer_ref"] == "Customer"
    assert val["total_rows"] == 7 and val["valid_rows"] == 3 and val["invalid_rows"] == 3 and val["duplicate_rows"] == 1
    assert len(val["preview"]) == 3
    assert final["status"] == "completed_with_errors"
    assert final["imported_rows"] == 3
    # Nothing silently dropped: 3 imported + 3 invalid + 1 duplicate = 7
    errs = alice.get(f"/api/v1/imports/{up['id']}/errors").json()
    assert errs["total"] == 4
    assert {e["row_number"] for e in errs["items"]} == {3, 4, 5, 6}
    assert any("date" in e["message"].lower() for e in errs["items"])
    fb = alice.get("/api/v1/feedback", params={"sort": "oldest"}).json()
    assert fb["total"] == 3
    first = fb["items"][0]
    assert first["text"] == ROWS[0][0]  # original text preserved
    assert first["received_at"].startswith("2026-03-01")
    assert first["product"]["name"] == "Lamp" and first["source"]["name"] == "Trustpilot"
    assert first["rating"] == 1.0 and first["rating_max"] == 5.0
    # Raw upload is cleared after processing.
    assert alice.post(f"/api/v1/imports/{up['id']}/validate", json={"mapping": up["mapping"]}).status_code == 409


def test_rejected_rows_report_is_formula_safe(alice):
    rows = [["=1+1 sneaky", "bad-date", "", "", "", ""], ["ok text here", "2026-01-01", "", "", "", ""]]
    res = import_file(alice, "x.csv", csv_bytes(rows, HEADER))
    r = alice.get(f"/api/v1/imports/{res['upload']['id']}/errors.csv")
    assert r.status_code == 200
    body = r.content.decode("utf-8-sig")
    assert "'=1+1 sneaky" in body
    assert "row_number,error_type,reason" in body.splitlines()[0]


def test_reimport_detects_existing_duplicates(alice):
    import_file(alice, "a.csv", csv_bytes(ROWS[:2], HEADER))
    res = import_file(alice, "a-again.csv", csv_bytes(ROWS[:2], HEADER), confirm=False)
    assert res["validation"]["duplicate_rows"] == 2 and res["validation"]["valid_rows"] == 0
    assert alice.get("/api/v1/feedback").json()["total"] == 2


def test_xlsx_import_with_real_dates(alice):
    from datetime import datetime

    rows = [
        ["Great app, fast and reliable", datetime(2026, 2, 10, 14, 30), 5, "App"],
        ["The app crashes constantly, terrible experience", datetime(2026, 2, 11), 1, "App"],
    ]
    res = import_file(alice, "survey.xlsx", xlsx_bytes(rows, ["Comment", "Submitted", "Rating", "Product"]))
    assert res["final"]["imported_rows"] == 2
    items = alice.get("/api/v1/feedback", params={"sort": "oldest"}).json()["items"]
    assert items[0]["received_at"].startswith("2026-02-10T14:30")
    assert items[1]["sentiment"]["label"] == "negative"


def test_naive_dates_use_workspace_timezone(alice):
    alice.patch("/api/v1/workspace", json={"timezone": "America/New_York"})
    res = import_file(alice, "tz.csv", csv_bytes([["Fine service", "2026-01-15 23:30"]], ["Text", "Date"]))
    item = alice.get("/api/v1/feedback").json()["items"][0]
    assert res["final"]["imported_rows"] == 1
    assert item["received_at"].startswith("2026-01-16T04:30")  # 23:30 EST = 04:30 UTC next day
    # Filtering by local date still finds it on the 15th.
    assert alice.get("/api/v1/feedback", params={"date_from": "2026-01-15", "date_to": "2026-01-15"}).json()["total"] == 1
    assert alice.get("/api/v1/feedback", params={"date_from": "2026-01-16", "date_to": "2026-01-16"}).json()["total"] == 0


def test_ambiguous_and_inferred_date_orders(alice):
    ambiguous = csv_bytes([["a b c", "03/04/2026"], ["d e f", "05/06/2026"]], ["Text", "Date"])
    res = import_file(alice, "amb.csv", ambiguous, confirm=False)
    assert res["validation"]["valid_rows"] == 0 and "ambiguous" in res["validation"]["errors"][0]["message"]
    up = res["upload"]
    v = alice.post(f"/api/v1/imports/{up['id']}/validate", json={"mapping": up["mapping"], "options": {"date_order": "dayfirst"}}).json()
    assert v["valid_rows"] == 2 and v["preview"][0]["received_at"].startswith("2026-04-03")
    inferred = csv_bytes([["a b c", "03/04/2026"], ["d e f", "25/06/2026"]], ["Text", "Date"])
    v2 = import_file(alice, "inf.csv", inferred, confirm=False)["validation"]
    assert v2["valid_rows"] == 2 and v2["preview"][0]["received_at"].startswith("2026-04-03")


def test_missing_dates_policy(alice):
    data = csv_bytes([["Nice", ""], ["Bad", ""]], ["Text", "Date"])
    res = import_file(alice, "nodate.csv", data, confirm=False)
    assert res["validation"]["valid_rows"] == 0 and res["validation"]["invalid_rows"] == 2
    up = res["upload"]
    v = alice.post(f"/api/v1/imports/{up['id']}/validate", json={"mapping": up["mapping"], "options": {"missing_date": "use_import_time"}}).json()
    assert v["valid_rows"] == 2 and v["date_defaulted_rows"] == 2


def test_json_import(alice):
    data = json.dumps({"records": [{"feedback": "Support was helpful", "date": "2026-05-01", "tags": ["support", "vip"]}]}).encode()
    res = import_file(alice, "feed.json", data)
    assert res["final"]["imported_rows"] == 1
    item = alice.get("/api/v1/feedback").json()["items"][0]
    assert sorted(t["name"] for t in item["tags"]) == ["support", "vip"]


def test_rejects_bad_files(alice):
    def up(name, content):
        return alice.post("/api/v1/imports", files={"file": (name, content, "application/octet-stream")})

    assert up("x.exe", b"MZ...").status_code == 400
    assert up("legacy.xls", b"\xd0\xcf\x11\xe0").status_code == 400
    assert up("macro.xlsm", b"PK\x03\x04").status_code == 400
    assert up("fake.xlsx", b"not a zip").status_code == 400
    assert up("empty.csv", b"").status_code == 400
    assert up("header-only.csv", b"text,date\n").status_code == 400
    assert up("big.csv", b"a,b\n" + b"x" * (3 * 1024 * 1024)).status_code == 413
    # A workbook that contains a VBA project is rejected even with an .xlsx name.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<x/>")
        zf.writestr("xl/vbaProject.bin", b"\x00")
    r = up("sneaky.xlsx", buf.getvalue())
    assert r.status_code == 400 and "macro" in r.json()["detail"].lower()
    assert up("../../etc/passwd.csv", b"text\nhello world\n").json()["file_name"] == "passwd.csv"


def test_mapping_validation(alice):
    r = alice.post("/api/v1/imports", files={"file": ("m.csv", csv_bytes([["x"]], ["Body"]), "text/csv")}).json()
    assert alice.post(f"/api/v1/imports/{r['id']}/validate", json={"mapping": {}}).status_code == 400
    assert alice.post(f"/api/v1/imports/{r['id']}/validate", json={"mapping": {"text": "Nope"}}).status_code == 400
    assert alice.post(f"/api/v1/imports/{r['id']}/confirm").status_code == 409  # must validate first


def test_encoding_detection(alice):
    content = 'Text,Date\n"Très bon service, merci beaucoup pour tout",2026-01-02\n'.encode("cp1252")
    res = import_file(alice, "latin.csv", content)
    assert res["final"]["imported_rows"] == 1
    assert alice.get("/api/v1/feedback").json()["items"][0]["text"].startswith("Très")
    assert res["upload"]["encoding"] == "cp1252"
    # An explicit encoding overrides the default order.
    content2 = "Text,Date\nZápis byl skvělý a rychlý,2026-01-03\n".encode("cp1250")
    r = alice.post("/api/v1/imports", files={"file": ("cz.csv", content2, "text/csv")}, data={"encoding": "cp1250"})
    assert r.status_code == 201 and r.json()["sample_rows"][0][0].startswith("Zápis")


def test_import_isolation(alice, bob):
    res = import_file(alice, "a.csv", csv_bytes(ROWS[:1], HEADER))
    assert bob.get(f"/api/v1/imports/{res['upload']['id']}").status_code == 404
    assert bob.get(f"/api/v1/imports/{res['upload']['id']}/errors.csv").status_code == 404


def test_manual_and_import_duplicate_interplay(alice):
    add_feedback(alice, "Delivery was late and the box was damaged", received_at="2026-03-01T10:00:00Z", customer_ref="C1")
    product_free = [[ROWS[0][0], "2026-03-01", "1", "", "Trustpilot", "C1"]]
    res = import_file(alice, "d.csv", csv_bytes(product_free, HEADER), confirm=False)
    assert res["validation"]["duplicate_rows"] == 1


def test_malformed_rows_are_reported_not_reshaped(alice):
    content = b'Text,Date\nGood service, really fast,2026-01-02\n"Quoted, fine",2026-01-03\n'
    res = import_file(alice, "bad.csv", content)
    v = res["validation"]
    assert v["valid_rows"] == 1 and v["invalid_rows"] == 1
    assert "fields" in v["errors"][0]["message"]
    texts = [i["text"] for i in alice.get("/api/v1/feedback").json()["items"]]
    assert texts == ["Quoted, fine"]


def test_oversized_request_rejected_before_parsing(client, alice):
    big = b"x" * (4 * 1024 * 1024)  # MAX_IMPORT_MB=2 in tests, so the 3 MB body limit is exceeded
    r = alice.post("/api/v1/imports", files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 413

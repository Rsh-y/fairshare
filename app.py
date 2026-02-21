from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Any
import io
import os
import uuid
import json

from flask import Flask, jsonify, render_template, request, send_file, session, redirect, url_for
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
except Exception:  # pragma: no cover - best-effort import for runtime
    A4 = None
    ImageReader = None
    canvas = None

app = Flask(__name__)
app.secret_key = os.environ.get("FAIRSHARE_SECRET", "fairshare-dev-secret")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
USERS_PATH = os.path.join(DATA_DIR, "users.json")


def _load_users() -> dict:
    if not os.path.isfile(USERS_PATH):
        return {}
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users(users: dict) -> None:
    with open(USERS_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _current_user() -> str | None:
    return session.get("username")


def _require_user():
    user = _current_user()
    if not user:
        return None, jsonify({"ok": False, "errors": ["Please log in first."]}), 401
    return user, None, None


@dataclass
class Expense:
    name: str
    amount: float
    payer: str
    split_type: str  # "all" or "custom"
    split_people: List[str]  # for custom splits (excluding payer)


@app.get("/")
def index():
    if _current_user():
        return redirect(url_for("app_page"))
    return redirect(url_for("login_page"))


@app.get("/login")
def login_page():
    return render_template("login.html")


@app.get("/app")
def app_page():
    if not _current_user():
        return redirect(url_for("login_page"))
    return render_template("app.html")


def _normalize_people(people: List[str]) -> Tuple[List[str], Dict[str, str]]:
    original = {}
    normalized = []
    for name in people:
        raw = name.strip()
        if not raw:
            continue
        key = raw.lower()
        if key in original:
            continue
        original[key] = raw
        normalized.append(key)
    return normalized, original


def _init_balances(people: List[str]) -> Dict[str, Dict[str, float]]:
    balances = {p: {} for p in people}
    for p in people:
        for o in people:
            if p != o:
                balances[p][o] = 0.0
    return balances


def _validate_expenses(expenses: List[dict], people: List[str]) -> Tuple[List[Expense], List[str]]:
    errors: List[str] = []
    cleaned: List[Expense] = []

    for i, exp in enumerate(expenses, start=1):
        name = str(exp.get("name", "")).strip()
        amount = exp.get("amount")
        payer = str(exp.get("payer", "")).strip().lower()
        split_type = str(exp.get("split_type", "all")).strip().lower() or "all"
        split_people = exp.get("split_people") or []

        if not name:
            errors.append(f"Expense #{i}: missing name")
            continue
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            errors.append(f"Expense '{name}': amount must be a number")
            continue
        if amount <= 0:
            errors.append(f"Expense '{name}': amount must be positive")
            continue
        if payer not in people:
            errors.append(f"Expense '{name}': payer must be one of the people")
            continue

        if split_type not in {"all", "custom"}:
            errors.append(f"Expense '{name}': split_type must be 'all' or 'custom'")
            continue

        if split_type == "custom":
            cleaned_split = []
            for p in split_people:
                key = str(p).strip().lower()
                if not key:
                    continue
                if key == payer:
                    errors.append(f"Expense '{name}': payer cannot be in split_people")
                    continue
                if key not in people:
                    errors.append(f"Expense '{name}': split person '{p}' not in people")
                    continue
                if key in cleaned_split:
                    continue
                cleaned_split.append(key)

            if not cleaned_split:
                errors.append(f"Expense '{name}': custom split must include at least one person")
                continue

            split_people = cleaned_split
        else:
            split_people = []

        cleaned.append(
            Expense(
                name=name,
                amount=float(amount),
                payer=payer,
                split_type=split_type,
                split_people=split_people,
            )
        )

    return cleaned, errors


def compute_summary(people_input: List[str], expenses_input: List[dict]) -> Dict[str, Any]:
    people, original = _normalize_people(people_input)
    if len(people) < 2:
        return {"ok": False, "errors": ["Add at least 2 unique people."]}

    expenses, errors = _validate_expenses(expenses_input, people)
    if errors:
        return {"ok": False, "errors": errors}

    balances = _init_balances(people)
    exp_sheet: Dict[str, dict] = {}

    for exp in expenses:
        exp_sheet[exp.name] = {
            "amount": exp.amount,
            "payer": exp.payer,
            "split_details": [],
            "split_type": exp.split_type,
        }

        if exp.split_type == "all":
            participants = list(people)
            share = exp.amount / len(participants)
            split_people = [p for p in participants if p != exp.payer]
        else:
            split_people = exp.split_people
            share = exp.amount / (len(split_people) + 1)

        for person in split_people:
            balances[exp.payer][person] += share
            balances[person][exp.payer] -= share
            exp_sheet[exp.name]["split_details"].append({
                "name": person,
                "amount": share,
            })

    # Raw settlements
    raw = []
    done = set()
    for person in people:
        for other in people:
            if person == other or (person, other) in done:
                continue
            if balances[person][other] > 0.01:
                raw.append({
                    "from": other,
                    "to": person,
                    "amount": balances[person][other],
                })
            elif balances[other][person] > 0.01:
                raw.append({
                    "from": person,
                    "to": other,
                    "amount": balances[other][person],
                })
            done.add((person, other))
            done.add((other, person))

    # Net balances
    net = {p: 0.0 for p in people}
    for person in people:
        for other in people:
            if person != other:
                net[person] += balances[person][other]

    debtors = []
    creditors = []
    for person, balance in net.items():
        if balance < -0.01:
            debtors.append([person, -balance])
        elif balance > 0.01:
            creditors.append([person, balance])

    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)

    simplified = []
    i = 0
    j = 0
    while i < len(debtors) and j < len(creditors):
        debtor_name, debt_amt = debtors[i]
        creditor_name, cred_amt = creditors[j]

        settle_amt = min(debt_amt, cred_amt)
        simplified.append({
            "from": debtor_name,
            "to": creditor_name,
            "amount": settle_amt,
        })

        debtors[i][1] -= settle_amt
        creditors[j][1] -= settle_amt

        if debtors[i][1] < 0.01:
            i += 1
        if creditors[j][1] < 0.01:
            j += 1

    total_spending = sum(details["amount"] for details in exp_sheet.values())
    summary = _render_summary(exp_sheet, original, balances, people, raw, simplified, total_spending)
    receipt = _render_receipt(exp_sheet, original, simplified)

    return {
        "ok": True,
        "people": people,
        "original_names": original,
        "expenses": exp_sheet,
        "raw_settlements": raw,
        "simplified_settlements": simplified,
        "summary": summary,
        "receipt": receipt,
        "total_spending": total_spending,
    }


def _render_summary(exp_sheet, original, balances, people, raw, simplified, total_spending) -> str:
    lines = []
    lines.append("==================================================")
    lines.append("               FULL EXPENSE SUMMARY               ")
    lines.append("==================================================")
    lines.append(f"TOTAL GROUP SPENDING: ₹ {total_spending:.2f}")
    lines.append("==================================================")
    lines.append("")
    lines.append("1) EXPENSE-WISE DETAILS:")
    lines.append("-" * 50)
    for exp, details in exp_sheet.items():
        lines.append(f"Expense: {exp}")
        lines.append(f"Amount: {details['amount']:.2f}")
        lines.append(f"Paid by: {original[details['payer']]}")

        if details["split_type"] == "all":
            lines.append("Split among: All")
        else:
            split_names = [original[split['name']] for split in details["split_details"]]
            payer_name = original[details['payer']]
            lines.append("Split Among: " + payer_name + "," + ", ".join(split_names))

        for split in details["split_details"]:
            lines.append(
                f"    {original[split['name']]} owes {original[details['payer']]}: {split['amount']:.2f}"
            )
        lines.append("-" * 50)

    lines.append("")
    lines.append("2) RAW BALANCES (Without Greedy Algorithm):")
    lines.append("-" * 50)
    if raw:
        for item in raw:
            lines.append(
                f"{original[item['from']]} owes {original[item['to']]} {item['amount']:.2f}"
            )
    else:
        lines.append("No debts to settle.")

    lines.append("")
    lines.append("3) FINAL SIMPLIFIED BALANCES (Greedy Algorithm):")
    lines.append("-" * 50)
    if simplified:
        for item in simplified:
            lines.append(
                f"{original[item['from']]} owes {original[item['to']]} {item['amount']:.2f}"
            )
    else:
        lines.append("All balances are settled! No one owes anything.")

    lines.append("==================================================")
    return "\n".join(lines)


def _render_receipt(exp_sheet, original, simplified) -> str:
    lines = []
    lines.append("EXPENSE SPLITTER RECEIPT")
    lines.append("=" * 50)
    lines.append("ITEMIZED EXPENSES")
    lines.append("-" * 50)
    total = 0.0
    for exp, details in exp_sheet.items():
        total += details["amount"]
        lines.append(f"{exp} | Paid by {original[details['payer']]} | Rs {details['amount']:.2f}")
    lines.append("-" * 50)
    lines.append(f"TOTAL: Rs {total:.2f}")
    lines.append("")
    lines.append("FINAL TRANSACTIONS")
    lines.append("-" * 50)
    if simplified:
        for item in simplified:
            lines.append(
                f"{original[item['from']]} pays {original[item['to']]} Rs {item['amount']:.2f}"
            )
    else:
        lines.append("All balances are settled. No payments needed.")
    lines.append("=" * 50)
    return "\n".join(lines)


@app.post("/api/compute")
def api_compute():
    payload = request.get_json(silent=True) or {}
    people = payload.get("people") or []
    expenses = payload.get("expenses") or []
    result = compute_summary(people, expenses)
    return jsonify(result)


@app.get("/api/auth/status")
def api_auth_status():
    user = _current_user()
    return jsonify({"ok": True, "username": user})


@app.post("/api/auth/register")
def api_auth_register():
    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        return jsonify({"ok": False, "errors": ["Username and password are required."]}), 400

    users = _load_users()
    if username in users:
        return jsonify({"ok": False, "errors": ["Username already exists."]}), 400

    users[username] = {
        "password_hash": generate_password_hash(password),
    }
    _save_users(users)
    session["username"] = username
    return jsonify({"ok": True, "username": username})


@app.post("/api/auth/login")
def api_auth_login():
    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    users = _load_users()
    record = users.get(username)
    if not record or not check_password_hash(record.get("password_hash", ""), password):
        return jsonify({"ok": False, "errors": ["Invalid username or password."]}), 400

    session["username"] = username
    return jsonify({"ok": True, "username": username})


@app.post("/api/auth/logout")
def api_auth_logout():
    session.pop("username", None)
    return jsonify({"ok": True})


@app.get("/api/records")
def api_records_list():
    user, err, code = _require_user()
    if err:
        return err, code

    records = []
    user_dir = os.path.join(DATA_DIR, "users", secure_filename(user))
    os.makedirs(user_dir, exist_ok=True)
    for name in os.listdir(user_dir):
        if name.endswith(".json"):
            records.append(name[:-5])
    records.sort()
    return jsonify({"ok": True, "records": records})


@app.post("/api/records/save")
def api_records_save():
    user, err, code = _require_user()
    if err:
        return err, code
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    people = payload.get("people") or []
    expenses = payload.get("expenses") or []
    bill_token = payload.get("bill_token")
    if not name:
        return jsonify({"ok": False, "errors": ["Record name is required."]}), 400

    safe_name = secure_filename(name) or "record"
    user_dir = os.path.join(DATA_DIR, "users", secure_filename(user))
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.join(user_dir, f"{safe_name}.json")

    data = {
        "people": people,
        "expenses": expenses,
        "bill_token": bill_token,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return jsonify({"ok": True, "name": safe_name})


@app.post("/api/records/load")
def api_records_load():
    user, err, code = _require_user()
    if err:
        return err, code
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "errors": ["Record name is required."]}), 400

    safe_name = secure_filename(name) or "record"
    user_dir = os.path.join(DATA_DIR, "users", secure_filename(user))
    path = os.path.join(user_dir, f"{safe_name}.json")
    if not os.path.isfile(path):
        return jsonify({"ok": False, "errors": ["Record not found."]}), 404

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return jsonify({"ok": True, "data": data, "name": safe_name})


@app.post("/api/records/clear")
def api_records_clear():
    user, err, code = _require_user()
    if err:
        return err, code
    removed = 0
    user_dir = os.path.join(DATA_DIR, "users", secure_filename(user))
    os.makedirs(user_dir, exist_ok=True)
    for name in os.listdir(user_dir):
        if name.endswith(".json"):
            try:
                os.remove(os.path.join(user_dir, name))
                removed += 1
            except OSError:
                continue
    return jsonify({"ok": True, "removed": removed})


@app.post("/api/receipt")
def api_receipt():
    payload = request.get_json(silent=True) or {}
    people = payload.get("people") or []
    expenses = payload.get("expenses") or []
    bill_token = payload.get("bill_token")
    result = compute_summary(people, expenses)
    if not result.get("ok"):
        return jsonify(result), 400

    if canvas is None or ImageReader is None:
        return jsonify({
            "ok": False,
            "errors": ["PDF generation requires the 'reportlab' package. Please install it and restart."],
        }), 500

    pdf_data = _build_pdf_receipt(
        result["receipt"],
        bill_token,
        result.get("simplified_settlements") or [],
        result.get("original_names") or {},
    )
    return send_file(
        io.BytesIO(pdf_data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="expense-receipt.pdf",
    )


@app.post("/api/upload")
def api_upload():
    files = request.files.getlist("bills")
    if not files:
        return jsonify({"ok": False, "errors": ["No files received."]}), 400
    token = request.form.get("bill_token") or uuid.uuid4().hex
    expense_name = (request.form.get("expense_name") or "").strip()
    folder = os.path.join(UPLOAD_DIR, token)
    os.makedirs(folder, exist_ok=True)

    saved = []
    target_folder = folder
    label_key = None
    if expense_name:
        label_key = _label_key(expense_name, folder)
        target_folder = os.path.join(folder, label_key)
        os.makedirs(target_folder, exist_ok=True)
        _store_label(folder, label_key, expense_name)

    existing = len([name for name in os.listdir(target_folder) if not name.startswith(".")])
    for idx, file in enumerate(files, start=1):
        filename = secure_filename(file.filename or f"bill-{idx}.png")
        _, ext = os.path.splitext(filename)
        ext = ext or ".png"
        target = os.path.join(target_folder, f"bill-{existing + idx}{ext}")
        file.save(target)
        saved.append(target)

    return jsonify({"ok": True, "bill_token": token, "count": len(saved)})


@app.post("/api/upload-qr")
def api_upload_qr():
    files = request.files.getlist("qr")
    if not files:
        return jsonify({"ok": False, "errors": ["No QR file received."]}), 400
    token = request.form.get("bill_token") or uuid.uuid4().hex
    person = (request.form.get("person") or "").strip().lower()
    if not person:
        return jsonify({"ok": False, "errors": ["Person name is required."]}), 400

    folder = os.path.join(UPLOAD_DIR, token, "qr")
    os.makedirs(folder, exist_ok=True)

    saved = []
    for file in files[:1]:
        filename = secure_filename(file.filename or "upi-qr.png")
        _, ext = os.path.splitext(filename)
        ext = ext or ".png"
        target = os.path.join(folder, f"{secure_filename(person)}{ext}")
        file.save(target)
        saved.append(target)

    return jsonify({"ok": True, "bill_token": token, "count": len(saved)})


@app.post("/api/qr/clear")
def api_clear_qr():
    token = request.form.get("bill_token")
    person = (request.form.get("person") or "").strip().lower()
    if not token or not person:
        return jsonify({"ok": False, "errors": ["bill_token and person are required."]}), 400

    folder = os.path.join(UPLOAD_DIR, token, "qr")
    if not os.path.isdir(folder):
        return jsonify({"ok": True, "removed": 0})

    removed = 0
    base = secure_filename(person)
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = os.path.join(folder, f"{base}{ext}")
        if os.path.isfile(path):
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass

    return jsonify({"ok": True, "removed": removed})


def _build_pdf_receipt(
    text: str,
    bill_token: str | None,
    simplified: list,
    original: dict,
) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 48
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, "FairShare Receipt")
    y -= 26

    pdf.setFont("Helvetica", 10)
    for line in text.splitlines():
        if y < 80:
            pdf.showPage()
            y = height - 48
            pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, line)
        y -= 14

    if simplified:
        pdf.showPage()
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(40, height - 48, "Payment Sections")
        y = height - 80

        qr_folder = None
        if bill_token:
            qr_folder = os.path.join(UPLOAD_DIR, bill_token, "qr")

        max_width = width - 80
        for item in simplified:
            debtor = original.get(item["from"], item["from"])
            creditor_key = item["to"]
            creditor = original.get(creditor_key, creditor_key)
            amount = item["amount"]

            if y < 240:
                pdf.showPage()
                pdf.setFont("Helvetica-Bold", 14)
                pdf.drawString(40, height - 48, "Payment Sections (cont.)")
                y = height - 80

            pdf.setFont("Helvetica-Bold", 12)
            pdf.drawString(40, y, f"{debtor} owes {creditor}")
            y -= 18
            pdf.setFont("Helvetica", 11)
            pdf.drawString(40, y, f"Amount: Rs {amount:.2f}")
            y -= 16

            qr_path = None
            if qr_folder and os.path.isdir(qr_folder):
                base = secure_filename(creditor_key)
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    candidate = os.path.join(qr_folder, f"{base}{ext}")
                    if os.path.isfile(candidate):
                        qr_path = candidate
                        break

            if qr_path:
                try:
                    img = ImageReader(qr_path)
                    iw, ih = img.getSize()
                    scale = min(max_width / iw, 220 / ih)
                    draw_w = iw * scale
                    draw_h = ih * scale
                    pdf.drawImage(img, 40, y - draw_h, width=draw_w, height=draw_h)
                    y -= draw_h + 20
                except Exception:
                    pdf.drawString(40, y, "QR image could not be loaded.")
                    y -= 16
            else:
                pdf.drawString(40, y, "No QR code on file for this payee.")
                y -= 16

            y -= 8

    if bill_token:
        folder = os.path.join(UPLOAD_DIR, bill_token)
        if os.path.isdir(folder):
            labels = _load_labels(folder)
            subfolders = [
                name
                for name in os.listdir(folder)
                if os.path.isdir(os.path.join(folder, name))
                and not name.startswith(".")
                and name != "qr"
            ]
            images = [
                os.path.join(folder, name)
                for name in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, name)) and not name.startswith(".")
            ]

            if subfolders or images:
                pdf.showPage()
                pdf.setFont("Helvetica-Bold", 14)
                pdf.drawString(40, height - 48, "Bill Photos")
                y = height - 80

                max_width = width - 80

                def draw_image(path):
                    nonlocal y
                    if y < 200:
                        pdf.showPage()
                        pdf.setFont("Helvetica-Bold", 14)
                        pdf.drawString(40, height - 48, "Bill Photos (cont.)")
                        y = height - 80
                    try:
                        img = ImageReader(path)
                        iw, ih = img.getSize()
                        scale = min(max_width / iw, 420 / ih)
                        draw_w = iw * scale
                        draw_h = ih * scale
                        pdf.drawImage(img, 40, y - draw_h, width=draw_w, height=draw_h)
                        y -= draw_h + 24
                    except Exception:
                        pdf.setFont("Helvetica", 10)
                        pdf.drawString(40, y, f"Could not load image: {os.path.basename(path)}")
                        y -= 16

                for key in sorted(subfolders):
                    label = labels.get(key, key)
                    if y < 140:
                        pdf.showPage()
                        pdf.setFont("Helvetica-Bold", 14)
                        pdf.drawString(40, height - 48, "Bill Photos (cont.)")
                        y = height - 80
                    pdf.setFont("Helvetica-Bold", 12)
                    pdf.drawString(40, y, f"Expense: {label}")
                    y -= 18
                    pdf.setFont("Helvetica", 10)
                    paths = sorted(
                        [
                            os.path.join(folder, key, name)
                            for name in os.listdir(os.path.join(folder, key))
                            if not name.startswith(".")
                        ]
                    )
                    for path in paths:
                        draw_image(path)

                if images:
                    if y < 140:
                        pdf.showPage()
                        pdf.setFont("Helvetica-Bold", 14)
                        pdf.drawString(40, height - 48, "Bill Photos (cont.)")
                        y = height - 80
                    pdf.setFont("Helvetica-Bold", 12)
                    pdf.drawString(40, y, "Unlabeled photos")
                    y -= 18
                    pdf.setFont("Helvetica", 10)
                    for path in images:
                        draw_image(path)

    pdf.save()
    buffer.seek(0)
    return buffer.read()


def _labels_path(folder: str) -> str:
    return os.path.join(folder, "labels.json")


def _load_labels(folder: str) -> dict:
    path = _labels_path(folder)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _store_label(folder: str, key: str, label: str) -> None:
    labels = _load_labels(folder)
    labels[key] = label
    with open(_labels_path(folder), "w", encoding="utf-8") as f:
        json.dump(labels, f, ensure_ascii=False, indent=2)


def _label_key(name: str, folder: str) -> str:
    base = secure_filename(name).lower() or "expense"
    labels = _load_labels(folder)
    if base not in labels:
        return base
    suffix = 2
    while f"{base}-{suffix}" in labels:
        suffix += 1
    return f"{base}-{suffix}"


if __name__ == "__main__":
    app.run(debug=True)

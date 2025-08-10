import os
from flask import Flask, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import openai
from datetime import datetime, timedelta

# Load .env for local dev
load_dotenv()

# Init Flask
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "change_this_for_prod")

# Database URL from env; fallback to sqlite for local dev
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///local.db")
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# OpenAI
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_KEY:
    openai.api_key = OPENAI_KEY

# Models
class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    contact = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    suggestions = db.relationship("Suggestion", backref="customer", lazy=True)

class Suggestion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# Ensure tables exist
with app.app_context():
    db.create_all()

# Utility: generate AI suggestion for one customer (and save)
def generate_suggestion_for_customer(customer):
    # Compose prompt
    prompt = (
        f"Bạn là chuyên gia tư vấn phát triển kinh doanh cho cửa hàng sửa xe.\n"
        f"Khách hàng: {customer.name}\n"
        f"Contact: {customer.contact or 'không có'}\n"
        f"Ghi chú: {customer.notes or 'không có'}\n\n"
        "Hãy đưa ra 3 gợi ý CỤ THỂ, NGẮN GỌN và DỄ THỰC HIỆN để tăng doanh thu và chăm sóc khách hàng này."
    )

    if OPENAI_KEY:
        try:
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.7
            )
            content = resp["choices"][0]["message"]["content"].strip()
        except Exception as e:
            content = f"(Lỗi khi gọi AI: {e})"
    else:
        # fallback rule-based suggestion
        content = (
            "1) Gọi lại trong 7-10 ngày để hỏi thăm, kèm ưu đãi 10% lần sau.\n"
            "2) Ghi lại dịch vụ đã làm để gửi nhắc bảo dưỡng định kỳ.\n"
            "3) Tạo gói combo nhỏ phù hợp với nhu cầu khách."
        )

    # Save to DB
    sug = Suggestion(customer_id=customer.id, content=content)
    db.session.add(sug)
    db.session.commit()
    return content

# Home - list customers and add
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()
        notes = request.form.get("notes", "").strip()
        if not name:
            flash("Vui lòng nhập tên khách hàng.", "warning")
            return redirect(url_for("index"))
        c = Customer(name=name, contact=contact, notes=notes)
        db.session.add(c)
        db.session.commit()
        flash("Đã thêm khách hàng.", "success")
        return redirect(url_for("index"))

    customers = Customer.query.order_by(Customer.created_at.desc()).all()
    return render_template("index.html", customers=customers)

# Delete customer
@app.route("/delete/<int:cust_id>", methods=["POST"])
def delete_customer(cust_id):
    c = Customer.query.get_or_404(cust_id)
    db.session.delete(c)
    db.session.commit()
    flash("Đã xóa khách hàng.", "info")
    return redirect(url_for("index"))

# Page to manually request suggestions (one customer)
@app.route("/customer/<int:cust_id>/suggest", methods=["POST"])
def suggest_for_customer(cust_id):
    c = Customer.query.get_or_404(cust_id)
    content = generate_suggestion_for_customer(c)
    flash("Đã tạo gợi ý AI cho khách hàng.", "success")
    return redirect(url_for("index"))

# Suggest page that allows custom prompt and shows result
@app.route("/suggest", methods=["GET", "POST"])
def suggest():
    suggestion = None
    if request.method == "POST":
        extra = request.form.get("business_info", "").strip()
        # include latest customers up to 30
        customers = Customer.query.order_by(Customer.created_at.desc()).limit(30).all()
        cust_text = "\n".join([f"- {c.name}: {c.notes or ''}" for c in customers])
        prompt = f"Danh sách khách hàng:\n{cust_text}\n\nThông tin bổ sung:\n{extra}\n\nHãy đưa ra 5 gợi ý cụ thể để tăng doanh thu và chăm sóc khách hàng."
        if OPENAI_KEY:
            try:
                resp = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role":"user","content":prompt}],
                    max_tokens=600,
                    temperature=0.7
                )
                suggestion = resp["choices"][0]["message"]["content"].strip()
            except Exception as e:
                suggestion = f"(Lỗi khi gọi AI: {e})"
        else:
            suggestion = "Chưa cấu hình OPENAI_API_KEY — không thể gọi AI."
    return render_template("suggest.html", suggestion=suggestion)

# Endpoint to generate suggestions for multiple customers (used by scheduled job)
@app.route("/generate_all_suggestions", methods=["POST"])
def generate_all_suggestions():
    # Simple token-based protection
    secret = os.getenv("SUGGESTION_SECRET")
    token = request.headers.get("X-SUGGESTION-TOKEN") or request.args.get("token")
    if not secret or token != secret:
        abort(403)

    limit = int(request.args.get("limit", 20))
    # choose customers to generate for (e.g., newest)
    customers = Customer.query.order_by(Customer.created_at.desc()).limit(limit).all()
    generated = []
    for c in customers:
        # optional: skip if last suggestion < 7 days
        last = Suggestion.query.filter_by(customer_id=c.id).order_by(Suggestion.created_at.desc()).first()
        if last and (datetime.utcnow() - last.created_at) < timedelta(days=7):
            continue
        content = generate_suggestion_for_customer(c)
        generated.append({"id": c.id, "name": c.name})
    return jsonify({"status":"ok", "generated": len(generated)}), 200

# Healthcheck
@app.route("/healthz")
def healthz():
    return jsonify({"status":"ok"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug=False in production
    app.run(host="0.0.0.0", port=port, debug=False)

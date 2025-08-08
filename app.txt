from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
import openai

# Khởi tạo Flask
app = Flask(__name__)

# Đọc API key từ biến môi trường (Render yêu cầu bảo mật)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Tạo DB nếu chưa có
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        contact TEXT,
        notes TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# Trang chính: hiển thị & thêm khách hàng
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        name = request.form["name"]
        contact = request.form["contact"]
        notes = request.form["notes"]

        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute("INSERT INTO customers (name, contact, notes) VALUES (?, ?, ?)",
                  (name, contact, notes))
        conn.commit()
        conn.close()

        return redirect(url_for("index"))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT * FROM customers")
    customers = c.fetchall()
    conn.close()
    return render_template("index.html", customers=customers)

# Gợi ý từ AI
@app.route("/suggest")
def suggest():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT name, notes FROM customers")
    data = c.fetchall()
    conn.close()

    # Ghép dữ liệu thành một đoạn mô tả
    prompt = "Dưới đây là danh sách khách hàng và ghi chú:\n"
    for name, notes in data:
        prompt += f"- {name}: {notes}\n"
    prompt += "\nHãy gợi ý chiến lược phát triển kinh doanh và chăm sóc khách hàng."

    try:
        ai_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        suggestion = ai_response["choices"][0]["message"]["content"]
    except Exception as e:
        suggestion = f"Lỗi khi gọi AI: {e}"

    return render_template("suggest.html", suggestion=suggestion)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

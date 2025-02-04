import os
import time
import uuid
import hashlib
import json
import requests
import threading

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------
# Глобальные конфиги (замените на ваши реальные данные)
# ---------------------------
MERCHANT_USER_ID = "51395"
SECRET_KEY       = "ES2yTUu7AzetuW2"
SERVICE_ID       = 66183
PHONE_NUMBER     = "+998903267962"  # Для create_invoice по умолчанию

# Хранилище заказов в памяти (для демонстрации)
orders = {}

# ---------------------------
# Функция генерации заголовка Auth для Click
# ---------------------------
def generate_auth_header():
    timestamp = str(int(time.time()))
    digest = hashlib.sha1((timestamp + SECRET_KEY).encode('utf-8')).hexdigest()
    return f"{MERCHANT_USER_ID}:{digest}:{timestamp}"

# ---------------------------
# Endpoint: /click-api/create_invoice
# Создание инвойса через реальный Click API
# ---------------------------
@app.route("/click-api/create_invoice", methods=["POST"])
def create_invoice():
    required_fields = ["merchant_trans_id", "amount", "phone_number"]
    for field in required_fields:
        if field not in request.form:
            return jsonify({"error": "-8", "error_note": f"Missing required field: {field}"}), 400

    merchant_trans_id = request.form["merchant_trans_id"]
    amount = float(request.form["amount"])   # сумма в сумах
    phone_number = request.form["phone_number"]

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Auth": generate_auth_header(),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    payload = {
        "service_id": SERVICE_ID,
        "amount": amount,
        "phone_number": phone_number,
        "merchant_trans_id": merchant_trans_id
    }

    try:
        resp = requests.post("https://api.click.uz/v2/merchant/invoice/create",
                             headers=headers,
                             json=payload,
                             timeout=30)
        if resp.status_code != 200:
            return jsonify({
                "error": "-9",
                "error_note": "Failed to create invoice",
                "http_code": resp.status_code,
                "response": resp.text
            }), 200
        return jsonify(resp.json()), 200
    except Exception as e:
        return jsonify({"error": "-9", "error_note": str(e)}), 200

# ---------------------------
# Endpoint: /click-api/prepare
# Эмуляция callback "prepare"
# ---------------------------
@app.route("/click-api/prepare", methods=["POST"])
def prepare():
    required_fields = ["click_trans_id", "merchant_trans_id", "amount"]
    for field in required_fields:
        if field not in request.form:
            return jsonify({"error": "-8", "error_note": f"Missing required field: {field}"}), 400

    click_trans_id = request.form["click_trans_id"]
    merchant_trans_id = request.form["merchant_trans_id"]
    amount = float(request.form["amount"])  # тийины

    orders[merchant_trans_id] = {
        "id": merchant_trans_id,
        "total": amount,
        "is_paid": False,
        "click_trans_id": click_trans_id,
        "status": "pending"
    }

    response = {
        "click_trans_id": click_trans_id,
        "merchant_trans_id": merchant_trans_id,
        "merchant_prepare_id": merchant_trans_id,
        "error": "0",
        "error_note": "Success"
    }
    return jsonify(response)

# ---------------------------
# Endpoint: /click-api/complete
# Эмуляция callback "complete" + фискализация
# ---------------------------
@app.route("/click-api/complete", methods=["POST"])
def complete():
    required_fields = ["click_trans_id", "merchant_trans_id", "merchant_prepare_id", "amount"]
    for field in required_fields:
        if field not in request.form:
            return jsonify({"error": "-8", "error_note": f"Missing required field: {field}"}), 400

    click_trans_id = request.form["click_trans_id"]
    merchant_trans_id = request.form["merchant_trans_id"]
    merchant_prepare_id = request.form["merchant_prepare_id"]
    amount = float(request.form["amount"])  # тийины

    if merchant_trans_id not in orders:
        return jsonify({"error": "-5", "error_note": "Order does not exist"}), 404

    order = orders[merchant_trans_id]
    if order["is_paid"]:
        return jsonify({"error": "-4", "error_note": "Already paid"}), 400

    if abs(order["total"] - amount) > 0.01:
        return jsonify({"error": "-2", "error_note": "Incorrect parameter amount"}), 400

    # Помечаем заказ как оплаченный
    order["is_paid"] = True
    order["status"] = "processing"

    # Фискальные данные (жёстко)
    good_price_tiyin = 50000
    quantity = 2
    price_total = good_price_tiyin * quantity
    vat = round((price_total / 1.12) * 0.12)

    fiscal_items = [{
        "Name": "БОКАЛ КЕРАМИЧЕСКИЙ",
        "SPIC": "06912001036000000",
        "PackageCode": "1184747",
        "GoodPrice": good_price_tiyin,
        "Price": price_total,
        "Amount": quantity,
        "VAT": vat,
        "VATPercent": 12,
        "CommissionInfo": {"TIN": "307022362"}
    }]

    # Отправка фискальных данных
    # POST https://api.click.uz/v2/merchant/payment/ofd_data/submit_items
    fiscal_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Auth": generate_auth_header(),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    fiscal_payload = {
        "service_id": SERVICE_ID,
        "payment_id": click_trans_id,  # click_trans_id
        "items": fiscal_items,
        "received_ecash": price_total,  # вся сумма (тийины)
        "received_cash": 0,
        "received_card": 0
    }

    try:
        resp_fiscal = requests.post(
            "https://api.click.uz/v2/merchant/payment/ofd_data/submit_items",
            headers=fiscal_headers,
            json=fiscal_payload,
            timeout=30
        )
        if resp_fiscal.status_code == 200:
            fiscal_result = resp_fiscal.json()
        else:
            fiscal_result = {"error_code": -1, "raw": resp_fiscal.text}
    except Exception as e:
        fiscal_result = {"error_code": -1, "error_note": str(e)}

    response = {
        "click_trans_id": click_trans_id,
        "merchant_trans_id": merchant_trans_id,
        "merchant_confirm_id": merchant_prepare_id,
        "error": "0",
        "error_note": "Success",
        "fiscal_items": fiscal_items,
        "fiscal_response": fiscal_result
    }
    return jsonify(response)

# ---------------------------
# Автопинг (чтобы Render не засыпал)
# ---------------------------
def autopinger():
    """
    Функция в отдельном потоке.
    Каждые 5 минут пингует SELF_URL, если он задан в переменных окружения.
    """
    while True:
        time.sleep(300)  # каждые 5 минут
        self_url = os.getenv("SELF_URL")
        if self_url:
            try:
                print("[AUTO-PING] Пингуем:", self_url)
                requests.get(self_url, timeout=10)
            except Exception as e:
                print("[AUTO-PING] Ошибка при пинге:", e)
        else:
            print("[AUTO-PING] SELF_URL не установлен. Ожидаем...")

def run_autopinger_thread():
    thread = threading.Thread(target=autopinger, daemon=True)
    thread.start()

# ---------------------------
# Точка входа
# ---------------------------
if __name__ == "__main__":
    run_autopinger_thread()
    # Запускаем приложение на 0.0.0.0:5000
    # Render будет использовать gunicorn, но локально можно debug=True
    app.run(host="0.0.0.0", port=5000, debug=True)

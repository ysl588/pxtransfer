from flask import Flask, request, jsonify, render_template
from datetime import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ===== 全局變量 =====
requests = []
current_queue_id = 1
last_reset_date = datetime.now().date()
signed_in_porters = set()

# ======= 頁面 =======
@app.route('/')
def index():
    return render_template('dashboard.html')


# ======= 請求功能 =======
@app.route('/request', methods=['POST'])
def request_transport():
    global current_queue_id, last_reset_date

    data = request.get_json()
    from_floor = data.get("from")
    to_floor = data.get("to")
    urgent = data.get("urgent", False)

    today = datetime.now().date()
    if today != last_reset_date:
        current_queue_id = 1
        last_reset_date = today

    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")

    new_request = {
        "id": current_queue_id,
        "from": from_floor,
        "to": to_floor,
        "time": current_time,
        "status": "waiting",
        "status_time": current_time,
        "porter": None,
        "urgent": urgent,
        "timestamp": now.timestamp()
    }

    requests.append(new_request)
    current_queue_id += 1
    return jsonify({"message": "Request created", "request": new_request}), 201


@app.route('/queue', methods=['GET'])
def get_queue():
    sorted_requests = sorted(requests, key=lambda r: r["timestamp"])
    return jsonify(sorted_requests)


@app.route('/pickup', methods=['POST'])
def pickup():
    data = request.get_json()
    porter = data.get("porter")
    req_id = int(data.get("id"))

    for req in requests:
        if req["id"] == req_id and req["status"] == "waiting":
            req["status"] = "pick up"
            req["status_time"] = datetime.now().strftime("%H:%M:%S")
            req["porter"] = porter
            break

    return jsonify({"message": "Picked up"})


@app.route('/start', methods=['POST'])
def start_transport():
    data = request.get_json()
    req_id = int(data.get("id"))

    for req in requests:
        if req["id"] == req_id and req["status"] == "pick up":
            req["status"] = "start transport"
            req["status_time"] = datetime.now().strftime("%H:%M:%S")
            break

    return jsonify({"message": "Started"})


@app.route('/done', methods=['POST'])
def done():
    data = request.get_json()
    req_id = int(data.get("id"))

    for req in requests:
        if req["id"] == req_id and req["status"] == "start transport":
            req["status"] = "finished"
            req["status_time"] = datetime.now().strftime("%H:%M:%S")
            break

    return jsonify({"message": "Completed"})


@app.route('/undo', methods=['POST'])
def undo():
    data = request.get_json()
    req_id = int(data.get("id"))

    for req in requests:
        if req["id"] == req_id and req["status"] != "waiting":
            req["status"] = "waiting"
            req["status_time"] = datetime.now().strftime("%H:%M:%S")
            req["porter"] = None
            break

    return jsonify({"message": "Undone"})


@app.route('/cancel_pickup', methods=['POST'])
def cancel_pickup():
    data = request.get_json()
    req_id = int(data.get("id"))

    for req in requests:
        if req["id"] == req_id and req["status"] == "pick up":
            req["status"] = "waiting"
            req["status_time"] = datetime.now().strftime("%H:%M:%S")
            req["porter"] = None
            break

    return jsonify({"message": "Pickup canceled"})


@app.route('/cancel', methods=['POST'])
def cancel():
    global requests
    data = request.get_json()
    req_id = int(data.get("id"))
    requests = [r for r in requests if r["id"] != req_id]
    return jsonify({"message": "Cancelled"})


# ======= 人員登入 =======
@app.route('/sign_in', methods=['POST'])
def porter_sign_in():
    data = request.get_json()
    porter = data.get("porter")
    signed_in_porters.add(porter)
    return jsonify({"message": "Signed in"})


@app.route('/available_porters', methods=['GET'])
def available_porters():
    active = set(req["porter"] for req in requests if req["porter"] and req["status"] != "finished")
    available = [{"porter": p, "status": "available" if p not in active else "busy"} for p in signed_in_porters]
    return jsonify(available)


@app.route('/requester_sign_in', methods=['POST'])
def requester_sign_in():
    return jsonify({"message": "Requester signed in"})


if __name__ == '__main__':
    app.run(debug=True)

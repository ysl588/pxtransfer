from flask import Flask, request, Response, jsonify
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import uuid
import time

app = Flask(__name__)
queue = []
porters = set()
porter_assignments = {}  # maps porter => active request ID
next_id = 1
transport_logs = []
user_last_request_time = {}  # Track last request per user

# Scheduler
scheduler = BackgroundScheduler()
scheduler.start()

@app.route("/queue", methods=["GET"])
def get_queue():
    return jsonify(queue)

@app.route("/porters", methods=["GET"])
def get_porters():
    result = []
    for p in porters:
        status = "available" if porter_assignments.get(p) is None else "unavailable"
        result.append({"porter": p, "status": status})
    return jsonify(result)

@app.route("/stats", methods=["GET"])
def get_stats():
    completed = [r for r in queue if r["status"] == "finished" and "start_time" in r]
    if completed:
        avg = sum((r["last_updated"] - r["start_time"]).total_seconds() for r in completed) / len(completed) / 60
    else:
        avg = 0
    return jsonify({
        "completed_transports": len(completed),
        "average_transport_time": round(avg, 1),
        "log_count": len(transport_logs)
    })

@app.route("/logs", methods=["GET"])
def get_logs():
    return jsonify(transport_logs)

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    global next_id
    try:
        data = request.form if request.form else request.json
        incoming_msg = data.get("Body", "").strip().lower()
        sender = data.get("From")

        # Throttle to avoid 429
        now = time.time()
        last = user_last_request_time.get(sender, 0)
        if now - last < 1.2:
            return Response("⏳ Please wait a moment before sending another message.", mimetype="text/plain")
        user_last_request_time[sender] = now

        print(f"📩 Received WhatsApp from {sender}: {incoming_msg}")
        reply = ""

        if incoming_msg == "sign in":
            porters.add(sender)
            porter_assignments[sender] = None
            reply = "✅ Signed in as porter. You'll now receive assignments."

        elif incoming_msg == "sign out":
            porters.discard(sender)
            porter_assignments.pop(sender, None)
            reply = "👋 Signed out. You won't be auto-assigned."

        elif incoming_msg == "porters":
            if not porters:
                reply = "🛛 No porters are currently signed in."
            else:
                reply_lines = ["🧑‍🔧 Active Porters:"]
                for p in porters:
                    status = "available" if porter_assignments.get(p) is None else "unavailable"
                    reply_lines.append(f"{p[-10:]} - {status}")
                reply = "\n".join(reply_lines)

        elif incoming_msg.startswith("request "):
            try:
                text = incoming_msg[len("request "):]
                if " to " not in text:
                    raise ValueError("Invalid format")
                from_floor, to_rest = text.split(" to ", 1)
                to_parts = to_rest.split()
                to_floor = to_parts[0]
                rest = to_parts[1:]
                priority = "high" if any(r in ["*", "urgent"] for r in rest) else "normal"
                new_id = str(next_id)
                next_id = (next_id + 1) if next_id < 9999 else 1
                new_req = {
                    "id": new_id,
                    "from": from_floor.upper(),
                    "to": to_floor.upper(),
                    "status": "waiting",
                    "priority": priority,
                    "deadline": None,
                    "assigned_worker": None,
                    "last_updated": datetime.now(),
                    "requester": sender,
                    "created_time": datetime.now()
                }
                queue.append(new_req)
                reply = f"✅ Request created: {from_floor.upper()} ➞ {to_floor.upper()} (ID: {new_id})"
                if priority == "high":
                    reply += " 🚨 Urgent"
            except Exception as e:
                print("⚠️ Parsing error:", e)
                reply = "❌ Format error. Use: request 10/F to 3/F *"

        elif incoming_msg == "queue":
            active_reqs = [r for r in queue if r["status"] != "finished"]
            if not active_reqs:
                reply = "📜 No active requests in the queue."
            else:
                reply_lines = ["📋 Active Requests:"]
                for req in active_reqs:
                    created_str = req["created_time"].strftime("%H:%M")
                    line = f"🆔 {req['id']} | {req['from']} ➞ {req['to']} | {req['status'].capitalize()}"
                    if req["priority"] == "high":
                        line += " 🚨"
                    line += f" ⏰ {created_str}"
                    reply_lines.append(line)
                reply = "\n".join(reply_lines)

        elif incoming_msg.startswith("pickup "):
            if sender not in porters:
                return Response("❌ Only signed-in porters can pick up requests.", mimetype="text/plain")
            if porter_assignments.get(sender):
                return Response("⚠️ You are already assigned to a request.", mimetype="text/plain")
            req_id = incoming_msg.split("pickup ")[1].strip()
            matched = next((r for r in queue if r["id"] == req_id), None)
            if matched and matched["status"] == "waiting":
                matched["status"] = "pick up"
                matched["assigned_worker"] = sender
                matched["last_updated"] = datetime.now()
                porter_assignments[sender] = req_id
                reply = f"✅ Request {req_id} marked as 'pick up' 🛒"
                requester = matched.get("requester")
                if requester and requester != sender:
                    log = f"[{datetime.now()}] Notify {requester}: Request {req_id} picked up by {sender}"
                    transport_logs.append(log)
                    print(f"📣 {log}")
            else:
                reply = f"❌ No matching waiting request with ID: {req_id}"

        elif incoming_msg.startswith("start "):
            req_id = incoming_msg.split("start ")[1].strip()
            matched = next((r for r in queue if r["id"] == req_id), None)
            if matched and matched["status"] == "pick up" and matched["assigned_worker"] == sender:
                matched["status"] = "start transport"
                matched["start_time"] = datetime.now()
                matched["last_updated"] = datetime.now()
                reply = f"🚶 Transport for {req_id} started."
                requester = matched.get("requester")
                if requester and requester != sender:
                    log = f"[{datetime.now()}] Notify {requester}: Transport started by {sender} for request {req_id}"
                    transport_logs.append(log)
                    print(f"📣 {log}")
            else:
                reply = f"❌ Cannot start. No active pickup for ID: {req_id}"

        elif incoming_msg.startswith("done "):
            req_id = incoming_msg.split("done ")[1].strip()
            matched = next((r for r in queue if r["id"] == req_id), None)
            if matched and matched["status"] != "finished" and matched["assigned_worker"] == sender:
                matched["status"] = "finished"
                matched["last_updated"] = datetime.now()
                porter_assignments[sender] = None
                reply = f"✅ Request {req_id} marked as 'finished' ✅"
                log = f"[{datetime.now()}] Transport finished for {req_id} by {sender}"
                transport_logs.append(log)
            else:
                reply = f"❌ No matching active request with ID: {req_id}"

        elif incoming_msg.startswith("cancel "):
            req_id = incoming_msg.split("cancel ")[1].strip()
            matched = next((r for r in queue if r["id"] == req_id), None)
            if matched and matched["status"] != "finished":
                if matched["requester"] == sender or matched["assigned_worker"] == sender:
                    queue.remove(matched)
                    if matched["assigned_worker"]:
                        porter_assignments[matched["assigned_worker"]] = None
                    log = f"[{datetime.now()}] Request {req_id} cancelled by {sender}"
                    transport_logs.append(log)
                    reply = f"🗑️ Request {req_id} cancelled."
                else:
                    reply = "❌ You are not authorized to cancel this request."
            else:
                reply = f"❌ No matching active request with ID: {req_id}"

        else:
            reply = (
                "👋 Available commands:\n"
                "• request 10/F to 3/F * — new request\n"
                "• queue — view active requests\n"
                "• sign in / sign out — join or leave porter pool\n"
                "• porters — list signed-in porters\n"
                "• pickup <ID> — accept request\n"
                "• start <ID> — begin transport\n"
                "• done <ID> — mark complete\n"
                "• cancel <ID> — cancel a request you made or are assigned to"
            )

        print(f"📤 Reply to {sender}: {reply}")
        return Response(reply, mimetype="text/plain")

    except Exception as err:
        print("🔥 Unexpected error:", err)
        return Response("⚠️ An unexpected error occurred. Try again or use a valid command.\n\n👋 Send 'help' to see command list.", mimetype="text/plain")

if __name__ == "__main__":
    app.run(port=5000, debug=True)

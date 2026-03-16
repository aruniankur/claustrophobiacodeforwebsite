from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from pythonosc import dispatcher
from pythonosc import osc_server
import threading
import requests

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# ESP32 address (AP default)
ESP32_IP = "192.168.4.1"

# latest sensor values
unreal_value = 0

sensor_data = {
    "ir": 0,
    "red": 0,
    "bpm": 0,
    "finger": 0
}

# Stores previously sent trigger values in insertion order.
sent_values_history = {}
sent_values_counter = 0
MAX_SENT_HISTORY = 100

# Lock to protect sensor_data across threads
data_lock = threading.Lock()

# OSC Server configuration — port 9001 (Unreal Engine uses 9000)
OSC_PORT = 9001
UNREAL_DIRECT_PORT = 9003   # Unreal sends directly here (no ESP32 relay)

# OSC callback for Unreal Engine value
def unreal_value_handler(unused_addr, *args):
    global unreal_value

    if len(args) > 0:
        unreal_value = int(args[0])
        print(f"[UNREAL] Value received: {unreal_value}")


# OSC callback for sensor data
def osc_sensor_handler(unused_addr, *args):
    """Handle OSC messages from ESP32"""
    global sensor_data
    
    with data_lock:
        if len(args) >= 4:
            ir, red, bpm, finger = args[0], args[1], args[2], args[3]
            sensor_data["ir"] = int(ir)
            sensor_data["red"] = int(red)
            sensor_data["bpm"] = round(float(bpm), 1)
            sensor_data["finger"] = int(finger)
            print(f"Received OSC: IR={ir}, Red={red}, BPM={bpm}, Finger={finger}")
        elif len(args) >= 2:
            ir, red = args[0], args[1]
            sensor_data["ir"] = int(ir)
            sensor_data["red"] = int(red)
            sensor_data["finger"] = 1 if ir > 50000 else 0
            print(f"Received OSC: IR={ir}, Red={red}")


@app.route("/")
def index():
    return render_template("index.html")


# HTTP endpoint for sensor data (for backward compatibility)
@app.route("/sensor", methods=["POST"])
def sensor():
    global sensor_data

    try:
        data = request.json
        
        if data:
            sensor_data["ir"] = data.get("ir", sensor_data["ir"])
            sensor_data["red"] = data.get("red", sensor_data["red"])
            sensor_data["bpm"] = data.get("bpm", sensor_data["bpm"])
            sensor_data["finger"] = data.get("finger", sensor_data["finger"])

        return jsonify({"status": "ok", "data": sensor_data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# frontend fetches latest values
@app.route("/data")
def data():
    with data_lock:
        snapshot = dict(sensor_data)
        # Newest first for UI rendering in the left history panel.
        history_items = list(sent_values_history.items())
        sent_history_snapshot = [
            {"id": send_id, **values}
            for send_id, values in reversed(history_items)
        ]

    snapshot["unreal_value"] = unreal_value
    snapshot["sent_history"] = sent_history_snapshot
    return jsonify(snapshot)


# button trigger
@app.route("/trigger", methods=["POST"])
def trigger():
    try:
        global sent_values_counter

        data = request.json or {}
        msg1 = data.get("msg1", 0)
        msg2 = data.get("msg2", 0)
        msg3 = data.get("msg3", 0)
        msg4 = data.get("msg4", 0)

        url = f"http://{ESP32_IP}/message"
        response = requests.get(url, params={"msg1": msg1, "msg2": msg2, "msg3": msg3, "msg4": msg4}, timeout=5)

        with data_lock:
            sent_values_counter += 1
            sent_values_history[str(sent_values_counter)] = {
                "msg1": int(msg1),
                "msg2": int(msg2),
                "msg3": int(msg3),
                "msg4": int(msg4)
            }

            # Keep memory bounded by removing oldest records.
            while len(sent_values_history) > MAX_SENT_HISTORY:
                oldest_id = next(iter(sent_values_history))
                del sent_values_history[oldest_id]

        print(f"[TRIGGER] msg1(lang)={msg1} msg2={msg2} msg3={msg3} msg4={msg4}")
        return jsonify({"status": "sent", "msg1": msg1, "msg2": msg2, "msg3": msg3, "msg4": msg4}), 200
    except Exception as e:
        print(f"[TRIGGER] Error: {str(e)}")
        return jsonify({"status": "failed", "error": str(e)}), 500


def start_osc_server():
    """Start OSC server on port 9001 — receives ESP32 sensor data + relayed Unreal value"""
    disp = dispatcher.Dispatcher()
    disp.map("/sensor/value", osc_sensor_handler)
    disp.map("/unreal/value", unreal_value_handler)

    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", OSC_PORT), disp)
    print(f"[OSC] Python listening on port {OSC_PORT} (ESP32 sensor + relayed Unreal)")
    server.serve_forever()


def start_unreal_osc_server():
    """Start dedicated OSC server on port 9003 — Unreal sends directly here"""
    disp = dispatcher.Dispatcher()
    disp.map("/unreal/value", unreal_value_handler)

    server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", UNREAL_DIRECT_PORT), disp)
    print(f"[OSC] Python listening on port {UNREAL_DIRECT_PORT} (direct from Unreal)")
    server.serve_forever()


if __name__ == "__main__":
    import time

    # Start OSC server for ESP32 sensor data + relayed Unreal (port 9001)
    osc_thread = threading.Thread(target=start_osc_server, daemon=True)
    osc_thread.start()

    # Start dedicated OSC server for direct Unreal messages (port 9003)
    unreal_thread = threading.Thread(target=start_unreal_osc_server, daemon=True)
    unreal_thread.start()

    time.sleep(0.5)
    
    print("[INFO] Starting Flask server on http://0.0.0.0:4000")
    app.run(host="0.0.0.0", port=4000, debug=True)
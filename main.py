from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from pythonosc import dispatcher
from pythonosc import osc_server
import threading
import requests
import time
from datetime import datetime

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

# Connectivity heartbeat timestamps.
last_sensor_update_ts = 0.0
last_esp32_http_ok_ts = 0.0
SENSOR_STALE_SECONDS = 5
ESP32_HTTP_STALE_SECONDS = 15

# Active capture session state. Only one capture can run at a time.
active_capture = None


def _build_capture_entry(msg1, msg2, msg3, msg4, capture_delay_sec, capture_duration_sec, start_ts, end_ts):
    return {
        "msg1": int(msg1),
        "msg2": int(msg2),
        "msg3": int(msg3),
        "msg4": int(msg4),
        "sent_at": datetime.utcnow().isoformat() + "Z",
        "capture_delay_sec": capture_delay_sec,
        "capture_duration_sec": capture_duration_sec,
        "capture_complete": False,
        "capture_started_at": datetime.utcfromtimestamp(start_ts).isoformat() + "Z",
        "capture_end_at": datetime.utcfromtimestamp(end_ts).isoformat() + "Z",
        "capture_completed_at": None,
        "ir_values": [],
        "red_values": [],
        "bpm_values": []
    }


def _prune_history_locked():
    """Keep only the latest MAX_SENT_HISTORY experiment entries and always preserve 'control'."""
    experiment_keys = [k for k in sent_values_history.keys() if k != "control"]
    while len(experiment_keys) > MAX_SENT_HISTORY:
        oldest_id = experiment_keys.pop(0)
        if oldest_id in sent_values_history:
            del sent_values_history[oldest_id]

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
    global sensor_data, last_sensor_update_ts, active_capture
    
    with data_lock:
        if len(args) >= 4:
            ir, red, bpm, finger = args[0], args[1], args[2], args[3]
            sensor_data["ir"] = int(ir)
            sensor_data["red"] = int(red)
            sensor_data["bpm"] = round(float(bpm), 1)
            sensor_data["finger"] = int(finger)
            last_sensor_update_ts = time.time()
            print(f"Received OSC: IR={ir}, Red={red}, BPM={bpm}, Finger={finger}")
        elif len(args) >= 2:
            ir, red = args[0], args[1]
            sensor_data["ir"] = int(ir)
            sensor_data["red"] = int(red)
            sensor_data["finger"] = 1 if ir > 50000 else 0
            last_sensor_update_ts = time.time()
            print(f"Received OSC: IR={ir}, Red={red}")
            bpm = sensor_data["bpm"]
        else:
            return

        # If capture is active, append this sample during the capture window.
        if active_capture:
            now = time.time()
            if now > active_capture["end_ts"]:
                # Capture finished.
                entry = sent_values_history.get(active_capture["entry_id"])
                if entry:
                    entry["capture_complete"] = True
                    entry["capture_completed_at"] = datetime.utcnow().isoformat() + "Z"
                active_capture = None
            elif now >= active_capture["start_ts"]:
                entry = sent_values_history.get(active_capture["entry_id"])
                # Keep capture timer running, but only store samples when finger is detected.
                if entry and int(sensor_data.get("finger", 0)) == 1:
                    entry["ir_values"].append(int(sensor_data["ir"]))
                    entry["red_values"].append(int(sensor_data["red"]))
                    entry["bpm_values"].append(float(sensor_data["bpm"]))


def _finalize_capture_if_expired(now_ts):
    """Finalize active capture by time even if no new OSC packet arrives."""
    global active_capture

    if not active_capture:
        return

    if now_ts <= active_capture["end_ts"]:
        return

    entry = sent_values_history.get(active_capture["entry_id"])
    if entry:
        entry["capture_complete"] = True
        entry["capture_completed_at"] = datetime.utcnow().isoformat() + "Z"
    active_capture = None


@app.route("/")
def index():
    return render_template("index.html")


# HTTP endpoint for sensor data (for backward compatibility)
@app.route("/sensor", methods=["POST"])
def sensor():
    global sensor_data, last_sensor_update_ts

    try:
        data = request.json
        
        if data:
            with data_lock:
                sensor_data["ir"] = data.get("ir", sensor_data["ir"])
                sensor_data["red"] = data.get("red", sensor_data["red"])
                sensor_data["bpm"] = data.get("bpm", sensor_data["bpm"])
                sensor_data["finger"] = data.get("finger", sensor_data["finger"])
                last_sensor_update_ts = time.time()

        return jsonify({"status": "ok", "data": sensor_data}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


# frontend fetches latest values
@app.route("/data")
def data():
    now = time.time()

    with data_lock:
        _finalize_capture_if_expired(now)

        snapshot = dict(sensor_data)
        # Newest first for UI rendering in the left history panel.
        history_items = list(sent_values_history.items())
        sent_history_snapshot = [
            {
                "id": send_id,
                "msg1": values.get("msg1"),
                "msg2": values.get("msg2"),
                "msg3": values.get("msg3"),
                "msg4": values.get("msg4"),
                "sent_at": values.get("sent_at"),
                "capture_complete": values.get("capture_complete", False),
                "samples": len(values.get("ir_values", []))
            }
            for send_id, values in reversed(history_items)
            if send_id != "control"
        ]
        sensor_age_sec = round(now - last_sensor_update_ts, 2) if last_sensor_update_ts else None
        http_age_sec = round(now - last_esp32_http_ok_ts, 2) if last_esp32_http_ok_ts else None
        capture_in_progress = active_capture is not None
        capture_remaining_sec = 0
        capture_entry_id = None
        if active_capture:
            capture_remaining_sec = max(0, int(active_capture["end_ts"] - now))
            capture_entry_id = active_capture["entry_id"]
        capture_mode = active_capture["mode"] if active_capture else None

        control_entry = sent_values_history.get("control")
        control_snapshot = None
        if control_entry:
            control_snapshot = {
                "sent_at": control_entry.get("sent_at"),
                "capture_complete": control_entry.get("capture_complete", False),
                "samples": len(control_entry.get("ir_values", []))
            }

    esp32_connected = False
    if sensor_age_sec is not None and sensor_age_sec <= SENSOR_STALE_SECONDS:
        esp32_connected = True
    elif http_age_sec is not None and http_age_sec <= ESP32_HTTP_STALE_SECONDS:
        esp32_connected = True

    snapshot["unreal_value"] = unreal_value
    snapshot["sent_history"] = sent_history_snapshot
    snapshot["esp32_connected"] = esp32_connected
    snapshot["sensor_age_sec"] = sensor_age_sec
    snapshot["esp32_http_age_sec"] = http_age_sec
    snapshot["capture_in_progress"] = capture_in_progress
    snapshot["capture_remaining_sec"] = capture_remaining_sec
    snapshot["capture_entry_id"] = capture_entry_id
    snapshot["capture_mode"] = capture_mode
    snapshot["control_capture"] = control_snapshot
    return jsonify(snapshot)


# button trigger
@app.route("/trigger", methods=["POST"])
def trigger():
    try:
        global sent_values_counter, last_esp32_http_ok_ts, active_capture

        data = request.json or {}
        msg1 = data.get("msg1", 0)
        msg2 = data.get("msg2", 0)
        msg3 = data.get("msg3", 0)
        msg4 = data.get("msg4", 0)

        with data_lock:
            _finalize_capture_if_expired(time.time())
            if active_capture:
                remaining = max(0, int(active_capture["end_ts"] - time.time()))
                return jsonify({"status": "busy", "remaining_sec": remaining}), 409

        url = f"http://{ESP32_IP}/message"
        response = requests.get(url, params={"msg1": msg1, "msg2": msg2, "msg3": msg3, "msg4": msg4}, timeout=5)
        response.raise_for_status()
        last_esp32_http_ok_ts = time.time()

        with data_lock:
            sent_values_counter += 1
            new_id = str(sent_values_counter)
            capture_duration_sec = int(msg3) * 12
            capture_start_ts = time.time() + 2
            capture_end_ts = capture_start_ts + capture_duration_sec

            sent_values_history[new_id] = _build_capture_entry(
                msg1=msg1,
                msg2=msg2,
                msg3=msg3,
                msg4=msg4,
                capture_delay_sec=2,
                capture_duration_sec=capture_duration_sec,
                start_ts=capture_start_ts,
                end_ts=capture_end_ts,
            )

            active_capture = {
                "entry_id": new_id,
                "mode": "experiment",
                "start_ts": capture_start_ts,
                "end_ts": capture_end_ts
            }

            # Keep memory bounded by removing oldest records.
            _prune_history_locked()

        print(f"[TRIGGER] msg1(lang)={msg1} msg2={msg2} msg3={msg3} msg4={msg4}")
        return jsonify({"status": "sent", "id": new_id, "msg1": msg1, "msg2": msg2, "msg3": msg3, "msg4": msg4}), 200
    except Exception as e:
        print(f"[TRIGGER] Error: {str(e)}")
        return jsonify({"status": "failed", "error": str(e)}), 500


@app.route("/control-capture", methods=["POST"])
def control_capture():
    try:
        global active_capture

        with data_lock:
            _finalize_capture_if_expired(time.time())
            if active_capture:
                remaining = max(0, int(active_capture["end_ts"] - time.time()))
                return jsonify({"status": "busy", "remaining_sec": remaining}), 409

            capture_duration_sec = 20
            capture_start_ts = time.time()
            capture_end_ts = capture_start_ts + capture_duration_sec

            sent_values_history["control"] = _build_capture_entry(
                msg1=0,
                msg2=0,
                msg3=0,
                msg4=0,
                capture_delay_sec=0,
                capture_duration_sec=capture_duration_sec,
                start_ts=capture_start_ts,
                end_ts=capture_end_ts,
            )

            active_capture = {
                "entry_id": "control",
                "mode": "control",
                "start_ts": capture_start_ts,
                "end_ts": capture_end_ts
            }

        print("[CONTROL] Capture started for 20s")
        return jsonify({"status": "started", "id": "control", "duration_sec": 20}), 200
    except Exception as e:
        print(f"[CONTROL] Error: {str(e)}")
        return jsonify({"status": "failed", "error": str(e)}), 500


@app.route("/analytic")
def analytic_page():
    return render_template("analytic.html")


@app.route("/analytic-data/<send_id>")
def analytic_data(send_id):
    with data_lock:
        entry = sent_values_history.get(str(send_id))
        if not entry:
            return jsonify({"status": "not_found"}), 404

        payload = {
            "id": str(send_id),
            "msg1": entry.get("msg1"),
            "msg2": entry.get("msg2"),
            "msg3": entry.get("msg3"),
            "msg4": entry.get("msg4"),
            "sent_at": entry.get("sent_at"),
            "capture_delay_sec": entry.get("capture_delay_sec"),
            "capture_duration_sec": entry.get("capture_duration_sec"),
            "capture_complete": entry.get("capture_complete", False),
            "capture_started_at": entry.get("capture_started_at"),
            "capture_end_at": entry.get("capture_end_at"),
            "capture_completed_at": entry.get("capture_completed_at"),
            "ir_values": list(entry.get("ir_values", [])),
            "red_values": list(entry.get("red_values", [])),
            "bpm_values": list(entry.get("bpm_values", []))
        }

        control_entry = sent_values_history.get("control")
        payload["control"] = {
            "exists": bool(control_entry),
            "capture_complete": control_entry.get("capture_complete", False) if control_entry else False,
            "sent_at": control_entry.get("sent_at") if control_entry else None,
            "ir_values": list(control_entry.get("ir_values", [])) if control_entry else [],
            "red_values": list(control_entry.get("red_values", [])) if control_entry else [],
            "bpm_values": list(control_entry.get("bpm_values", [])) if control_entry else []
        }

    return jsonify(payload)


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
    # Start OSC server for ESP32 sensor data + relayed Unreal (port 9001)
    osc_thread = threading.Thread(target=start_osc_server, daemon=True)
    osc_thread.start()

    # Start dedicated OSC server for direct Unreal messages (port 9003)
    unreal_thread = threading.Thread(target=start_unreal_osc_server, daemon=True)
    unreal_thread.start()

    time.sleep(0.5)
    
    print("[INFO] Starting Flask server on http://0.0.0.0:4000")
    app.run(host="0.0.0.0", port=4000, debug=False, use_reloader=False)
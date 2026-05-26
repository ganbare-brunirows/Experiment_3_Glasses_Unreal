import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLOWorld, SAM
import threading
import os
import MeshyGlasses
import base64
from flask import Flask, request, jsonify
import torch

# ==========================================
# 0. DEVICE CONFIGURATION (GPU vs CPU)
# ==========================================
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f"--- AI System Initializing on device: {device.upper()} ---")

# ==========================================
# 1. INITIALIZE AI MODELS
# ==========================================
print("Loading YOLO-World (Open-Vocabulary)...")
yolo_model = YOLOWorld("yolov8s-worldv2.pt")
yolo_model.to(device)

print("Loading SAM (Segmenter)...")
sam_model = SAM("sam_b.pt")
sam_model.to(device)

box_annotator = sv.BoxAnnotator()
label_annotator = sv.LabelAnnotator()

# ==========================================
# 2. FLASK AI SERVER (ON-DEMAND)
# ==========================================
app = Flask(__name__)

# Variable to store the last voice prompt received
pending_prompt = None

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/trigger', methods=['POST'])
def process_on_demand():
    global pending_prompt
    data = request.json
    if not data or 'image' not in data:
        return jsonify({"status": "error", "message": "No image provided"}), 400

    prompt = data.get('prompt', 'object')
    pending_prompt = prompt
    print(f"\n[AI] Received request from phone. Prompting for: '{prompt}'")

    # 1. Decode Image from Phone
    try:
        img_data = base64.b64decode(data['image'])
        nparray = np.frombuffer(img_data, np.uint8)
        frame = cv2.imdecode(nparray, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"Error decoding image: {e}")
        return jsonify({"status": "error", "message": "Image decoding failed"}), 400

    # 2. Configure YOLO-World for the voice prompt
    yolo_model.set_classes([prompt])
    
    # Run Detection
    yolo_results = yolo_model.predict(frame, device=device, verbose=False)[0]
    yolo_det = sv.Detections.from_ultralytics(yolo_results)
    yolo_det = yolo_det[yolo_det.confidence > 0.3]

    if len(yolo_det) == 0:
        print(f"[AI] Could not find any '{prompt}' in the image.")
        return jsonify({"status": "error", "message": f"Object '{prompt}' not found"}), 200

    # 3. Run SAM using the best detection box
    print(f"[AI] Found '{prompt}'. Refining mask with SAM...")
    best_index = np.argmax(yolo_det.confidence)
    bboxes = [yolo_det.xyxy[best_index].tolist()]
    
    sam_results = sam_model(frame, bboxes=bboxes, device=device, verbose=False)[0]
    sam_det = sv.Detections.from_ultralytics(sam_results)

    if len(sam_det) > 0 and sam_det.mask is not None:
        mask = sam_det.mask[0]
        extracted_image = np.zeros_like(frame)
        extracted_image[mask] = frame[mask]
        
        # Crop to bounding box
        x1, y1, x2, y2 = yolo_det.xyxy[best_index]
        y1, y2, x1, x2 = max(0, int(y1)), min(frame.shape[0], int(y2)), max(0, int(x1)), min(frame.shape[1], int(x2))
        cropped = extracted_image[y1:y2, x1:x2]
        
        # Save locally for Meshy to use later
        cv2.imwrite("extracted_object.png", cropped)
        
        # 4. Return mask to phone (COMPRESSED JPEG TO PREVENT TIMEOUT)
        # Critical change: Use quality 70 for instant Wi-Fi delivery
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 70]
        _, buffer = cv2.imencode('.jpg', cropped, encode_param)
        mask_base64 = base64.b64encode(buffer).decode('utf-8')
        
        print(f"[AI] Success! Mask sent to phone. Size: {len(mask_base64)/1024:.1f} KB")
        return jsonify({
            "status": "success",
            "image": mask_base64
        }), 200

    return jsonify({"status": "error", "message": "SAM refinement failed"}), 200

@app.route('/approve', methods=['POST'])
def approve_meshy():
    global pending_prompt
    data = request.json
    if data and data.get('approved'):
        # Use the saved prompt or the one from the request
        prompt = data.get('prompt') or pending_prompt or 'object'
        print(f"\n[AUTHORIZATION] Approved! Starting Meshy 3D generation for '{prompt}'...")
        
        if os.path.exists("extracted_object.png"):
            threading.Thread(target=run_meshy, args=("extracted_object.png", prompt), daemon=True).start()
            return jsonify({"status": "meshy_started", "prompt": prompt}), 200
    
    print("\n[AUTHORIZATION] Cancelled or no image found.")
    return jsonify({"status": "cancelled"}), 200

def run_meshy(img_path, prompt):
    print(f"--- Calling Meshy API for object: {prompt} ---")
    task_id = MeshyGlasses.create_3d_model(img_path)
    if task_id:
        MeshyGlasses.download_3d_model(task_id, prompt)

if __name__ == '__main__':
    print("\n--- AI WORKER ONLINE (GPU ENABLED) ---")
    print("Listening on http://0.0.0.0:5000")
    print("Workflow: Gesture -> Voice Command -> Auto-Upload -> Approve on Phone")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
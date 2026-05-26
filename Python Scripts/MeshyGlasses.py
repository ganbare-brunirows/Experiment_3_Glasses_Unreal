import requests
import json
import time
import base64

# ==========================================
# SETUP
# ==========================================
MESHY_API_KEY = "msy_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"  # Replace this with your real API key
IMAGE_PATH = "extracted_object.png"

UPLOAD_URL = "https://api.meshy.ai/v1/image-to-3d"
WEBHOOK_URL = "https://webhook.example.com/your-webhook-endpoint"

headers = {
    "Authorization": f"Bearer {MESHY_API_KEY}",
    "Content-Type": "application/json"  # Tell the server this is JSON format
}

# ==========================================
# 0. WEBHOOK NOTIFICATION
# ==========================================
def notify_webhook(model_url, prompt):
    payload = {
        "meshy_link": model_url,
        "prompt": prompt
    }
    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        if response.ok:
            print(f"Webhook fired successfully: {WEBHOOK_URL}")
        else:
            print(f"Webhook error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Failed to send webhook: {e}")

# ==========================================
# 1. SEND IMAGE TO MESHY (VIA BASE64)
# ==========================================
def create_3d_model(image_path):
    print(f"Encoding {image_path} to Base64 and uploading to Meshy...")
    
    # Read image and convert to Base64 text
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        
    # Format as a standard Data URI
    base64_image_url = f"data:image/png;base64,{encoded_string}"
    
    # Send everything as a clean JSON dictionary
    payload = {
        "image_url": base64_image_url,
        "enable_pbr": True  # When sending JSON, Python booleans work correctly
    }
    
    # Note: Use json=payload instead of data=payload or files=files
    response = requests.post(UPLOAD_URL, headers=headers, json=payload)
        
    if response.status_code == 202 or response.status_code == 200:
        task_id = response.json()["result"]
        print(f"Success! Task ID: {task_id}")
        return task_id
    else:
        print(f"Error starting task: {response.text}")
        return None

# ==========================================
# 2. POLL FOR COMPLETION & DOWNLOAD
# ==========================================
def download_3d_model(task_id, prompt):
    poll_url = f"https://api.meshy.ai/v1/image-to-3d/{task_id}"
    
    print("Waiting for Meshy to generate the 3D model (this usually takes 1-3 minutes)...")
    
    while True:
        response = requests.get(poll_url, headers=headers)
        if response.status_code != 200:
            print(f"Error checking status: {response.text}")
            break
            
        data = response.json()
        status = data.get("status")
        
        if status == "SUCCEEDED":
            print("\n3D model generation completed!")
            
            # Meshy provides several formats; we'll use the .glb format
            model_url = data.get("model_urls", {}).get("glb")
            
            if model_url:
                print(f"Download URL: {model_url}")
                notify_webhook(model_url, prompt)
                print("Downloading .glb file...")
                
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"generated_object_{timestamp}.glb"
                
                model_data = requests.get(model_url)
                with open(filename, 'wb') as f:
                    f.write(model_data.content)
                    
                print(f"Saved as '{filename}'. Ready for Unreal Engine!")
            else:
                print("The model was generated, but the .glb file URL was not found.")
            break
            
        elif status in ["FAILED", "EXPIRED"]:
            print(f"Task failed: {data.get('task_error')}")
            break    
        else:
            progress = data.get("progress", 0)
            print(f"Status: {status} | Progreso: {progress}%", end="\r")
            time.sleep(5) 

# ==========================================
# EXECUTE
# ==========================================
if __name__ == "__main__":
    task_id = create_3d_model(IMAGE_PATH)
    if task_id:
        download_3d_model(task_id, "unknown")

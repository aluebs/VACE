# VACE Video Processing Server

A Flask-based HTTP server with async processing and progress tracking for long-running VACE tasks.

## Features

- **Async Processing**: Non-blocking video processing with background tasks
- **Progress Tracking**: Real-time progress updates with percentage and status messages
- **Job Management**: Submit jobs, monitor progress, and download results
- **Job Persistence**: Jobs survive server restarts with automatic recovery
- **Smart Recovery**: Automatically recovers existing jobs from filesystem on startup
- **Video Upload**: Accepts video files up to 500MB or video URLs
- **URL Support**: Download videos from HTTP/HTTPS URLs, including AWS S3 signed URLs
- **Text Prompts**: Process videos with custom text prompts
- **Depth Task**: Uses VACE's depth control task with Wan model
- **Ping Endpoint**: Health check for connectivity testing
- **Auto Cleanup**: Automatically removes old files after 24 hours
- **Error Handling**: Comprehensive error handling and logging

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Ensure VACE is Set Up**:
   - Make sure you have the VACE pipeline working
   - Ensure the Wan model is downloaded and configured
   - Test that `python vace/vace_pipeline.py --base wan --task depth` works

3. **Start the Server**:
   ```bash
   python vace_server.py
   ```

   The server will start on `http://0.0.0.0:5000` (accessible from any network interface).

## API Endpoints

### 1. Health Check (Ping)
```bash
GET /ping
```

**Response**:
```json
{
  "status": "ok",
  "message": "VACE server is running",
  "timestamp": 1234567890.123
}
```

### 2. Submit Video for Processing (Non-blocking)
```bash
POST /process
```

**Parameters (Form Upload)**:
- `video` (file): Video file to process (mp4, avi, mov, mkv, webm)
- `prompt` (text): Text prompt for video processing

**Parameters (URL Download)**:
- `video_url` (text): URL to video file (supports HTTP/HTTPS, including AWS S3 signed URLs)
- `prompt` (text): Text prompt for video processing

**Alternative Form Format**:
- `video_url` (text): URL to video file
- `prompt` (text): Text prompt for video processing

**Response**:
```json
{
  "job_id": "uuid-string",
  "status": "queued",
  "message": "Job submitted successfully. Use /status/{job_id} to check progress."
}
```

### 3. Get Job Status and Progress
```bash
GET /status/<job_id>
```

**Response**:
```json
{
  "id": "job-id",
  "status": "inference",
  "progress": 75,
  "message": "Inference step 30/40",
  "prompt": "Make this cinematic",
  "filename": "video.mp4",
  "created_at": "2024-01-01T10:00:00",
  "updated_at": "2024-01-01T10:15:00",
  "has_output": false
}
```

### 4. Download Processed Video
```bash
GET /download/<job_id>
```

**Response**: Returns the processed video file as download

### 5. List All Jobs
```bash
GET /jobs
```

**Response**:
```json
{
  "jobs": [
    {
      "id": "job-id",
      "status": "completed",
      "progress": 100,
      "message": "Processing completed successfully!",
      "created_at": "2024-01-01T10:00:00",
      "updated_at": "2024-01-01T10:20:00"
    }
  ],
  "total": 1
}
```

### 6. Server Status
```bash
GET /status
```

**Response**:
```json
{
  "status": "running",
  "jobs": {"completed": 5, "processing": 2, "queued": 1},
  "upload_files": 0,
  "result_directories": 8,
  "allowed_extensions": ["mp4", "avi", "mov", "mkv", "webm"],
  "max_file_size_mb": 500
}
```

### 7. Manual Cleanup
```bash
POST /cleanup
```

**Response**:
```json
{
  "message": "Cleanup completed successfully"
}
```

### 8. Job Recovery
```bash
POST /recover
```

**Response**:
```json
{
  "message": "Recovery completed successfully. Found 3 new jobs.",
  "recovered_jobs": 3,
  "total_jobs": 15
}
```

Manually triggers job recovery from the filesystem. This scans the `results/` directory for existing job folders and recovers any jobs that aren't already in the database. Useful if jobs were created before the persistence system was added.

## Usage Examples

### Using the Test Client

1. **Ping the server**:
   ```bash
   python test_client.py ping http://localhost:5000
   ```

2. **Check server status**:
   ```bash
   python test_client.py status http://localhost:5000
   ```

3. **Submit a job and monitor progress**:
   ```bash
   # With local file
   python test_client.py process http://localhost:5000 my_video.mp4 "Make this video look cinematic with enhanced depth"
   
   # With URL
   python test_client.py process http://localhost:5000 "https://example.com/video.mp4" "Make cinematic" --url
   ```

4. **Submit job only (non-blocking)**:
   ```bash
   # With local file
   python test_client.py submit http://localhost:5000 my_video.mp4 "Make cinematic"
   
   # With URL
   python test_client.py submit http://localhost:5000 "https://example.com/video.mp4" "Make cinematic" --url
   ```

5. **Monitor job progress**:
   ```bash
   python test_client.py monitor http://localhost:5000 <job_id>
   ```

6. **Download completed video**:
   ```bash
   python test_client.py download http://localhost:5000 <job_id>
   ```

7. **List all jobs**:
   ```bash
   python test_client.py jobs http://localhost:5000
   ```

8. **Recover jobs from filesystem**:
   ```bash
   python test_client.py recover http://localhost:5000
   ```

### Using curl

1. **Ping**:
   ```bash
   curl http://localhost:5000/ping
   ```

2. **Submit job with file**:
   ```bash
   curl -X POST \
     -F "video=@my_video.mp4" \
     -F "prompt=Make this video look cinematic" \
     http://localhost:5000/process
   ```

3. **Submit job with URL (JSON)**:
   ```bash
   curl -X POST \
     -H "Content-Type: application/json" \
     -d '{"video_url": "https://example.com/video.mp4", "prompt": "Make cinematic"}' \
     http://localhost:5000/process
   ```

4. **Submit job with URL (Form)**:
   ```bash
   curl -X POST \
     -F "video_url=https://example.com/video.mp4" \
     -F "prompt=Make this video look cinematic" \
     http://localhost:5000/process
   ```

5. **Check job status**:
   ```bash
   curl http://localhost:5000/status/<job_id>
   ```

6. **Download result**:
   ```bash
   curl http://localhost:5000/download/<job_id> --output processed_video.mp4
   ```

7. **Recover jobs**:
   ```bash
   curl -X POST http://localhost:5000/recover
   ```

### Using Python requests

```python
import requests
import time

# Ping server
response = requests.get('http://localhost:5000/ping')
print(response.json())

# Submit job
with open('my_video.mp4', 'rb') as video_file:
    files = {'video': video_file}
    data = {'prompt': 'Make this video look cinematic'}
    response = requests.post('http://localhost:5000/process', files=files, data=data)
    
    if response.status_code == 202:
        job_data = response.json()
        job_id = job_data['job_id']
        print(f"Job submitted: {job_id}")
        
        # Monitor progress
        while True:
            status_response = requests.get(f'http://localhost:5000/status/{job_id}')
            status = status_response.json()
            
            print(f"Progress: {status['progress']}% - {status['message']}")
            
            if status['status'] == 'completed':
                # Download result
                download_response = requests.get(f'http://localhost:5000/download/{job_id}')
                with open('processed_video.mp4', 'wb') as f:
                    f.write(download_response.content)
                print("Video processed and downloaded successfully!")
                break
            elif status['status'] == 'failed':
                print(f"Job failed: {status.get('error', 'Unknown error')}")
                break
            
            time.sleep(5)  # Check every 5 seconds
    else:
        print(f"Error: {response.json()}")
```

## Job Persistence and Recovery

The server automatically saves job information to `jobs_database.pkl` and can recover jobs after restarts:

### **Automatic Recovery on Startup**
- Scans `results/` directory for existing job folders
- Identifies valid UUID-named directories with video files
- Recovers jobs that aren't already in the database
- Uses smart file prioritization:
  1. `out_video.mp4` (main output)
  2. Files with "output", "result", "processed", "final" in name
  3. Any video file except intermediate files (src_mask, src_video, etc.)

### **Manual Recovery**
If you have jobs that aren't showing up (e.g., created before persistence was added):
```bash
# Using test client
python test_client.py recover http://localhost:5000

# Using curl
curl -X POST http://localhost:5000/recover
```

### **What Gets Recovered**
- Job ID (from directory name)
- Output video file (automatically detected)
- Status marked as "completed"
- Creation time (from directory timestamp)
- Prompt/filename marked as "Unknown (recovered job)"

### **Files Created**
- `jobs_database.pkl`: Persistent job database
- `uploads/`: Temporary upload storage (for both uploaded files and downloaded URLs)
- `results/<job_id>/`: Individual job result directories

## Video URL Support

The server supports processing videos from URLs in addition to file uploads:

### **Supported URL Types**
- HTTP/HTTPS URLs pointing to video files
- AWS S3 signed URLs (including accelerated endpoints)
- Any publicly accessible video URL

### **URL Processing Features**
- **Streaming Download**: Large videos are downloaded in chunks to handle memory efficiently
- **Size Validation**: URLs are checked against the same 500MB limit as file uploads
- **Format Detection**: File extension is automatically detected from URL or defaults to MP4
- **Error Handling**: Comprehensive error handling for network issues, timeouts, and invalid URLs

### **AWS S3 Integration**
The server works seamlessly with AWS S3 signed URLs, including:
- Standard S3 URLs (`s3.us-west-2.amazonaws.com`)
- S3 Transfer Acceleration URLs (`s3-accelerate.amazonaws.com`)
- Pre-signed URLs with query parameters
- Temporary access URLs

### **Usage Examples**

**JSON Request (Recommended)**:
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://your-bucket.s3.amazonaws.com/video.mp4?AWSAccessKeyId=...",
    "prompt": "Make this video cinematic"
  }' \
  http://localhost:5000/process
```

**Form Request**:
```bash
curl -X POST \
  -F "video_url=https://example.com/video.mp4" \
  -F "prompt=Make cinematic" \
  http://localhost:5000/process
```

**Test Client**:
```bash
python test_client.py process http://localhost:5000 "https://example.com/video.mp4" "Make cinematic" --url
```

## Configuration

You can modify these settings in `vace_server.py`:

- `MAX_CONTENT_LENGTH`: Maximum file size (default: 500MB)
- `ALLOWED_EXTENSIONS`: Allowed video file extensions
- `UPLOAD_FOLDER`: Directory for temporary uploads
- `RESULTS_FOLDER`: Directory for processing results
- `JOBS_DB_FILE`: Job database file (default: jobs_database.pkl)
- Port and host settings in the `app.run()` call

## External Access Setup (Cloudflare Tunnel)

Follow these steps to make your server accessible externally without a public IP:

### Step 1: Install Cloudflare Tunnel
```bash
chmod +x setup_cloudflare_tunnel.sh
./setup_cloudflare_tunnel.sh
```

### Step 2: Start your VACE server (in one terminal)
```bash
python vace_server.py
```

You should see output like:
```
Starting VACE Server...
Available endpoints:
  GET  /ping              - Health check
  POST /process           - Submit video for processing (non-blocking)
  GET  /status/<job_id>   - Get job status and progress
  GET  /download/<job_id> - Download processed video
  GET  /jobs              - List all jobs
  GET  /status            - Server status
  POST /cleanup           - Manual cleanup
  POST /recover           - Recover jobs from filesystem
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://YOUR_LOCAL_IP:5000
```

### Step 3: Create the Cloudflare tunnel (in another terminal)
```bash
cloudflared tunnel --url http://localhost:5000
```

You'll see output like:
```
2024-01-XX 10:30:45 INF Thank you for trying Cloudflare Tunnel...
2024-01-XX 10:30:46 INF +--------------------------------------------------------------------------------------------+
2024-01-XX 10:30:46 INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
2024-01-XX 10:30:46 INF |  https://random-words-123.trycloudflare.com                                               |
2024-01-XX 10:30:46 INF +--------------------------------------------------------------------------------------------+
```

### Step 4: Test the connection
```bash
# Replace with your actual tunnel URL
python test_client.py ping https://random-words-123.trycloudflare.com
```

You should see:
```
✓ Server is running: VACE server is running
```

### Step 5: Process a video
```bash
python test_client.py process https://random-words-123.trycloudflare.com your_video.mp4 "Make this video look cinematic with enhanced depth"
```

## Important Notes:
- **Keep both terminals running**: The VACE server and the cloudflared tunnel both need to stay active
- **The URL changes**: Each time you restart the tunnel, you get a new random URL
- **No account needed**: This works without signing up for Cloudflare
- **HTTPS included**: Your tunnel automatically gets SSL/TLS encryption

## Troubleshooting

1. **Server won't start**: Check if port 5000 is already in use
2. **Processing fails**: Check VACE pipeline works independently
3. **File upload fails**: Check file size and format
4. **Timeout errors**: Increase timeout values for large videos
5. **Memory issues**: Monitor GPU memory usage during processing

## Logs

The server logs all activities to the console. Key information includes:
- Request processing start/completion
- Error messages and stack traces
- File cleanup operations
- Server startup information

## Security Notes

- This server is designed for internal/trusted network use
- No authentication is implemented
- File uploads are temporarily stored on disk
- Consider adding authentication for production use 
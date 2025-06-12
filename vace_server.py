#!/usr/bin/env python3
"""
VACE Video Processing Server

A Flask server with async processing and progress tracking for long-running VACE tasks.
"""

import os
import uuid
import time
import shutil
import logging
import threading
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
from datetime import datetime
from collections import defaultdict
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
RESULTS_FOLDER = 'results'
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB max file size
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}

app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Create necessary directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

# Global storage for job status and progress
jobs = {}
job_lock = threading.Lock()

class JobStatus:
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    INFERENCE = "inference"
    COMPLETED = "completed"
    FAILED = "failed"

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def cleanup_old_files(directory, max_age_hours=24):
    """Clean up files older than max_age_hours."""
    try:
        current_time = time.time()
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getctime(file_path)
                if file_age > max_age_hours * 3600:  # Convert hours to seconds
                    os.remove(file_path)
                    logger.info(f"Cleaned up old file: {filename}")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")

def update_job_status(job_id, status, progress=None, message=None, error=None):
    """Update job status thread-safely."""
    with job_lock:
        if job_id in jobs:
            jobs[job_id]['status'] = status
            jobs[job_id]['updated_at'] = datetime.now().isoformat()
            if progress is not None:
                jobs[job_id]['progress'] = progress
            if message is not None:
                jobs[job_id]['message'] = message
            if error is not None:
                jobs[job_id]['error'] = error

def parse_vace_output(line, job_id):
    """Parse VACE pipeline output for progress information."""
    line = line.strip()
    if not line:
        return
    
    # Look for common progress indicators
    if "preprocess_output:" in line:
        update_job_status(job_id, JobStatus.INFERENCE, 50, "Preprocessing completed, starting inference...")
    elif "Loading model" in line or "loading" in line.lower():
        update_job_status(job_id, JobStatus.INFERENCE, 55, "Loading models...")
    elif "inference" in line.lower() and "step" in line.lower():
        # Try to extract step information
        try:
            if "/" in line:
                parts = line.split("/")
                if len(parts) >= 2:
                    current = int(''.join(filter(str.isdigit, parts[0])))
                    total = int(''.join(filter(str.isdigit, parts[1])))
                    progress = 50 + int((current / total) * 45)  # 50-95% for inference
                    update_job_status(job_id, JobStatus.INFERENCE, progress, f"Inference step {current}/{total}")
        except:
            pass
    elif "Saving" in line or "saving" in line.lower():
        update_job_status(job_id, JobStatus.INFERENCE, 95, "Saving results...")

def process_video_background(job_id, input_path, prompt, output_dir):
    """Background task to process video with progress tracking."""
    try:
        update_job_status(job_id, JobStatus.PREPROCESSING, 10, "Starting preprocessing...")
        
        # Run VACE pipeline with real-time output capture
        cmd = [
            'python', 'vace/vace_pipeline.py',
            '--base', 'wan',
            '--task', 'depth',
            '--video', input_path,
            '--prompt', prompt,
            '--save_dir', output_dir
        ]
        
        logger.info(f"Job {job_id}: Running command: {' '.join(cmd)}")
        
        # Start the process
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Read output line by line for progress tracking
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                logger.info(f"Job {job_id}: {output.strip()}")
                parse_vace_output(output, job_id)
        
        # Wait for process to complete
        return_code = process.poll()
        
        if return_code == 0:
            # Find the output video file
            output_files = []
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    if file.endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')):
                        output_files.append(os.path.join(root, file))
            
            if output_files:
                update_job_status(job_id, JobStatus.COMPLETED, 100, "Processing completed successfully!")
                with job_lock:
                    jobs[job_id]['output_file'] = output_files[0]
            else:
                update_job_status(job_id, JobStatus.FAILED, 0, error="No output video found")
        else:
            update_job_status(job_id, JobStatus.FAILED, 0, error="VACE pipeline failed")
            
    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}")
        update_job_status(job_id, JobStatus.FAILED, 0, error=str(e))
    finally:
        # Clean up input file
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
        except Exception as e:
            logger.warning(f"Failed to clean up input file: {str(e)}")

@app.route('/ping', methods=['GET'])
def ping():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'message': 'VACE server is running',
        'timestamp': time.time()
    })

@app.route('/process', methods=['POST'])
def process_video():
    """Submit video for processing (non-blocking)."""
    try:
        # Check if video file is present
        if 'video' not in request.files:
            return jsonify({'error': 'No video file provided'}), 400
        
        video_file = request.files['video']
        if video_file.filename == '':
            return jsonify({'error': 'No video file selected'}), 400
        
        # Check if prompt is provided
        prompt = request.form.get('prompt')
        if not prompt:
            return jsonify({'error': 'No prompt provided'}), 400
        
        # Validate file type
        if not allowed_file(video_file.filename):
            return jsonify({'error': f'File type not allowed. Allowed types: {ALLOWED_EXTENSIONS}'}), 400
        
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        logger.info(f"Received job {job_id} with prompt: {prompt}")
        
        # Save uploaded video
        filename = secure_filename(video_file.filename)
        file_extension = filename.rsplit('.', 1)[1].lower()
        input_filename = f"{job_id}_input.{file_extension}"
        input_path = os.path.join(UPLOAD_FOLDER, input_filename)
        video_file.save(input_path)
        
        # Create output directory for this job
        output_dir = os.path.join(RESULTS_FOLDER, job_id)
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize job status
        with job_lock:
            jobs[job_id] = {
                'id': job_id,
                'status': JobStatus.QUEUED,
                'progress': 0,
                'message': 'Job queued for processing',
                'prompt': prompt,
                'filename': filename,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'output_file': None,
                'error': None
            }
        
        # Start background processing
        thread = threading.Thread(
            target=process_video_background,
            args=(job_id, input_path, prompt, output_dir)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'job_id': job_id,
            'status': 'queued',
            'message': 'Job submitted successfully. Use /status/{job_id} to check progress.'
        }), 202
        
    except Exception as e:
        logger.error(f"Error submitting job: {str(e)}")
        return jsonify({'error': f'Failed to submit job: {str(e)}'}), 500

@app.route('/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    """Get status of a specific job."""
    with job_lock:
        if job_id not in jobs:
            return jsonify({'error': 'Job not found'}), 404
        
        job_info = jobs[job_id].copy()
        # Don't include the output file path in status response
        if 'output_file' in job_info:
            job_info['has_output'] = job_info['output_file'] is not None
            del job_info['output_file']
        
        return jsonify(job_info)

@app.route('/download/<job_id>', methods=['GET'])
def download_result(job_id):
    """Download the processed video for a completed job."""
    with job_lock:
        if job_id not in jobs:
            return jsonify({'error': 'Job not found'}), 404
        
        job = jobs[job_id]
        if job['status'] != JobStatus.COMPLETED:
            return jsonify({'error': f'Job not completed. Status: {job["status"]}'}), 400
        
        if not job['output_file'] or not os.path.exists(job['output_file']):
            return jsonify({'error': 'Output file not found'}), 404
        
        return send_file(
            job['output_file'],
            as_attachment=True,
            download_name=f"processed_{job_id}.mp4",
            mimetype='video/mp4'
        )

@app.route('/jobs', methods=['GET'])
def list_jobs():
    """List all jobs with their status."""
    with job_lock:
        job_list = []
        for job_id, job in jobs.items():
            job_summary = {
                'id': job_id,
                'status': job['status'],
                'progress': job['progress'],
                'message': job['message'],
                'created_at': job['created_at'],
                'updated_at': job['updated_at']
            }
            job_list.append(job_summary)
        
        # Sort by creation time (newest first)
        job_list.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({
            'jobs': job_list,
            'total': len(job_list)
        })

@app.route('/status', methods=['GET'])
def server_status():
    """Get server status and statistics."""
    try:
        with job_lock:
            status_counts = defaultdict(int)
            for job in jobs.values():
                status_counts[job['status']] += 1
        
        upload_count = len([f for f in os.listdir(UPLOAD_FOLDER) if os.path.isfile(os.path.join(UPLOAD_FOLDER, f))])
        result_count = len([f for f in os.listdir(RESULTS_FOLDER) if os.path.isdir(os.path.join(RESULTS_FOLDER, f))])
        
        return jsonify({
            'status': 'running',
            'jobs': dict(status_counts),
            'upload_files': upload_count,
            'result_directories': result_count,
            'allowed_extensions': list(ALLOWED_EXTENSIONS),
            'max_file_size_mb': MAX_CONTENT_LENGTH // (1024 * 1024)
        })
    except Exception as e:
        return jsonify({'error': f'Status check failed: {str(e)}'}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Manually trigger cleanup of old files and completed jobs."""
    try:
        cleanup_old_files(UPLOAD_FOLDER)
        cleanup_old_files(RESULTS_FOLDER)
        
        # Clean up old completed jobs (keep last 100)
        with job_lock:
            if len(jobs) > 100:
                sorted_jobs = sorted(jobs.items(), key=lambda x: x[1]['created_at'])
                jobs_to_remove = sorted_jobs[:-100]
                for job_id, _ in jobs_to_remove:
                    del jobs[job_id]
        
        return jsonify({'message': 'Cleanup completed successfully'})
    except Exception as e:
        return jsonify({'error': f'Cleanup failed: {str(e)}'}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File too large. Maximum size is 500MB.'}), 413

if __name__ == '__main__':
    # Clean up old files on startup
    cleanup_old_files(UPLOAD_FOLDER)
    cleanup_old_files(RESULTS_FOLDER)
    
    # Start the server
    logger.info("Starting VACE Server...")
    logger.info("Available endpoints:")
    logger.info("  GET  /ping              - Health check")
    logger.info("  POST /process           - Submit video for processing (non-blocking)")
    logger.info("  GET  /status/<job_id>   - Get job status and progress")
    logger.info("  GET  /download/<job_id> - Download processed video")
    logger.info("  GET  /jobs              - List all jobs")
    logger.info("  GET  /status            - Server status")
    logger.info("  POST /cleanup           - Manual cleanup")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    ) 
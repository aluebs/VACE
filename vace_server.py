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
import pickle
import requests
from urllib.parse import urlparse
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
RESULTS_FOLDER = 'results'
JOBS_DB_FILE = 'jobs_database.pkl'
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

def download_video_from_url(url, job_id):
    """Download video from URL and return local file path."""
    try:
        logger.info(f"Job {job_id}: Downloading video from URL: {url}")
        
        # Parse URL to get filename hint
        parsed_url = urlparse(url)
        url_filename = os.path.basename(parsed_url.path)
        
        # Determine file extension
        if url_filename and '.' in url_filename:
            file_extension = url_filename.rsplit('.', 1)[1].lower()
            if file_extension not in ALLOWED_EXTENSIONS:
                file_extension = 'mp4'  # Default fallback
        else:
            file_extension = 'mp4'  # Default fallback
        
        # Create local filename
        local_filename = f"{job_id}_input.{file_extension}"
        local_path = os.path.join(UPLOAD_FOLDER, local_filename)
        
        # Download the file with streaming to handle large files
        response = requests.get(url, stream=True, timeout=300)  # 5 minute timeout
        response.raise_for_status()
        
        # Check content length if available
        content_length = response.headers.get('content-length')
        if content_length and int(content_length) > MAX_CONTENT_LENGTH:
            raise ValueError(f"File too large: {int(content_length)} bytes (max: {MAX_CONTENT_LENGTH})")
        
        # Download with progress tracking
        total_size = 0
        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total_size += len(chunk)
                    
                    # Check size limit during download
                    if total_size > MAX_CONTENT_LENGTH:
                        f.close()
                        os.remove(local_path)
                        raise ValueError(f"File too large: {total_size} bytes (max: {MAX_CONTENT_LENGTH})")
        
        logger.info(f"Job {job_id}: Downloaded {total_size} bytes to {local_filename}")
        return local_path, url_filename or f"video.{file_extension}"
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Job {job_id}: Failed to download video from URL: {str(e)}")
        raise ValueError(f"Failed to download video: {str(e)}")
    except Exception as e:
        logger.error(f"Job {job_id}: Error downloading video: {str(e)}")
        raise ValueError(f"Error downloading video: {str(e)}")

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

def save_jobs_database():
    """Save jobs database to disk."""
    try:
        with open(JOBS_DB_FILE, 'wb') as f:
            pickle.dump(jobs, f)
    except Exception as e:
        logger.error(f"Failed to save jobs database: {str(e)}")

def recover_jobs_from_filesystem():
    """Recover jobs by scanning the results directory for existing job folders."""
    recovered_jobs = {}
    try:
        if os.path.exists(RESULTS_FOLDER):
            for item in os.listdir(RESULTS_FOLDER):
                item_path = os.path.join(RESULTS_FOLDER, item)
                if os.path.isdir(item_path):
                    # Check if this looks like a job ID (UUID format)
                    try:
                        uuid.UUID(item)  # Validate UUID format
                        job_id = item
                        
                        # Look for output video file
                        output_file = None
                        video_files = []
                        for root, dirs, files in os.walk(item_path):
                            for file in files:
                                if file.endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')):
                                    video_files.append(os.path.join(root, file))
                        
                        if video_files:
                            # Apply same prioritization logic as in processing
                            for file_path in video_files:
                                filename = os.path.basename(file_path)
                                if filename == 'out_video.mp4':
                                    output_file = file_path
                                    break
                            
                            if not output_file:
                                for file_path in video_files:
                                    filename = os.path.basename(file_path)
                                    if any(name in filename.lower() for name in ['output', 'result', 'processed', 'final']):
                                        output_file = file_path
                                        break
                            
                            if not output_file:
                                filtered_files = []
                                for file_path in video_files:
                                    filename = os.path.basename(file_path)
                                    if not any(name in filename.lower() for name in ['src_mask', 'src_video', 'mask', 'depth', 'flow', 'pose', 'input']):
                                        filtered_files.append(file_path)
                                
                                if filtered_files:
                                    output_file = filtered_files[0]
                                else:
                                    output_file = video_files[0]
                        
                        if output_file:
                            # Get file creation time for approximate job creation time
                            creation_time = datetime.fromtimestamp(os.path.getctime(item_path)).isoformat()
                            
                            recovered_jobs[job_id] = {
                                'id': job_id,
                                'status': JobStatus.COMPLETED,
                                'progress': 100,
                                'message': 'Recovered from filesystem',
                                'prompt': 'Unknown (recovered job)',
                                'filename': 'Unknown (recovered job)',
                                'created_at': creation_time,
                                'updated_at': creation_time,
                                'output_file': output_file,
                                'error': None
                            }
                            logger.info(f"Recovered job {job_id} with output: {os.path.basename(output_file)}")
                    
                    except ValueError:
                        # Not a valid UUID, skip
                        continue
        
        logger.info(f"Recovered {len(recovered_jobs)} jobs from filesystem")
        return recovered_jobs
    
    except Exception as e:
        logger.error(f"Failed to recover jobs from filesystem: {str(e)}")
        return {}

def load_jobs_database():
    """Load jobs database from disk."""
    global jobs
    try:
        if os.path.exists(JOBS_DB_FILE):
            with open(JOBS_DB_FILE, 'rb') as f:
                loaded_jobs = pickle.load(f)
                # Verify that output files still exist and update status if needed
                for job_id, job in loaded_jobs.items():
                    if job['status'] == JobStatus.COMPLETED and job.get('output_file'):
                        if not os.path.exists(job['output_file']):
                            job['status'] = JobStatus.FAILED
                            job['error'] = 'Output file no longer exists'
                            job['output_file'] = None
                    elif job['status'] in [JobStatus.QUEUED, JobStatus.PREPROCESSING, JobStatus.INFERENCE]:
                        # Mark running jobs as failed since they were interrupted
                        job['status'] = JobStatus.FAILED
                        job['error'] = 'Job interrupted by server restart'
                
                jobs = loaded_jobs
                logger.info(f"Loaded {len(jobs)} jobs from database")
        else:
            logger.info("No jobs database found, starting fresh")
            jobs = {}
        
        # Also try to recover any jobs from filesystem that aren't in the database
        recovered_jobs = recover_jobs_from_filesystem()
        for job_id, job in recovered_jobs.items():
            if job_id not in jobs:
                jobs[job_id] = job
        
        if recovered_jobs:
            # Save the updated database with recovered jobs
            save_jobs_database()
            
    except Exception as e:
        logger.error(f"Failed to load jobs database: {str(e)}")
        # If database loading fails, try to recover from filesystem
        jobs = recover_jobs_from_filesystem()
        if jobs:
            save_jobs_database()

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
            
            # Save to disk after each update
            save_jobs_database()

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
            # Find the output video file - prioritize out_video.mp4
            output_files = []
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    if file.endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')):
                        output_files.append(os.path.join(root, file))
            
            if output_files:
                # Prioritize out_video.mp4 as the main output
                main_output = None
                for file_path in output_files:
                    filename = os.path.basename(file_path)
                    if filename == 'out_video.mp4':
                        main_output = file_path
                        break
                
                # If out_video.mp4 not found, look for other common output names
                if not main_output:
                    for file_path in output_files:
                        filename = os.path.basename(file_path)
                        if any(name in filename.lower() for name in ['output', 'result', 'processed', 'final']):
                            main_output = file_path
                            break
                
                # If still not found, exclude known intermediate files and pick the first remaining
                if not main_output:
                    filtered_files = []
                    for file_path in output_files:
                        filename = os.path.basename(file_path)
                        # Exclude known intermediate/input files
                        if not any(name in filename.lower() for name in ['src_mask', 'src_video', 'mask', 'depth', 'flow', 'pose', 'input']):
                            filtered_files.append(file_path)
                    
                    if filtered_files:
                        main_output = filtered_files[0]
                    else:
                        main_output = output_files[0]  # Fallback to any video file
                
                update_job_status(job_id, JobStatus.COMPLETED, 100, "Processing completed successfully!")
                with job_lock:
                    jobs[job_id]['output_file'] = main_output
                    save_jobs_database()  # Save after setting output file
                logger.info(f"Job {job_id}: Selected output file: {os.path.basename(main_output)}")
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
        # Check if prompt is provided
        prompt = request.form.get('prompt') or request.json.get('prompt') if request.is_json else None
        if not prompt:
            return jsonify({'error': 'No prompt provided'}), 400
        
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        logger.info(f"Received job {job_id} with prompt: {prompt}")
        
        # Handle video input - either file upload or URL
        input_path = None
        filename = None
        
        # Check for video URL (JSON request)
        if request.is_json:
            video_url = request.json.get('video_url')
            if not video_url:
                return jsonify({'error': 'No video_url provided in JSON request'}), 400
            
            try:
                input_path, filename = download_video_from_url(video_url, job_id)
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
        
        # Check for video file upload (form request)
        elif 'video' in request.files:
            video_file = request.files['video']
            if video_file.filename == '':
                return jsonify({'error': 'No video file selected'}), 400
            
            # Validate file type
            if not allowed_file(video_file.filename):
                return jsonify({'error': f'File type not allowed. Allowed types: {ALLOWED_EXTENSIONS}'}), 400
            
            # Save uploaded video
            filename = secure_filename(video_file.filename)
            file_extension = filename.rsplit('.', 1)[1].lower()
            input_filename = f"{job_id}_input.{file_extension}"
            input_path = os.path.join(UPLOAD_FOLDER, input_filename)
            video_file.save(input_path)
        
        # Check for video_url in form data (alternative format)
        elif request.form.get('video_url'):
            video_url = request.form.get('video_url')
            try:
                input_path, filename = download_video_from_url(video_url, job_id)
            except ValueError as e:
                return jsonify({'error': str(e)}), 400
        
        else:
            return jsonify({'error': 'No video file or video_url provided'}), 400
        
        if not input_path or not os.path.exists(input_path):
            return jsonify({'error': 'Failed to process video input'}), 500
        
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
            # Save to disk immediately after creating job
            save_jobs_database()
        
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
                save_jobs_database()  # Save after cleanup
        
        return jsonify({'message': 'Cleanup completed successfully'})
    except Exception as e:
        return jsonify({'error': f'Cleanup failed: {str(e)}'}), 500

@app.route('/recover', methods=['POST'])
def recover_jobs():
    """Manually trigger job recovery from filesystem."""
    try:
        with job_lock:
            recovered_jobs = recover_jobs_from_filesystem()
            recovered_count = 0
            
            for job_id, job in recovered_jobs.items():
                if job_id not in jobs:
                    jobs[job_id] = job
                    recovered_count += 1
            
            if recovered_count > 0:
                save_jobs_database()
        
        return jsonify({
            'message': f'Recovery completed successfully. Found {recovered_count} new jobs.',
            'recovered_jobs': recovered_count,
            'total_jobs': len(jobs)
        })
    except Exception as e:
        return jsonify({'error': f'Recovery failed: {str(e)}'}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File too large. Maximum size is 500MB.'}), 413

if __name__ == '__main__':
    # Load existing jobs from database
    load_jobs_database()
    
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
    logger.info("  POST /recover           - Recover jobs from filesystem")
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False,
        threaded=True
    ) 
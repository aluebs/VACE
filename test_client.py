#!/usr/bin/env python3
"""
Test client for VACE Server

This script demonstrates how to interact with the VACE server.
"""

import requests
import sys
import time
import json

def ping_server(server_url):
    """Test if the server is running."""
    try:
        response = requests.get(f"{server_url}/ping", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Server is running: {data['message']}")
            return True
        else:
            print(f"✗ Server responded with status {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Failed to connect to server: {e}")
        return False

def get_server_status(server_url):
    """Get server status information."""
    try:
        response = requests.get(f"{server_url}/status", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print("Server Status:")
            print(f"  Status: {data['status']}")
            print(f"  Jobs: {data.get('jobs', {})}")
            print(f"  Upload files: {data['upload_files']}")
            print(f"  Result directories: {data['result_directories']}")
            print(f"  Allowed extensions: {', '.join(data['allowed_extensions'])}")
            print(f"  Max file size: {data['max_file_size_mb']} MB")
            return True
        else:
            print(f"✗ Failed to get status: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Failed to get status: {e}")
        return False

def submit_job(server_url, video_path, prompt):
    """Submit video processing job."""
    try:
        print(f"Submitting job...")
        print(f"Video: {video_path}")
        print(f"Prompt: {prompt}")
        
        with open(video_path, 'rb') as video_file:
            files = {'video': video_file}
            data = {'prompt': prompt}
            
            response = requests.post(
                f"{server_url}/process",
                files=files,
                data=data,
                timeout=30
            )
        
        if response.status_code == 202:
            result = response.json()
            job_id = result['job_id']
            print(f"✓ Job submitted successfully!")
            print(f"Job ID: {job_id}")
            print(f"Message: {result['message']}")
            return job_id
        else:
            try:
                error_data = response.json()
                print(f"✗ Job submission failed: {error_data.get('error', 'Unknown error')}")
            except:
                print(f"✗ Job submission failed with status {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"✗ Request failed: {e}")
        return None
    except FileNotFoundError:
        print(f"✗ Video file not found: {video_path}")
        return None

def get_job_status(server_url, job_id):
    """Get status of a specific job."""
    try:
        response = requests.get(f"{server_url}/status/{job_id}", timeout=10)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print(f"✗ Job {job_id} not found")
            return None
        else:
            print(f"✗ Failed to get job status: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"✗ Failed to get job status: {e}")
        return None

def monitor_job(server_url, job_id, check_interval=5):
    """Monitor job progress until completion."""
    print(f"\nMonitoring job {job_id}...")
    print("Press Ctrl+C to stop monitoring (job will continue running)")
    
    try:
        while True:
            status = get_job_status(server_url, job_id)
            if not status:
                break
            
            progress = status.get('progress', 0)
            message = status.get('message', 'No message')
            job_status = status.get('status', 'unknown')
            
            # Create progress bar
            bar_length = 30
            filled_length = int(bar_length * progress // 100)
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            
            print(f"\r[{bar}] {progress}% - {job_status}: {message}", end='', flush=True)
            
            if job_status in ['completed', 'failed']:
                print()  # New line
                if job_status == 'completed':
                    print(f"✓ Job completed successfully!")
                    return True
                else:
                    error = status.get('error', 'Unknown error')
                    print(f"✗ Job failed: {error}")
                    return False
            
            time.sleep(check_interval)
            
    except KeyboardInterrupt:
        print(f"\n⚠ Monitoring stopped. Job {job_id} is still running.")
        print(f"Check status with: {sys.argv[0]} status {server_url} {job_id}")
        return None

def download_result(server_url, job_id, output_filename=None):
    """Download the processed video."""
    try:
        if not output_filename:
            output_filename = f"processed_{job_id}_{int(time.time())}.mp4"
        
        print(f"Downloading result...")
        response = requests.get(f"{server_url}/download/{job_id}", timeout=60)
        
        if response.status_code == 200:
            with open(output_filename, 'wb') as f:
                f.write(response.content)
            print(f"✓ Video downloaded successfully: {output_filename}")
            return True
        else:
            try:
                error_data = response.json()
                print(f"✗ Download failed: {error_data.get('error', 'Unknown error')}")
            except:
                print(f"✗ Download failed with status {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"✗ Download failed: {e}")
        return False

def list_jobs(server_url):
    """List all jobs."""
    try:
        response = requests.get(f"{server_url}/jobs", timeout=10)
        if response.status_code == 200:
            data = response.json()
            jobs = data.get('jobs', [])
            total = data.get('total', 0)
            
            print(f"Total jobs: {total}")
            if jobs:
                print("\nRecent jobs:")
                print("-" * 80)
                print(f"{'Job ID':<36} {'Status':<12} {'Progress':<8} {'Created':<20}")
                print("-" * 80)
                
                for job in jobs[:10]:  # Show last 10 jobs
                    job_id = job['id'][:8] + "..."  # Truncate ID for display
                    status = job['status']
                    progress = f"{job['progress']}%"
                    created = job['created_at'][:19].replace('T', ' ')  # Format datetime
                    print(f"{job_id:<36} {status:<12} {progress:<8} {created:<20}")
            else:
                print("No jobs found.")
            return True
        else:
            print(f"✗ Failed to list jobs: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Failed to list jobs: {e}")
        return False

def recover_jobs(server_url):
    """Trigger job recovery from filesystem."""
    try:
        print("Triggering job recovery...")
        response = requests.post(f"{server_url}/recover", timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ {data['message']}")
            print(f"Recovered jobs: {data['recovered_jobs']}")
            print(f"Total jobs: {data['total_jobs']}")
            return True
        else:
            try:
                error_data = response.json()
                print(f"✗ Recovery failed: {error_data.get('error', 'Unknown error')}")
            except:
                print(f"✗ Recovery failed with status {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"✗ Recovery failed: {e}")
        return False

def process_video_complete(server_url, video_path, prompt, output_filename=None):
    """Complete workflow: submit job, monitor progress, and download result."""
    # Submit job
    job_id = submit_job(server_url, video_path, prompt)
    if not job_id:
        return False
    
    # Monitor progress
    success = monitor_job(server_url, job_id)
    if success:
        # Download result
        return download_result(server_url, job_id, output_filename)
    
    return False

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print(f"  {sys.argv[0]} ping <server_url>")
        print(f"  {sys.argv[0]} status <server_url>")
        print(f"  {sys.argv[0]} submit <server_url> <video_path> <prompt>")
        print(f"  {sys.argv[0]} monitor <server_url> <job_id>")
        print(f"  {sys.argv[0]} download <server_url> <job_id> [output_filename]")
        print(f"  {sys.argv[0]} jobs <server_url>")
        print(f"  {sys.argv[0]} recover <server_url>")
        print(f"  {sys.argv[0]} process <server_url> <video_path> <prompt> [output_filename]")
        print()
        print("Examples:")
        print(f"  {sys.argv[0]} ping http://localhost:5000")
        print(f"  {sys.argv[0]} process http://localhost:5000 video.mp4 'Make cinematic'")
        print(f"  {sys.argv[0]} jobs http://localhost:5000")
        print(f"  {sys.argv[0]} recover http://localhost:5000")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "ping":
        if len(sys.argv) != 3:
            print("Usage: ping <server_url>")
            sys.exit(1)
        server_url = sys.argv[2]
        ping_server(server_url)
        
    elif command == "status":
        if len(sys.argv) == 3:
            # Server status
            server_url = sys.argv[2]
            get_server_status(server_url)
        elif len(sys.argv) == 4:
            # Job status
            server_url = sys.argv[2]
            job_id = sys.argv[3]
            status = get_job_status(server_url, job_id)
            if status:
                print(json.dumps(status, indent=2))
        else:
            print("Usage: status <server_url> [job_id]")
            sys.exit(1)
        
    elif command == "submit":
        if len(sys.argv) != 5:
            print("Usage: submit <server_url> <video_path> <prompt>")
            sys.exit(1)
        server_url = sys.argv[2]
        video_path = sys.argv[3]
        prompt = sys.argv[4]
        submit_job(server_url, video_path, prompt)
        
    elif command == "monitor":
        if len(sys.argv) != 4:
            print("Usage: monitor <server_url> <job_id>")
            sys.exit(1)
        server_url = sys.argv[2]
        job_id = sys.argv[3]
        monitor_job(server_url, job_id)
        
    elif command == "download":
        if len(sys.argv) < 4 or len(sys.argv) > 5:
            print("Usage: download <server_url> <job_id> [output_filename]")
            sys.exit(1)
        server_url = sys.argv[2]
        job_id = sys.argv[3]
        output_filename = sys.argv[4] if len(sys.argv) == 5 else None
        download_result(server_url, job_id, output_filename)
        
    elif command == "jobs":
        if len(sys.argv) != 3:
            print("Usage: jobs <server_url>")
            sys.exit(1)
        server_url = sys.argv[2]
        list_jobs(server_url)
        
    elif command == "recover":
        if len(sys.argv) != 3:
            print("Usage: recover <server_url>")
            sys.exit(1)
        server_url = sys.argv[2]
        recover_jobs(server_url)
        
    elif command == "process":
        if len(sys.argv) < 5 or len(sys.argv) > 6:
            print("Usage: process <server_url> <video_path> <prompt> [output_filename]")
            sys.exit(1)
        server_url = sys.argv[2]
        video_path = sys.argv[3]
        prompt = sys.argv[4]
        output_filename = sys.argv[5] if len(sys.argv) == 6 else None
        process_video_complete(server_url, video_path, prompt, output_filename)
        
    else:
        print(f"Unknown command: {command}")
        print("Available commands: ping, status, submit, monitor, download, jobs, recover, process")
        sys.exit(1)

if __name__ == "__main__":
    main() 
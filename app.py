from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import yt_dlp
import tempfile
import os
import re
from pathlib import Path
import shutil
import asyncio
from typing import Generator

app = FastAPI()

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

def cleanup_temp_dir(temp_dir: str):
    """Clean up temporary directory after response is sent"""
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass  # Ignore cleanup errors

def sanitize_filename(filename):
    # First, normalize unicode characters
    import unicodedata
    filename = unicodedata.normalize('NFKD', filename)
    
    # Remove invalid characters and emojis
    filename = ''.join(c for c in filename if c.isascii() and (c.isalnum() or c in ' -_.,()[]{}'))
    filename = re.sub(r'\s+', ' ', filename)  # Replace multiple spaces with single space
    filename = filename.strip()  # Remove leading/trailing spaces
    
    if not filename:
        filename = "video"  # Fallback name if everything is stripped
    
    return filename[:200]  # Limit length to 200 chars

def is_valid_youtube_url(url):
    # YouTube URL patterns
    patterns = [
        r'^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'^https?://(?:www\.)?youtube\.com/v/[\w-]+',
        r'^https?://youtu\.be/[\w-]+',
        r'^https?://(?:www\.)?youtube\.com/embed/[\w-]+'
    ]
    return any(re.match(pattern, url) for pattern in patterns)

def get_video_info(url):
    ydl_opts = {
        'format': 'best',  # Get best quality
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'Unknown Title'),
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail'),
                'url': url,
                'filesize': info.get('filesize') or info.get('filesize_approx')
            }
        except Exception as e:
            raise Exception(f"Failed to fetch video info: {str(e)}")

def file_iterator(file_path: str, chunk_size: int = 1024 * 1024) -> Generator[bytes, None, None]:
    """Stream file in chunks to prevent memory issues with large files"""
    with open(file_path, 'rb') as f:
        while chunk := f.read(chunk_size):
            yield chunk

@app.get("/")
async def index():
    return FileResponse('static/index.html')

@app.post("/get-info")
async def fetch_video_info(request: Request):
    try:
        data = await request.json()
        url = data.get('url')
        
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")
            
        if not is_valid_youtube_url(url):
            raise HTTPException(status_code=400, detail="Invalid YouTube URL. Please provide a valid YouTube video URL.")

        info = get_video_info(url)
        return JSONResponse(content=info)
        
    except yt_dlp.utils.DownloadError as e:
        error_message = str(e)
        if "Private video" in error_message:
            raise HTTPException(status_code=403, detail="This video is private and cannot be accessed")
        elif "Video unavailable" in error_message:
            raise HTTPException(status_code=404, detail="This video is unavailable")
        else:
            raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download")
async def download_video(request: Request, background_tasks: BackgroundTasks):
    temp_dir = None
    try:
        data = await request.json()
        url = data.get('url')
        
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")

        if not is_valid_youtube_url(url):
            raise HTTPException(status_code=400, detail="Invalid YouTube URL. Please provide a valid YouTube video URL.")

        # Create a temporary directory for downloading
        temp_dir = tempfile.mkdtemp()
        
        try:
            # First, get video info and create a safe filename
            with yt_dlp.YoutubeDL({
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True
            }) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise HTTPException(status_code=404, detail="Could not fetch video information")
                
                # Create a safe filename
                video_title = sanitize_filename(info.get('title', 'video'))
                safe_filename = f"{video_title}.%(ext)s"
                
                # Download options with safe filename
                ydl_opts = {
                    'format': 'best',  # Get best quality
                    'outtmpl': os.path.join(temp_dir, safe_filename),
                    'quiet': True,
                    'no_warnings': True,
                    'merge_output_format': 'mp4'  # Force MP4 output
                }
                
                # Download the video
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                    
                    # Find the downloaded file
                    downloaded_files = [f for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                    if not downloaded_files:
                        raise HTTPException(status_code=500, detail="No file was downloaded")
                    
                    # Get the downloaded file
                    downloaded_file = os.path.join(temp_dir, downloaded_files[0])
                    if not os.path.exists(downloaded_file) or not os.path.getsize(downloaded_file):
                        raise HTTPException(status_code=500, detail="Downloaded file is empty or not found")
                    
                    # Create final output filename
                    output_filename = f"{video_title}.mp4"
                    
                    # Schedule cleanup after response is sent
                    background_tasks.add_task(cleanup_temp_dir, temp_dir)
                    
                    # Return a streaming response
                    return StreamingResponse(
                        file_iterator(downloaded_file),
                        media_type='video/mp4',
                        headers={
                            'Content-Disposition': f'attachment; filename="{output_filename}"',
                            'Cache-Control': 'no-cache'
                        },
                        background=background_tasks
                    )
                    
        except yt_dlp.utils.DownloadError as e:
            error_message = str(e).lower()
            if "private video" in error_message:
                raise HTTPException(status_code=403, detail="This video is private and cannot be accessed")
            elif "video unavailable" in error_message or "not available" in error_message:
                raise HTTPException(status_code=404, detail="This video is unavailable")
            elif "copyright" in error_message:
                raise HTTPException(status_code=403, detail="This video is not available due to copyright restrictions")
            else:
                raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
                
    except Exception as e:
        # Clean up temp directory if an error occurred
        if temp_dir and os.path.exists(temp_dir):
            cleanup_temp_dir(temp_dir)
            
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
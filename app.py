from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
import yt_dlp
import tempfile
import os
import re
from pathlib import Path

app = FastAPI()

def sanitize_filename(filename):
    # Remove invalid characters and limit length
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    return filename[:200]  # Limit length to 200 chars

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
            
        info = get_video_info(url)
        return JSONResponse(content=info)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download")
async def download_video(request: Request):
    try:
        data = await request.json()
        url = data.get('url')
        
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")

        # Create a temporary directory for downloading
        with tempfile.TemporaryDirectory() as temp_dir:
            ydl_opts = {
                'format': 'best',
                'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Download the video
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # Stream the file to the client
                return FileResponse(
                    filename,
                    media_type='application/octet-stream',
                    filename=sanitize_filename(os.path.basename(filename))
                )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
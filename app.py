from flask import Flask, request, jsonify, Response, send_file
import yt_dlp
import tempfile
import os
import re
from pathlib import Path

app = Flask(__name__)

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

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/get-info', methods=['POST'])
def fetch_video_info():
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
            
        info = get_video_info(url)
        return jsonify(info)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download_video():
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400

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
                return send_file(
                    filename,
                    as_attachment=True,
                    download_name=sanitize_filename(os.path.basename(filename))
                )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)

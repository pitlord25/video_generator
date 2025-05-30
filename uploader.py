import os, time, datetime

from PyQt5.QtCore import QThread, pyqtSignal
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


class UploadThread(QThread):
    """Thread for uploading videos to YouTube"""
    
    # Signals
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str, str)  # url, video_id
    error_signal = pyqtSignal(str)
    
    def __init__(self, 
                 credentials, 
                 video_path, 
                 title, 
                 description, 
                 category, 
                 tags, 
                 privacy_status, 
                 thumbnail_path=None, 
                 publish_at: datetime=None, 
                 made_for_kids=False):
        super().__init__()
        
        self.credentials = credentials
        self.video_path = video_path
        self.title = title
        self.description = description
        self.category = category
        self.tags = tags.split(",") if tags else []
        self.privacy_status = privacy_status
        self.thumbnail_path = thumbnail_path
        self.publish_at = publish_at
        self.made_for_kids = made_for_kids
        
        # Required for tracking upload progress
        self.progress = 0
        self.last_progress_time = 0
        self.running = True
        
    def run(self):
        """Upload the video to YouTube"""
        try:
            if not os.path.exists(self.video_path):
                self.error_signal.emit(f"Video file not found: {self.video_path}")
                return
                
            # Build the YouTube service
            youtube = build('youtube', 'v3', credentials=self.credentials)
            
            # Set up video metadata
            body = {
                'snippet': {
                    'title': self.title,
                    'description': self.description,
                    'tags': self.tags,
                    'categoryId': self.category
                },
                'status': {
                    'privacyStatus': self.privacy_status,
                    'selfDeclaredMadeForKids': self.made_for_kids
                }
            }
            
            # Add scheduled publishing if specified
            if self.publish_at and self.privacy_status == 'public':
                body['status']['publishAt'] = self.publish_at.isoformat()
                body['status']['privacyStatus'] = 'private'  # Set to private until publish time
                
            # Set up the media file upload
            media = MediaFileUpload(
                self.video_path,
                chunksize=1024*1024,  # 1MB chunks
                resumable=True
            )
            
            # Start the upload
            self.status_signal.emit("Starting upload...")
            insert_request = youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            # Monitor upload progress
            response = None
            while response is None and self.running:
                status, response = insert_request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    self.progress = progress
                    self.progress_signal.emit(progress)
                    self.status_signal.emit(f"Uploading: {progress}%")
                    
                    # Throttle progress updates
                    current_time = time.time()
                    if current_time - self.last_progress_time > 0.5:  # Update every 0.5 seconds max
                        self.last_progress_time = current_time
                        
            if not self.running:
                self.error_signal.emit("Upload cancelled")
                return
                
            # Get the video ID
            video_id = response['id']
            
            # Upload thumbnail if provided
            if self.thumbnail_path and os.path.exists(self.thumbnail_path):
                try:
                    self.status_signal.emit("Uploading thumbnail...")
                    youtube.thumbnails().set(
                        videoId=video_id,
                        media_body=MediaFileUpload(self.thumbnail_path)
                    ).execute()
                except HttpError as e:
                    self.status_signal.emit(f"Thumbnail upload failed: {str(e)}")
                    
            # Prepare video URL
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Signal completion
            self.progress_signal.emit(100)
            
            # Determine final status message
            if self.publish_at and self.privacy_status == 'public':
                status_msg = f"Video scheduled for {self.publish_at.strftime('%Y-%m-%d %H:%M')}"
            else:
                status_msg = f"Video {self.privacy_status} at {video_url}"
                
            self.status_signal.emit(status_msg)
            self.finished_signal.emit(video_url, video_id)
        
        except HttpError as e:
            error_content = e.content.decode('utf-8') if hasattr(e, 'content') else str(e)
            self.error_signal.emit(f"HTTP Error: {error_content}")
            
            # Log more detailed error information
            self.status_signal.emit(f"Error code: {e.resp.status}")
            if hasattr(e, 'reason'):
                self.status_signal.emit(f"Reason: {e.reason}")
                
            # Check specifically for permission issues
            if e.resp.status == 403:
                self.status_signal.emit("Permission denied. Make sure your account has access to this channel.")
            
        except Exception as e:
            self.error_signal.emit(f"Error: {str(e)}")
            
    def cancel(self):
        """Cancel the upload"""
        self.running = False
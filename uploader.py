from PyQt5.QtCore import QThread, pyqtSignal
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

# If modifying these scopes, delete your previously saved credentials
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'

class UploadThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str, str)  # URL and video ID
    error_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    
    def __init__(self, credentials, video_path, title, description, category, tags, privacy_status, 
                 thumbnail_path=None, publish_at=None, made_for_kids=False):
        super().__init__()
        self.credentials = credentials
        self.video_path = video_path
        self.title = title
        self.description = description
        self.category = category
        self.tags = tags.split(',') if tags else []
        self.privacy_status = privacy_status
        self.thumbnail_path = thumbnail_path
        self.publish_at = publish_at
        self.made_for_kids = made_for_kids
        
    def run(self):
        try:
            # Create YouTube service
            youtube = build('youtube', 'v3', credentials=self.credentials)
            
            # Define the video metadata
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
            
            # Add publish time if scheduled
            if self.publish_at and self.privacy_status == 'public':
                body['status']['publishAt'] = self.publish_at.isoformat()
                body['status']['privacyStatus'] = 'private'  # Set to private until publish time
            
            self.status_signal.emit("Starting video upload...")
            
            # Set up the media file
            media = MediaFileUpload(
                self.video_path,
                chunksize=1024*1024,
                resumable=True
            )
            
            # Create the insert request
            insert_request = youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            # Upload the video with progress tracking
            response = None
            while response is None:
                status, response = insert_request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    self.progress_signal.emit(progress)
            
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            self.status_signal.emit("Video uploaded successfully!")
            
            # Upload thumbnail if provided
            if self.thumbnail_path and os.path.exists(self.thumbnail_path):
                self.status_signal.emit("Uploading thumbnail...")
                try:
                    # Check if file size is within YouTube's limits (2MB)
                    file_size = os.path.getsize(self.thumbnail_path)
                    if file_size > 2 * 1024 * 1024:  # 2MB in bytes
                        self.status_signal.emit("Thumbnail too large (max 2MB), skipping...")
                    else:
                        youtube.thumbnails().set(
                            videoId=video_id,
                            media_body=MediaFileUpload(self.thumbnail_path)
                        ).execute()
                        self.status_signal.emit("Thumbnail uploaded successfully!")
                except Exception as e:
                    # Don't fail the entire upload for thumbnail issues
                    error_msg = str(e)
                    if "insufficient permission" in error_msg.lower():
                        self.status_signal.emit("Thumbnail upload requires additional permissions - video uploaded successfully without custom thumbnail")
                    else:
                        self.status_signal.emit(f"Thumbnail upload failed: {error_msg}")
            
            # If set to public immediately (not scheduled), try to verify it's actually public
            if self.privacy_status == 'public' and not self.publish_at:
                self.status_signal.emit("Verifying video is public...")
                try:
                    # Get video details to verify status
                    video_response = youtube.videos().list(
                        part='status',
                        id=video_id
                    ).execute()
                    
                    if video_response['items']:
                        actual_status = video_response['items'][0]['status']['privacyStatus']
                        if actual_status == 'public':
                            self.status_signal.emit("Video is now public and accessible!")
                        else:
                            self.status_signal.emit(f"Video uploaded but status is: {actual_status}")
                    else:
                        self.status_signal.emit("Video uploaded successfully!")
                except Exception as e:
                    # Don't fail for status check issues
                    error_msg = str(e)
                    if "insufficient permission" in error_msg.lower():
                        self.status_signal.emit("Video uploaded successfully! (Cannot verify status due to permissions)")
                    else:
                        self.status_signal.emit("Video uploaded successfully! (Status verification unavailable)")
            
            self.finished_signal.emit(video_url, video_id)
            
        except Exception as e:
            self.error_signal.emit(str(e))
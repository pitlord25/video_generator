from PyQt5.QtCore import QThread, pyqtSignal
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# If modifying these scopes, delete your previously saved credentials
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'

class UploadThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str, str, str)  # Updated to pass more info: message, video_id, video_url
    error_signal = pyqtSignal(str)
    
    def __init__(self, credentials, video_file, title, description, category, privacy_status):
        QThread.__init__(self)
        self.credentials = credentials
        self.video_file = video_file
        self.title = title
        self.description = description
        self.category = category
        self.privacy_status = privacy_status
        
    def run(self):
        try:
            youtube = build(API_SERVICE_NAME, API_VERSION, credentials=self.credentials)
            
            body = {
                'snippet': {
                    'title': self.title,
                    'description': self.description,
                    'categoryId': self.category
                },
                'status': {
                    'privacyStatus': self.privacy_status
                }
            }
            
            # Call the API's videos.insert method to create and upload the video
            media = MediaFileUpload(self.video_file, 
                                  chunksize=1024*1024, 
                                  resumable=True)
            
            request = youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    self.progress_signal.emit(progress)
            
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            self.finished_signal.emit(f"Upload complete!", video_id, video_url)
        
        except Exception as e:
            self.error_signal.emit(f"An error occurred: {str(e)}")

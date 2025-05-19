import sys
import os
import pickle
import json
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, 
                            QWidget, QFileDialog, QLabel, QLineEdit, QProgressBar, QMessageBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

class UploadThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    
    def __init__(self, credentials, video_path, title, description, category, tags, privacy_status):
        super().__init__()
        self.credentials = credentials
        self.video_path = video_path
        self.title = title
        self.description = description
        self.category = category
        self.tags = tags.split(',') if tags else []
        self.privacy_status = privacy_status
        
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
                    'privacyStatus': self.privacy_status
                }
            }
            
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
            
            # Get the video URL
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            self.finished_signal.emit(video_url)
            
        except Exception as e:
            self.error_signal.emit(str(e))


class YouTubeUploader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.credentials = None
        self.video_path = None
        self.upload_thread = None
        self.token_path = "token.pickle"
        self.client_secrets_path = None
        
        self.init_ui()
        
        # Try to load existing credentials
        self.load_credentials()
    
    def init_ui(self):
        self.setWindowTitle("YouTube Video Uploader")
        self.setMinimumSize(600, 500)
        
        # Create central widget and layout
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # OAuth2 credentials section
        oauth_layout = QHBoxLayout()
        self.oauth_status_label = QLabel("OAuth2 Status: Not Authenticated")
        self.load_oauth_button = QPushButton("Load OAuth2 Client File")
        self.load_oauth_button.clicked.connect(self.load_oauth_file)
        oauth_layout.addWidget(self.oauth_status_label)
        oauth_layout.addWidget(self.load_oauth_button)
        main_layout.addLayout(oauth_layout)
        
        # Video selection section
        video_layout = QHBoxLayout()
        self.video_path_label = QLabel("No video selected")
        self.select_video_button = QPushButton("Select Video")
        self.select_video_button.clicked.connect(self.select_video)
        video_layout.addWidget(self.video_path_label)
        video_layout.addWidget(self.select_video_button)
        main_layout.addLayout(video_layout)
        
        # Video details section
        main_layout.addWidget(QLabel("Video Title:"))
        self.title_input = QLineEdit()
        main_layout.addWidget(self.title_input)
        
        main_layout.addWidget(QLabel("Video Description:"))
        self.description_input = QLineEdit()
        main_layout.addWidget(self.description_input)
        
        main_layout.addWidget(QLabel("Category ID:"))
        self.category_input = QLineEdit("22")  # Default: People & Blogs
        main_layout.addWidget(self.category_input)
        
        main_layout.addWidget(QLabel("Tags (comma separated):"))
        self.tags_input = QLineEdit()
        main_layout.addWidget(self.tags_input)
        
        main_layout.addWidget(QLabel("Privacy Status:"))
        privacy_layout = QHBoxLayout()
        self.privacy_public = QPushButton("Public")
        self.privacy_unlisted = QPushButton("Unlisted")
        self.privacy_private = QPushButton("Private")
        
        self.privacy_public.setCheckable(True)
        self.privacy_unlisted.setCheckable(True)
        self.privacy_private.setCheckable(True)
        
        self.privacy_unlisted.setChecked(True)
        self.current_privacy = "unlisted"
        
        self.privacy_public.clicked.connect(lambda: self.set_privacy("public"))
        self.privacy_unlisted.clicked.connect(lambda: self.set_privacy("unlisted"))
        self.privacy_private.clicked.connect(lambda: self.set_privacy("private"))
        
        privacy_layout.addWidget(self.privacy_public)
        privacy_layout.addWidget(self.privacy_unlisted)
        privacy_layout.addWidget(self.privacy_private)
        main_layout.addLayout(privacy_layout)
        
        # Progress section
        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Status: Ready")
        main_layout.addWidget(self.status_label)
        
        self.result_url = QLineEdit()
        self.result_url.setReadOnly(True)
        self.result_url.setPlaceholderText("Video URL will appear here after upload")
        main_layout.addWidget(self.result_url)
        
        # Upload button
        self.upload_button = QPushButton("Upload to YouTube")
        self.upload_button.clicked.connect(self.start_upload)
        self.upload_button.setEnabled(False)
        main_layout.addWidget(self.upload_button)
        
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
    
    def set_privacy(self, status):
        self.current_privacy = status
        
        self.privacy_public.setChecked(status == "public")
        self.privacy_unlisted.setChecked(status == "unlisted")
        self.privacy_private.setChecked(status == "private")
    
    def load_oauth_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select OAuth2 Client Secret File", "", "JSON Files (*.json)")
        
        if file_path:
            self.client_secrets_path = file_path
            try:
                with open(file_path, 'r') as f:
                    json.load(f)  # Validate the JSON format
                
                self.get_credentials()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Invalid OAuth2 client file: {str(e)}")
    
    def get_credentials(self):
        # Check if we already have a valid token
        if os.path.exists(self.token_path):
            with open(self.token_path, 'rb') as token:
                self.credentials = pickle.load(token)
        
        # If credentials don't exist or are invalid, get new ones
        if not self.credentials or not self.credentials.valid:
            if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                try:
                    self.credentials.refresh(Request())
                except Exception as e:
                    QMessageBox.warning(self, "Token Error", f"Could not refresh token: {str(e)}")
                    self.credentials = None
            
            # If still no valid credentials, we need to authenticate
            if not self.credentials:
                if not self.client_secrets_path:
                    QMessageBox.critical(self, "Error", "Please load an OAuth2 client file first.")
                    return
                
                flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_path, 
                    scopes=['https://www.googleapis.com/auth/youtube.upload']
                )
                
                # Open browser for authentication
                self.credentials = flow.run_local_server(port=8080)
                
                # Save the credentials for the next run
                with open(self.token_path, 'wb') as token:
                    pickle.dump(self.credentials, token)
        
        self.oauth_status_label.setText("OAuth2 Status: Authenticated")
        self.update_upload_button_state()
    
    def load_credentials(self):
        # Try to load existing credentials from pickle file
        if os.path.exists(self.token_path):
            try:
                with open(self.token_path, 'rb') as token:
                    self.credentials = pickle.load(token)
                
                if self.credentials and self.credentials.valid:
                    self.oauth_status_label.setText("OAuth2 Status: Authenticated")
                elif self.credentials and self.credentials.refresh_token:
                    try:
                        self.credentials.refresh(Request())
                        self.oauth_status_label.setText("OAuth2 Status: Authenticated")
                    except:
                        self.oauth_status_label.setText("OAuth2 Status: Token expired, needs refresh")
            except Exception as e:
                self.oauth_status_label.setText(f"OAuth2 Status: Error loading token")
    
    def select_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.flv *.mov *.avi *.wmv *.mkv)")
        
        if file_path:
            self.video_path = file_path
            file_name = os.path.basename(file_path)
            self.video_path_label.setText(f"Selected: {file_name}")
            
            # Auto-fill title from filename without extension
            title = os.path.splitext(file_name)[0]
            self.title_input.setText(title)
            
            self.update_upload_button_state()
    
    def update_upload_button_state(self):
        is_ready = (self.credentials is not None and 
                   self.credentials.valid and 
                   self.video_path is not None)
        
        self.upload_button.setEnabled(is_ready)
    
    def start_upload(self):
        if not self.video_path:
            QMessageBox.warning(self, "Warning", "Please select a video file first.")
            return
        
        if not self.credentials or not self.credentials.valid:
            QMessageBox.warning(self, "Warning", "Please authenticate with YouTube first.")
            return
        
        # Get video details from input fields
        title = self.title_input.text()
        description = self.description_input.text()
        category = self.category_input.text()
        tags = self.tags_input.text()
        privacy_status = self.current_privacy
        
        if not title:
            QMessageBox.warning(self, "Warning", "Please enter a title for the video.")
            return
        
        # Disable UI elements during upload
        self.upload_button.setEnabled(False)
        self.select_video_button.setEnabled(False)
        self.load_oauth_button.setEnabled(False)
        
        # Reset progress bar
        self.progress_bar.setValue(0)
        self.status_label.setText("Status: Uploading...")
        
        # Create and start upload thread
        self.upload_thread = UploadThread(
            self.credentials, self.video_path, title, description, 
            category, tags, privacy_status
        )
        
        # Connect signals
        self.upload_thread.progress_signal.connect(self.update_progress)
        self.upload_thread.finished_signal.connect(self.upload_finished)
        self.upload_thread.error_signal.connect(self.upload_error)
        
        # Start the thread
        self.upload_thread.start()
    
    def update_progress(self, progress):
        self.progress_bar.setValue(progress)
    
    def upload_finished(self, url):
        # Re-enable UI elements
        self.upload_button.setEnabled(True)
        self.select_video_button.setEnabled(True)
        self.load_oauth_button.setEnabled(True)
        
        # Update status
        self.status_label.setText("Status: Upload Complete!")
        self.progress_bar.setValue(100)
        
        # Show URL
        self.result_url.setText(url)
        
        # Show success message
        QMessageBox.information(self, "Success", f"Video uploaded successfully!\nURL: {url}")
    
    def upload_error(self, error_msg):
        # Re-enable UI elements
        self.upload_button.setEnabled(True)
        self.select_video_button.setEnabled(True)
        self.load_oauth_button.setEnabled(True)
        
        # Update status
        self.status_label.setText(f"Status: Error: {error_msg}")
        
        # Show error message
        QMessageBox.critical(self, "Upload Error", f"Failed to upload video: {error_msg}")


def main():
    # Prevent opening browser automatically for OAuth
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    
    app = QApplication(sys.argv)
    window = YouTubeUploader()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
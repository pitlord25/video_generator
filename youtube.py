import sys
import os
import pickle
import json
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, 
                            QWidget, QFileDialog, QLabel, QLineEdit, QProgressBar, QMessageBox,
                            QDateTimeEdit, QCheckBox, QTextEdit, QGroupBox, QFormLayout)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDateTime
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

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


class YouTubeUploader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.credentials = None
        self.video_path = None
        self.thumbnail_path = None
        self.upload_thread = None
        self.token_path = "token.pickle"
        self.client_secrets_path = None
        
        self.init_ui()
        
        # Try to load existing credentials
        self.load_credentials()
    
    def init_ui(self):
        self.setWindowTitle("YouTube Video Uploader & Publisher")
        self.setMinimumSize(700, 700)
        
        # Create central widget and layout
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # OAuth2 credentials section
        oauth_group = QGroupBox("Authentication")
        oauth_layout = QHBoxLayout()
        self.oauth_status_label = QLabel("OAuth2 Status: Not Authenticated")
        self.load_oauth_button = QPushButton("Load OAuth2 Client File")
        self.load_oauth_button.clicked.connect(self.load_oauth_file)
        oauth_layout.addWidget(self.oauth_status_label)
        oauth_layout.addWidget(self.load_oauth_button)
        oauth_group.setLayout(oauth_layout)
        main_layout.addWidget(oauth_group)
        
        # File selection section
        files_group = QGroupBox("File Selection")
        files_layout = QVBoxLayout()
        
        # Video selection
        video_layout = QHBoxLayout()
        self.video_path_label = QLabel("No video selected")
        self.select_video_button = QPushButton("Select Video")
        self.select_video_button.clicked.connect(self.select_video)
        video_layout.addWidget(self.video_path_label)
        video_layout.addWidget(self.select_video_button)
        files_layout.addLayout(video_layout)
        
        # Thumbnail selection
        thumbnail_layout = QHBoxLayout()
        self.thumbnail_path_label = QLabel("No thumbnail selected (optional)")
        self.select_thumbnail_button = QPushButton("Select Thumbnail")
        self.select_thumbnail_button.clicked.connect(self.select_thumbnail)
        thumbnail_layout.addWidget(self.thumbnail_path_label)
        thumbnail_layout.addWidget(self.select_thumbnail_button)
        files_layout.addLayout(thumbnail_layout)
        
        files_group.setLayout(files_layout)
        main_layout.addWidget(files_group)
        
        # Video details section
        details_group = QGroupBox("Video Details")
        details_layout = QFormLayout()
        
        self.title_input = QLineEdit()
        details_layout.addRow("Title:", self.title_input)
        
        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(100)
        details_layout.addRow("Description:", self.description_input)
        
        self.category_input = QLineEdit("22")  # Default: People & Blogs
        details_layout.addRow("Category ID:", self.category_input)
        
        self.tags_input = QLineEdit()
        details_layout.addRow("Tags (comma separated):", self.tags_input)
        
        self.made_for_kids_checkbox = QCheckBox("Made for kids")
        details_layout.addRow("Content:", self.made_for_kids_checkbox)
        
        details_group.setLayout(details_layout)
        main_layout.addWidget(details_group)
        
        # Publishing options section
        publish_group = QGroupBox("Publishing Options")
        publish_layout = QVBoxLayout()
        
        # Privacy status
        privacy_label = QLabel("Privacy Status:")
        publish_layout.addWidget(privacy_label)
        
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
        publish_layout.addLayout(privacy_layout)
        
        # Scheduling
        schedule_layout = QHBoxLayout()
        self.schedule_checkbox = QCheckBox("Schedule publication")
        self.schedule_checkbox.stateChanged.connect(self.toggle_schedule)
        schedule_layout.addWidget(self.schedule_checkbox)
        
        self.schedule_datetime = QDateTimeEdit()
        self.schedule_datetime.setDateTime(QDateTime.currentDateTime().addSecs(3600))  # 1 hour from now
        self.schedule_datetime.setEnabled(False)
        schedule_layout.addWidget(self.schedule_datetime)
        
        publish_layout.addLayout(schedule_layout)
        
        publish_group.setLayout(publish_layout)
        main_layout.addWidget(publish_group)
        
        # Progress section
        progress_group = QGroupBox("Upload Progress")
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel("Status: Ready")
        progress_layout.addWidget(self.status_label)
        
        self.result_url = QLineEdit()
        self.result_url.setReadOnly(True)
        self.result_url.setPlaceholderText("Video URL will appear here after upload")
        progress_layout.addWidget(self.result_url)
        
        progress_group.setLayout(progress_layout)
        main_layout.addWidget(progress_group)
        
        # Upload button
        self.upload_button = QPushButton("Upload & Publish to YouTube")
        self.upload_button.clicked.connect(self.start_upload)
        self.upload_button.setEnabled(False)
        self.upload_button.setStyleSheet("QPushButton { font-size: 14px; padding: 10px; }")
        main_layout.addWidget(self.upload_button)
        
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
    
    def toggle_schedule(self, state):
        self.schedule_datetime.setEnabled(state == Qt.Checked)
        if state == Qt.Checked:
            # Force public when scheduling
            self.set_privacy("public")
            self.privacy_public.setEnabled(False)
            self.privacy_unlisted.setEnabled(False)
            self.privacy_private.setEnabled(False)
        else:
            self.privacy_public.setEnabled(True)
            self.privacy_unlisted.setEnabled(True)
            self.privacy_private.setEnabled(True)
    
    def set_privacy(self, status):
        self.current_privacy = status
        
        self.privacy_public.setChecked(status == "public")
        self.privacy_unlisted.setChecked(status == "unlisted")
        self.privacy_private.setChecked(status == "private")
        
        # Update button text based on privacy
        if status == "public":
            self.upload_button.setText("Upload & Publish Publicly to YouTube")
        elif status == "unlisted":
            self.upload_button.setText("Upload as Unlisted to YouTube")
        else:
            self.upload_button.setText("Upload as Private to YouTube")
    
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
                
                # Updated scopes for full YouTube access
                scopes = [
                    'https://www.googleapis.com/auth/youtube.upload',
                    'https://www.googleapis.com/auth/youtube.readonly'
                ]
                
                flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_path, scopes=scopes
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
    
    def select_thumbnail(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Thumbnail Image", "", "Image Files (*.jpg *.jpeg *.png *.gif *.bmp)")
        
        if file_path:
            self.thumbnail_path = file_path
            file_name = os.path.basename(file_path)
            self.thumbnail_path_label.setText(f"Selected: {file_name}")
    
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
        description = self.description_input.toPlainText()
        category = self.category_input.text()
        tags = self.tags_input.text()
        privacy_status = self.current_privacy
        made_for_kids = self.made_for_kids_checkbox.isChecked()
        
        if not title:
            QMessageBox.warning(self, "Warning", "Please enter a title for the video.")
            return
        
        # Handle scheduling
        publish_at = None
        if self.schedule_checkbox.isChecked():
            publish_at = self.schedule_datetime.dateTime().toPyDateTime()
            if publish_at <= datetime.now():
                QMessageBox.warning(self, "Warning", "Please select a future date and time for scheduling.")
                return
        
        # Confirm publication for public videos
        if privacy_status == "public" and not self.schedule_checkbox.isChecked():
            reply = QMessageBox.question(
                self, "Confirm Publication", 
                "Are you sure you want to publish this video publicly? It will be immediately visible to everyone on YouTube.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        # Disable UI elements during upload
        self.upload_button.setEnabled(False)
        self.select_video_button.setEnabled(False)
        self.select_thumbnail_button.setEnabled(False)
        self.load_oauth_button.setEnabled(False)
        
        # Reset progress bar
        self.progress_bar.setValue(0)
        self.status_label.setText("Status: Preparing upload...")
        
        # Create and start upload thread
        self.upload_thread = UploadThread(
            self.credentials, self.video_path, title, description, 
            category, tags, privacy_status, self.thumbnail_path, 
            publish_at, made_for_kids
        )
        
        # Connect signals
        self.upload_thread.progress_signal.connect(self.update_progress)
        self.upload_thread.finished_signal.connect(self.upload_finished)
        self.upload_thread.error_signal.connect(self.upload_error)
        self.upload_thread.status_signal.connect(self.update_status)
        
        # Start the thread
        self.upload_thread.start()
    
    def update_progress(self, progress):
        self.progress_bar.setValue(progress)
    
    def update_status(self, status):
        self.status_label.setText(f"Status: {status}")
    
    def upload_finished(self, url, video_id):
        # Re-enable UI elements
        self.upload_button.setEnabled(True)
        self.select_video_button.setEnabled(True)
        self.select_thumbnail_button.setEnabled(True)
        self.load_oauth_button.setEnabled(True)
        
        # Update status
        self.progress_bar.setValue(100)
        
        # Show URL
        self.result_url.setText(url)
        
        # Show success message with different text based on privacy status
        if self.current_privacy == "public":
            if self.schedule_checkbox.isChecked():
                success_msg = f"Video uploaded and scheduled for publication!\nURL: {url}\nVideo ID: {video_id}"
            else:
                success_msg = f"Video uploaded and published publicly!\nURL: {url}\nVideo ID: {video_id}\n\nYour video is now live and can be viewed by anyone!"
        else:
            success_msg = f"Video uploaded successfully as {self.current_privacy}!\nURL: {url}\nVideo ID: {video_id}"
        
        QMessageBox.information(self, "Success", success_msg)
    
    def upload_error(self, error_msg):
        # Re-enable UI elements
        self.upload_button.setEnabled(True)
        self.select_video_button.setEnabled(True)
        self.select_thumbnail_button.setEnabled(True)
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
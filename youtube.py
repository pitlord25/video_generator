import sys
import os
import json
import pickle
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                            QHBoxLayout, QFileDialog, QLabel, QWidget, QLineEdit,
                            QTextEdit, QProgressBar, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QClipboard
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request

# If modifying these scopes, delete your previously saved credentials
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
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


class YouTubeUploaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.credentials = None
        self.client_secrets_file = None
        self.credentials_file = None  # Path to store the pickled credentials
        self.video_url = None
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('YouTube Video Uploader')
        self.setGeometry(100, 100, 600, 450)
        
        # Create central widget and layout
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # Create OAuth2 credentials section
        client_secrets_layout = QHBoxLayout()
        self.client_secrets_label = QLabel('Client Secrets File:')
        self.client_secrets_path = QLineEdit()
        self.client_secrets_path.setReadOnly(True)
        self.load_client_secrets_btn = QPushButton('Load Client Secrets')
        
        client_secrets_layout.addWidget(self.client_secrets_label)
        client_secrets_layout.addWidget(self.client_secrets_path)
        client_secrets_layout.addWidget(self.load_client_secrets_btn)
        
        # Create Video file selection section
        video_layout = QHBoxLayout()
        self.video_label = QLabel('Video File:')
        self.video_path = QLineEdit()
        self.video_path.setReadOnly(True)
        self.browse_video_btn = QPushButton('Browse')
        
        video_layout.addWidget(self.video_label)
        video_layout.addWidget(self.video_path)
        video_layout.addWidget(self.browse_video_btn)
        
        # Create video details section
        self.title_label = QLabel('Title:')
        self.title_input = QLineEdit()
        
        self.description_label = QLabel('Description:')
        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(100)
        
        # Category and privacy
        category_privacy_layout = QHBoxLayout()
        self.category_label = QLabel('Category ID:')
        self.category_input = QLineEdit('22')  # Default to 'People & Blogs'
        
        self.privacy_label = QLabel('Privacy Status:')
        self.privacy_input = QLineEdit('private')  # Default to private
        
        category_privacy_layout.addWidget(self.category_label)
        category_privacy_layout.addWidget(self.category_input)
        category_privacy_layout.addWidget(self.privacy_label)
        category_privacy_layout.addWidget(self.privacy_input)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        
        # Upload button
        self.upload_btn = QPushButton('Upload to YouTube')
        self.upload_btn.setEnabled(False)
        
        # Video URL section
        url_layout = QHBoxLayout()
        self.url_label = QLabel('Video URL:')
        self.url_text = QLineEdit()
        self.url_text.setReadOnly(True)
        self.copy_url_btn = QPushButton('Copy URL')
        self.copy_url_btn.setEnabled(False)
        self.open_url_btn = QPushButton('Open in Browser')
        self.open_url_btn.setEnabled(False)
        
        url_layout.addWidget(self.url_label)
        url_layout.addWidget(self.url_text)
        url_layout.addWidget(self.copy_url_btn)
        url_layout.addWidget(self.open_url_btn)
        
        # Status bar for messages
        self.status_label = QLabel('Ready')
        
        # Add all widgets to main layout
        main_layout.addLayout(client_secrets_layout)
        main_layout.addLayout(video_layout)
        main_layout.addWidget(self.title_label)
        main_layout.addWidget(self.title_input)
        main_layout.addWidget(self.description_label)
        main_layout.addWidget(self.description_input)
        main_layout.addLayout(category_privacy_layout)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.upload_btn)
        main_layout.addLayout(url_layout)
        main_layout.addWidget(self.status_label)
        
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        # Connect signals and slots
        self.load_client_secrets_btn.clicked.connect(self.load_oauth)
        self.browse_video_btn.clicked.connect(self.browse_video)
        self.upload_btn.clicked.connect(self.upload_video)
        self.copy_url_btn.clicked.connect(self.copy_url_to_clipboard)
        self.open_url_btn.clicked.connect(self.open_url_in_browser)
        
    def load_oauth(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 'Load OAuth2 Client Secrets', '', 'JSON Files (*.json)'
        )
        
        if file_path:
            self.client_secrets_file = file_path
            self.oauth_path.setText(file_path)
            
            # Check if there are saved credentials
            token_path = os.path.join(os.path.dirname(file_path), 'token.pickle')
            
            if os.path.exists(token_path):
                with open(token_path, 'rb') as token:
                    self.credentials = pickle.load(token)
                
                # Check if credentials are valid or need refreshing
                if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                    self.credentials.refresh(Request())
                    with open(token_path, 'wb') as token:
                        pickle.dump(self.credentials, token)
                    
                    self.status_label.setText('Credentials loaded and refreshed')
                else:
                    self.status_label.setText('Credentials loaded successfully')
                
                self.update_upload_button_state()
                return
            
            # If no saved credentials, get new ones
            self.get_credentials()
    
    def save_oauth(self):
        if not self.credentials:
            QMessageBox.warning(self, 'Warning', 'No credentials to save')
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, 'Save OAuth2 Credentials', '', 'Pickle Files (*.pickle)'
        )
        
        if file_path:
            with open(file_path, 'wb') as token:
                pickle.dump(self.credentials, token)
            self.status_label.setText(f'Credentials saved to {file_path}')
    
    def get_credentials(self):
        if not self.client_secrets_file:
            QMessageBox.warning(self, 'Warning', 'Please load OAuth2 client secrets file first')
            return
            
        try:
            flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                self.client_secrets_file, SCOPES)
            self.credentials = flow.run_local_server(port=8080)
            
            # Save the credentials for the next run
            token_path = os.path.join(os.path.dirname(self.client_secrets_file), 'token.pickle')
            with open(token_path, 'wb') as token:
                pickle.dump(self.credentials, token)
                
            self.status_label.setText('Authentication successful')
            self.update_upload_button_state()
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Authentication failed: {str(e)}')
    
    def browse_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 'Select Video File', '', 'Video Files (*.mp4 *.avi *.mov *.mkv *.flv *.wmv)'
        )
        
        if file_path:
            self.video_path.setText(file_path)
            self.update_upload_button_state()
    
    def upload_video(self):
        if not self.credentials:
            QMessageBox.warning(self, 'Warning', 'Please authenticate with YouTube first')
            return
            
        video_file = self.video_path.text()
        title = self.title_input.text()
        description = self.description_input.toPlainText()
        category = self.category_input.text()
        privacy_status = self.privacy_input.text()
        
        if not video_file or not title:
            QMessageBox.warning(self, 'Warning', 'Please provide a video file and title')
            return
        
        # Create and start upload thread
        self.upload_thread = UploadThread(
            self.credentials, video_file, title, description, category, privacy_status
        )
        
        self.upload_thread.progress_signal.connect(self.update_progress)
        self.upload_thread.finished_signal.connect(self.upload_finished)
        self.upload_thread.error_signal.connect(self.upload_error)
        
        self.upload_btn.setEnabled(False)
        self.copy_url_btn.setEnabled(False)
        self.open_url_btn.setEnabled(False)
        self.url_text.clear()
        self.status_label.setText('Uploading...')
        self.upload_thread.start()
    
    def update_progress(self, value):
        self.progress_bar.setValue(value)
    
    def upload_finished(self, message, video_id, video_url):
        self.progress_bar.setValue(100)
        self.status_label.setText(f"{message} Video ID: {video_id}")
        self.upload_btn.setEnabled(True)
        
        # Update and enable URL section
        self.video_url = video_url
        self.url_text.setText(video_url)
        self.copy_url_btn.setEnabled(True)
        self.open_url_btn.setEnabled(True)
        
        QMessageBox.information(self, 'Success', f"{message}\nVideo URL: {video_url}")
    
    def upload_error(self, error_message):
        self.status_label.setText(error_message)
        self.upload_btn.setEnabled(True)
        QMessageBox.critical(self, 'Error', error_message)
    
    def update_upload_button_state(self):
        self.upload_btn.setEnabled(
            bool(self.credentials) and bool(self.video_path.text())
        )
        
    def copy_url_to_clipboard(self):
        if self.video_url:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.video_url)
            self.status_label.setText('URL copied to clipboard')
            
    def open_url_in_browser(self):
        if self.video_url:
            import webbrowser
            webbrowser.open(self.video_url)
            self.status_label.setText('Opening video in browser')


def main():
    app = QApplication(sys.argv)
    
    # To prevent "OAuth 2.0 verification required" message when using OAuth 2.0 for installed apps
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    window = YouTubeUploaderApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
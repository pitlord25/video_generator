import sys
import os
import json
import http.server
import socketserver
import webbrowser
from threading import Thread
import pickle
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, 
                           QLabel, QFileDialog, QWidget, QProgressBar, QComboBox, QLineEdit, 
                           QTextEdit, QGroupBox, QMessageBox)
from PyQt5.QtCore import Qt, QObject, pyqtSignal, pyqtSlot

import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

class OAuth2Server:
    def __init__(self, success_callback):
        self.success_callback = success_callback
        self.auth_code = None
        
    def start_server(self):
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self_handler, *args, **kwargs):
                super().__init__(self_handler, *args, **kwargs)
            
            def do_GET(self_handler):
                self.auth_code = self_handler.path.split("code=")[1].split("&")[0]
                self_handler.send_response(200)
                self_handler.send_header('Content-type', 'text/html')
                self_handler.end_headers()
                self_handler.wfile.write(b"<html><body><h1>Authentication Successful!</h1><p>You can close this window now.</p></body></html>")
                self.success_callback(self.auth_code)
                
        with socketserver.TCPServer(("", 8080), Handler) as httpd:
            httpd.handle_request()

class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    message = pyqtSignal(str)

class YouTubeUploader(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.credentials = None
        self.client_secrets_file = None
        self.youtube = None
        self.channels = []
        self.selected_channel = None
        self.video_file = None
        
        self.signals = WorkerSignals()
        self.signals.finished.connect(self.on_upload_finished)
        self.signals.error.connect(self.show_error)
        self.signals.progress.connect(self.update_progress)
        self.signals.message.connect(self.show_message)
        
        self.init_ui()
        
        # Attempt to load saved credentials
        self.load_saved_credentials()
        
    def init_ui(self):
        self.setWindowTitle("YouTube Video Uploader")
        self.setMinimumSize(600, 500)
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        
        # Auth section
        auth_group = QGroupBox("Authentication")
        auth_layout = QVBoxLayout()
        auth_group.setLayout(auth_layout)
        
        # Client secrets file selection
        client_secrets_layout = QHBoxLayout()
        self.client_secrets_label = QLabel("Client Secrets File:")
        self.client_secrets_path = QLineEdit()
        self.client_secrets_path.setReadOnly(True)
        self.select_client_secrets_btn = QPushButton("Select OAuth2 JSON")
        self.select_client_secrets_btn.clicked.connect(self.select_client_secrets)
        
        client_secrets_layout.addWidget(self.client_secrets_label)
        client_secrets_layout.addWidget(self.client_secrets_path)
        client_secrets_layout.addWidget(self.select_client_secrets_btn)
        
        # Status and auth button
        status_layout = QHBoxLayout()
        self.auth_status_label = QLabel("Status: Not authenticated")
        self.auth_btn = QPushButton("Authenticate")
        self.auth_btn.clicked.connect(self.authenticate)
        self.auth_btn.setEnabled(False)
        
        status_layout.addWidget(self.auth_status_label)
        status_layout.addWidget(self.auth_btn)
        
        auth_layout.addLayout(client_secrets_layout)
        auth_layout.addLayout(status_layout)
        
        main_layout.addWidget(auth_group)
        
        # Channel selection
        channel_group = QGroupBox("YouTube Channel")
        channel_layout = QVBoxLayout()
        channel_group.setLayout(channel_layout)
        
        self.channel_combo = QComboBox()
        self.channel_combo.setEnabled(False)
        self.channel_combo.currentIndexChanged.connect(self.on_channel_selected)
        self.refresh_channels_btn = QPushButton("Refresh Channels")
        self.refresh_channels_btn.clicked.connect(self.list_channels)
        self.refresh_channels_btn.setEnabled(False)
        
        channel_layout.addWidget(QLabel("Select Channel:"))
        channel_layout.addWidget(self.channel_combo)
        channel_layout.addWidget(self.refresh_channels_btn)
        
        main_layout.addWidget(channel_group)
        
        # Video upload section
        upload_group = QGroupBox("Video Upload")
        upload_layout = QVBoxLayout()
        upload_group.setLayout(upload_layout)
        
        # Video file selection
        video_file_layout = QHBoxLayout()
        self.video_path = QLineEdit()
        self.video_path.setReadOnly(True)
        self.select_video_btn = QPushButton("Select Video")
        self.select_video_btn.clicked.connect(self.select_video)
        
        video_file_layout.addWidget(QLabel("Video File:"))
        video_file_layout.addWidget(self.video_path)
        video_file_layout.addWidget(self.select_video_btn)
        
        # Video details
        self.title_input = QLineEdit()
        self.description_input = QTextEdit()
        
        # Upload button and progress
        upload_action_layout = QHBoxLayout()
        self.upload_btn = QPushButton("Upload Video")
        self.upload_btn.clicked.connect(self.upload_video)
        self.upload_btn.setEnabled(False)
        self.progress_bar = QProgressBar()
        
        upload_action_layout.addWidget(self.upload_btn)
        upload_action_layout.addWidget(self.progress_bar)
        
        # Results area
        self.result_label = QLabel("Video URL will appear here after upload")
        
        upload_layout.addLayout(video_file_layout)
        upload_layout.addWidget(QLabel("Video Title:"))
        upload_layout.addWidget(self.title_input)
        upload_layout.addWidget(QLabel("Video Description:"))
        upload_layout.addWidget(self.description_input)
        upload_layout.addLayout(upload_action_layout)
        upload_layout.addWidget(self.result_label)
        
        main_layout.addWidget(upload_group)
        
    def select_client_secrets(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select OAuth2 Client Secrets File", "", "JSON Files (*.json)"
        )
        if file_path:
            self.client_secrets_file = file_path
            self.client_secrets_path.setText(file_path)
            self.auth_btn.setEnabled(True)
    
    def authenticate(self):
        try:
            # Check if we have saved credentials
            if self.credentials:
                self.init_youtube_api()
                return
                
            # Set up the OAuth2 flow
            flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                self.client_secrets_file,
                scopes=["https://www.googleapis.com/auth/youtube.upload", 
                        "https://www.googleapis.com/auth/youtube.readonly"]
            )
            
            # Start the server to receive the auth code
            def auth_success(auth_code):
                flow.fetch_token(code=auth_code)
                self.credentials = flow.credentials
                self.save_credentials()
                self.init_youtube_api()
            
            # Open browser for authentication
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true'
            )
            
            webbrowser.open(auth_url)
            
            # Start server to receive redirect
            server = OAuth2Server(auth_success)
            Thread(target=server.start_server).start()
            
            self.show_message("Browser opened for authentication. Please complete the login process.")
            
        except Exception as e:
            self.show_error(f"Authentication error: {str(e)}")
    
    def init_youtube_api(self):
        try:
            self.youtube = build("youtube", "v3", credentials=self.credentials)
            self.auth_status_label.setText("Status: Authenticated")
            self.refresh_channels_btn.setEnabled(True)
            self.list_channels()
        except Exception as e:
            self.show_error(f"Error initializing YouTube API: {str(e)}")
    
    def list_channels(self):
        try:
            if not self.youtube:
                self.show_error("Not authenticated. Please authenticate first.")
                return
                
            self.channels = []
            self.channel_combo.clear()
            
            response = self.youtube.channels().list(
                part="snippet",
                mine=True
            ).execute()
            
            for channel in response.get("items", []):
                channel_id = channel["id"]
                channel_title = channel["snippet"]["title"]
                self.channels.append({"id": channel_id, "title": channel_title})
                self.channel_combo.addItem(channel_title)
            
            if self.channels:
                self.channel_combo.setEnabled(True)
                self.on_channel_selected(0)
            else:
                self.show_message("No channels found for this account.")
                
        except Exception as e:
            self.show_error(f"Error listing channels: {str(e)}")
    
    def on_channel_selected(self, index):
        if index >= 0 and index < len(self.channels):
            self.selected_channel = self.channels[index]
            self.upload_btn.setEnabled(self.video_file is not None)
    
    def select_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mov *.avi *.wmv)"
        )
        if file_path:
            self.video_file = file_path
            self.video_path.setText(file_path)
            # Auto-populate title with filename
            file_name = os.path.basename(file_path)
            name_without_ext = os.path.splitext(file_name)[0]
            self.title_input.setText(name_without_ext)
            
            # Enable upload if channel is selected
            self.upload_btn.setEnabled(self.selected_channel is not None)
    
    def upload_video(self):
        if not self.youtube or not self.selected_channel:
            self.show_error("Not authenticated or no channel selected.")
            return
            
        if not self.video_file:
            self.show_error("Please select a video file first.")
            return
            
        title = self.title_input.text()
        if not title:
            self.show_error("Please enter a title for the video.")
            return
            
        description = self.description_input.toPlainText()
        
        # Start upload in a separate thread
        Thread(target=self._do_upload, args=(title, description)).start()
        
        self.progress_bar.setValue(0)
        self.upload_btn.setEnabled(False)
        self.signals.message.emit("Upload started...")
    
    def _do_upload(self, title, description):
        try:
            # Create a media file upload object
            media = MediaFileUpload(
                self.video_file,
                chunksize=1024*1024,
                resumable=True
            )
            
            # Define video resource
            body = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'categoryId': '22'  # People & Blogs category
                },
                'status': {
                    'privacyStatus': 'private'  # Set to private by default
                }
            }
            
            # Create upload request
            request = self.youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            # Upload video
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    self.signals.progress.emit(progress)
            
            # Get the video URL
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            self.signals.finished.emit(video_url)
            
        except HttpError as e:
            self.signals.error.emit(f"An HTTP error occurred: {e.resp.status} {e.content}")
        except Exception as e:
            self.signals.error.emit(f"An error occurred: {str(e)}")
    
    @pyqtSlot(object)
    def on_upload_finished(self, video_url):
        self.result_label.setText(f"Upload successful! URL: {video_url}")
        self.upload_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        
        # Show a clickable link
        msg_box = QMessageBox()
        msg_box.setWindowTitle("Upload Complete")
        msg_box.setText(f"Video successfully uploaded!\n\nURL: {video_url}")
        msg_box.exec_()
    
    @pyqtSlot(str)
    def show_error(self, error_msg):
        QMessageBox.critical(self, "Error", error_msg)
        self.upload_btn.setEnabled(True)
    
    @pyqtSlot(int)
    def update_progress(self, progress):
        self.progress_bar.setValue(progress)
    
    @pyqtSlot(str)
    def show_message(self, message):
        self.result_label.setText(message)
    
    def save_credentials(self):
        if self.credentials:
            # Convert credentials to dict
            creds_dict = {
                'token': self.credentials.token,
                'refresh_token': self.credentials.refresh_token,
                'token_uri': self.credentials.token_uri,
                'client_id': self.credentials.client_id,
                'client_secret': self.credentials.client_secret,
                'scopes': self.credentials.scopes
            }
            
            # Save to file
            with open('youtube_credentials.pickle', 'wb') as f:
                pickle.dump(creds_dict, f)
    
    def load_saved_credentials(self):
        try:
            if os.path.exists('youtube_credentials.pickle'):
                with open('youtube_credentials.pickle', 'rb') as f:
                    creds_dict = pickle.load(f)
                
                self.credentials = google.oauth2.credentials.Credentials(
                    token=creds_dict['token'],
                    refresh_token=creds_dict['refresh_token'],
                    token_uri=creds_dict['token_uri'],
                    client_id=creds_dict['client_id'],
                    client_secret=creds_dict['client_secret'],
                    scopes=creds_dict['scopes']
                )
                
                self.auth_status_label.setText("Status: Credentials loaded")
                
                # Try to initialize the API with loaded credentials
                try:
                    self.init_youtube_api()
                except:
                    # If the credentials are expired, we'll need to re-authenticate
                    self.credentials = None
                    self.auth_status_label.setText("Status: Credentials expired, please re-authenticate")
                
        except Exception as e:
            # If there's any error, we'll just ignore the saved credentials
            self.credentials = None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YouTubeUploader()
    window.show()
    sys.exit(app.exec_())
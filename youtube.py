import os
import sys
import json
import pickle
import httplib2
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, 
                            QWidget, QFileDialog, QLabel, QComboBox, QLineEdit, QMessageBox,
                            QProgressBar, QDialog, QListWidget, QListWidgetItem)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# YouTube API Constants
SCOPES = ['https://www.googleapis.com/auth/youtube.upload', 
          'https://www.googleapis.com/auth/youtube.readonly']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'

class AccountManager:
    """Manages YouTube accounts authentication and storage"""
    
    def __init__(self):
        self.accounts_dir = os.path.join(os.path.expanduser('~'), '.youtube_uploader')
        os.makedirs(self.accounts_dir, exist_ok=True)
        self.accounts_file = os.path.join(self.accounts_dir, 'accounts.json')
        self.client_secret_file = None
        self.load_accounts()
    
    def load_accounts(self):
        """Load accounts from storage"""
        if os.path.exists(self.accounts_file):
            with open(self.accounts_file, 'r') as f:
                self.accounts = json.load(f)
        else:
            self.accounts = {}
    
    def save_accounts(self):
        """Save accounts to storage"""
        with open(self.accounts_file, 'w') as f:
            json.dump(self.accounts, f)
    
    def set_client_secret(self, file_path):
        """Set the client secret file"""
        self.client_secret_file = file_path
        # Make a copy in our secure directory
        if not os.path.exists(os.path.join(self.accounts_dir, 'client_secret.json')):
            with open(file_path, 'r') as src, open(os.path.join(self.accounts_dir, 'client_secret.json'), 'w') as dst:
                dst.write(src.read())
        self.client_secret_file = os.path.join(self.accounts_dir, 'client_secret.json')
    
    def get_credentials(self, account_name):
        """Get credentials for a specific account"""
        if account_name not in self.accounts:
            return None
        
        credentials = None
        # Check if we have valid credentials in pickle
        pickle_file = os.path.join(self.accounts_dir, f"{account_name}.pickle")
        if os.path.exists(pickle_file):
            with open(pickle_file, 'rb') as token:
                credentials = pickle.load(token)
        
        # If credentials are invalid or don't exist, refresh or run auth flow
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                # If we can't refresh, remove the account
                if os.path.exists(pickle_file):
                    os.remove(pickle_file)
                return None
            
            # Save the refreshed credentials
            with open(pickle_file, 'wb') as token:
                pickle.dump(credentials, token)
        
        return credentials
    
    def add_account(self, account_name):
        """Add a new account using OAuth2 flow"""
        if not self.client_secret_file:
            raise ValueError("Client secret file not set")
        
        flow = InstalledAppFlow.from_client_secrets_file(self.client_secret_file, SCOPES)
        credentials = flow.run_local_server(port=0)
        
        # Save credentials to pickle file
        pickle_file = os.path.join(self.accounts_dir, f"{account_name}.pickle")
        with open(pickle_file, 'wb') as token:
            pickle.dump(credentials, token)
        
        # Get account information to store
        youtube = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
        channels_response = youtube.channels().list(part='snippet', mine=True).execute()
        
        # Store account info
        channel_info = channels_response['items'][0]['snippet']
        self.accounts[account_name] = {
            'email': account_name,  # Using account_name as email
            'title': channel_info['title'],
            'pickle_file': pickle_file
        }
        self.save_accounts()
        return True
    
    def remove_account(self, account_name):
        """Remove an account"""
        if account_name in self.accounts:
            # Remove pickle file
            pickle_file = os.path.join(self.accounts_dir, f"{account_name}.pickle")
            if os.path.exists(pickle_file):
                os.remove(pickle_file)
            
            # Remove from accounts dictionary
            del self.accounts[account_name]
            self.save_accounts()
            return True
        return False
    
    def get_account_names(self):
        """Get a list of account names"""
        return list(self.accounts.keys())


class UploadThread(QThread):
    """Thread for uploading videos to YouTube"""
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str, str)  # video_id, video_url
    error_signal = pyqtSignal(str)
    
    def __init__(self, credentials, video_file, title, description, tags, category_id, privacy_status, channel_id=None):
        super().__init__()
        self.credentials = credentials
        self.video_file = video_file
        self.title = title
        self.description = description
        self.tags = tags.split(',') if tags else None
        self.category_id = category_id
        self.privacy_status = privacy_status
        self.channel_id = channel_id
    
    def run(self):
        try:
            youtube = build(API_SERVICE_NAME, API_VERSION, credentials=self.credentials)
            
            # Prepare the metadata for the video
            body = {
                'snippet': {
                    'title': self.title,
                    'description': self.description,
                    'tags': self.tags,
                    'categoryId': self.category_id
                },
                'status': {
                    'privacyStatus': self.privacy_status
                }
            }
            
            # If a specific channel is selected
            if self.channel_id:
                body['snippet']['channelId'] = self.channel_id
            
            # Create upload request
            insert_request = youtube.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=MediaFileUpload(self.video_file, 
                                          chunksize=1024*1024, 
                                          resumable=True)
            )
            
            # Upload the video
            response = None
            while response is None:
                status, response = insert_request.next_chunk()
                if status:
                    self.progress_signal.emit(int(status.progress() * 100))
            
            # Get video ID and URL
            video_id = response['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            self.finished_signal.emit(video_id, video_url)
            
        except Exception as e:
            self.error_signal.emit(str(e))


class AccountDialog(QDialog):
    """Dialog for managing YouTube accounts"""
    
    def __init__(self, account_manager, parent=None):
        super().__init__(parent)
        self.account_manager = account_manager
        self.init_ui()
        self.refresh_account_list()
    
    def init_ui(self):
        self.setWindowTitle("Manage YouTube Accounts")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout()
        
        # Client Secret File
        client_secret_layout = QHBoxLayout()
        self.client_secret_label = QLabel("Client Secret:")
        self.client_secret_path = QLineEdit()
        self.client_secret_path.setReadOnly(True)
        self.client_secret_btn = QPushButton("Browse...")
        self.client_secret_btn.clicked.connect(self.browse_client_secret)
        
        client_secret_layout.addWidget(self.client_secret_label)
        client_secret_layout.addWidget(self.client_secret_path)
        client_secret_layout.addWidget(self.client_secret_btn)
        
        # Account List
        self.account_list = QListWidget()
        
        # Account Add Form
        add_account_layout = QHBoxLayout()
        self.new_account_name = QLineEdit()
        self.new_account_name.setPlaceholderText("Enter account name/email")
        self.add_account_btn = QPushButton("Add Account")
        self.add_account_btn.clicked.connect(self.add_account)
        
        add_account_layout.addWidget(self.new_account_name)
        add_account_layout.addWidget(self.add_account_btn)
        
        # Remove Account Button
        self.remove_account_btn = QPushButton("Remove Selected Account")
        self.remove_account_btn.clicked.connect(self.remove_account)
        
        # Close Button
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        
        # Add everything to main layout
        layout.addLayout(client_secret_layout)
        layout.addWidget(QLabel("Accounts:"))
        layout.addWidget(self.account_list)
        layout.addLayout(add_account_layout)
        layout.addWidget(self.remove_account_btn)
        layout.addWidget(self.close_btn)
        
        self.setLayout(layout)
    
    def browse_client_secret(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Client Secret JSON", "", "JSON Files (*.json)"
        )
        if file_path:
            self.client_secret_path.setText(file_path)
            self.account_manager.set_client_secret(file_path)
    
    def refresh_account_list(self):
        self.account_list.clear()
        for account_name in self.account_manager.get_account_names():
            item = QListWidgetItem(account_name)
            self.account_list.addItem(item)
    
    def add_account(self):
        account_name = self.new_account_name.text().strip()
        if not account_name:
            QMessageBox.warning(self, "Error", "Please enter an account name")
            return
        
        if not self.account_manager.client_secret_file:
            QMessageBox.warning(self, "Error", "Please select a client secret file first")
            return
        
        try:
            self.account_manager.add_account(account_name)
            self.refresh_account_list()
            self.new_account_name.clear()
            QMessageBox.information(self, "Success", f"Account '{account_name}' added successfully")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add account: {str(e)}")
    
    def remove_account(self):
        selected_items = self.account_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "Please select an account to remove")
            return
        
        account_name = selected_items[0].text()
        confirm = QMessageBox.question(
            self, "Confirm Removal", 
            f"Are you sure you want to remove account '{account_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if confirm == QMessageBox.Yes:
            if self.account_manager.remove_account(account_name):
                self.refresh_account_list()
                QMessageBox.information(self, "Success", f"Account '{account_name}' removed successfully")
            else:
                QMessageBox.critical(self, "Error", f"Failed to remove account '{account_name}'")


class YouTubeUploader(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.account_manager = AccountManager()
        self.current_credentials = None
        self.channels = []
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("YouTube Video Uploader")
        self.setMinimumSize(600, 400)
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Account selection
        account_layout = QHBoxLayout()
        account_layout.addWidget(QLabel("Select Account:"))
        self.account_combo = QComboBox()
        self.refresh_account_list()
        account_layout.addWidget(self.account_combo)
        
        self.manage_accounts_btn = QPushButton("Manage Accounts")
        self.manage_accounts_btn.clicked.connect(self.manage_accounts)
        account_layout.addWidget(self.manage_accounts_btn)
        
        # Channel selection
        channel_layout = QHBoxLayout()
        channel_layout.addWidget(QLabel("Select Channel:"))
        self.channel_combo = QComboBox()
        channel_layout.addWidget(self.channel_combo)
        
        self.refresh_channels_btn = QPushButton("Refresh Channels")
        self.refresh_channels_btn.clicked.connect(self.load_channels)
        channel_layout.addWidget(self.refresh_channels_btn)
        
        # Video file selection
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("Video File:"))
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        file_layout.addWidget(self.file_path_edit)
        
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(self.browse_btn)
        
        # Video details
        details_layout = QVBoxLayout()
        
        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("Title:"))
        self.title_edit = QLineEdit()
        title_layout.addWidget(self.title_edit)
        
        description_layout = QHBoxLayout()
        description_layout.addWidget(QLabel("Description:"))
        self.description_edit = QLineEdit()
        description_layout.addWidget(self.description_edit)
        
        tags_layout = QHBoxLayout()
        tags_layout.addWidget(QLabel("Tags (comma separated):"))
        self.tags_edit = QLineEdit()
        tags_layout.addWidget(self.tags_edit)
        
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        # Common YouTube categories
        categories = {
            "1": "Film & Animation",
            "2": "Autos & Vehicles",
            "10": "Music",
            "15": "Pets & Animals",
            "17": "Sports",
            "19": "Travel & Events",
            "20": "Gaming",
            "22": "People & Blogs",
            "23": "Comedy",
            "24": "Entertainment",
            "25": "News & Politics",
            "26": "Howto & Style",
            "27": "Education",
            "28": "Science & Technology"
        }
        for cat_id, cat_name in categories.items():
            self.category_combo.addItem(cat_name, cat_id)
        category_layout.addWidget(self.category_combo)
        
        privacy_layout = QHBoxLayout()
        privacy_layout.addWidget(QLabel("Privacy:"))
        self.privacy_combo = QComboBox()
        self.privacy_combo.addItems(["private", "unlisted", "public"])
        privacy_layout.addWidget(self.privacy_combo)
        
        details_layout.addLayout(title_layout)
        details_layout.addLayout(description_layout)
        details_layout.addLayout(tags_layout)
        details_layout.addLayout(category_layout)
        details_layout.addLayout(privacy_layout)
        
        # Upload controls
        upload_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        
        self.upload_btn = QPushButton("Upload Video")
        self.upload_btn.setMinimumHeight(50)
        self.upload_btn.clicked.connect(self.upload_video)
        
        self.url_label = QLabel("Video URL will appear here after upload")
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.url_label.setAlignment(Qt.AlignCenter)
        
        upload_layout.addWidget(self.progress_bar)
        upload_layout.addWidget(self.upload_btn)
        upload_layout.addWidget(self.url_label)
        
        # Add all layouts to main layout
        main_layout.addLayout(account_layout)
        main_layout.addLayout(channel_layout)
        main_layout.addLayout(file_layout)
        main_layout.addLayout(details_layout)
        main_layout.addLayout(upload_layout)
        
        # Connect account combo box change
        self.account_combo.currentTextChanged.connect(self.on_account_changed)
        
        # Check if we have accounts
        if self.account_combo.count() > 0:
            self.on_account_changed(self.account_combo.currentText())
    
    def refresh_account_list(self):
        """Refresh the account combo box"""
        current_account = self.account_combo.currentText()
        
        self.account_combo.clear()
        accounts = self.account_manager.get_account_names()
        self.account_combo.addItems(accounts)
        
        # Try to restore previous selection
        if current_account and current_account in accounts:
            index = self.account_combo.findText(current_account)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
    
    def on_account_changed(self, account_name):
        """Handle account selection change"""
        if not account_name:
            self.current_credentials = None
            self.channels = []
            self.channel_combo.clear()
            return
        
        try:
            self.current_credentials = self.account_manager.get_credentials(account_name)
            if self.current_credentials:
                self.load_channels()
            else:
                QMessageBox.warning(
                    self, "Authentication Error",
                    f"Failed to authenticate account '{account_name}'. Please try re-adding the account."
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error loading account '{account_name}': {str(e)}")
    
    def load_channels(self):
        """Load available channels for the current account"""
        if not self.current_credentials:
            QMessageBox.warning(self, "Error", "No account selected or authentication failed")
            return
        
        try:
            youtube = build(API_SERVICE_NAME, API_VERSION, credentials=self.current_credentials)
            
            # Get channels the user has access to
            channels_response = youtube.channels().list(
                part="snippet,contentDetails",
                mine=True
            ).execute()
            
            self.channel_combo.clear()
            self.channels = []
            
            for channel in channels_response.get("items", []):
                channel_id = channel["id"]
                channel_title = channel["snippet"]["title"]
                self.channels.append({
                    "id": channel_id,
                    "title": channel_title
                })
                self.channel_combo.addItem(channel_title, channel_id)
            
            if not self.channels:
                QMessageBox.information(self, "No Channels", "No YouTube channels found for this account")
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load channels: {str(e)}")
    
    def manage_accounts(self):
        """Open the account management dialog"""
        dialog = AccountDialog(self.account_manager, self)
        result = dialog.exec_()
        if result == QDialog.Accepted:
            self.refresh_account_list()
    
    def browse_file(self):
        """Browse for a video file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", 
            "Video Files (*.mp4 *.avi *.mov *.mkv *.flv *.wmv);;All Files (*)"
        )
        if file_path:
            self.file_path_edit.setText(file_path)
            # Set title from filename if empty
            if not self.title_edit.text():
                base_name = os.path.basename(file_path)
                file_name, _ = os.path.splitext(base_name)
                self.title_edit.setText(file_name)
    
    def upload_video(self):
        """Start the video upload process"""
        # Check if we have all required inputs
        if not self.current_credentials:
            QMessageBox.warning(self, "Error", "Please select an account first")
            return
        
        video_file = self.file_path_edit.text()
        if not video_file or not os.path.exists(video_file):
            QMessageBox.warning(self, "Error", "Please select a valid video file")
            return
        
        title = self.title_edit.text()
        if not title:
            QMessageBox.warning(self, "Error", "Please enter a title for the video")
            return
        
        # Get channel ID if selected
        channel_id = None
        if self.channel_combo.currentIndex() >= 0:
            channel_id = self.channel_combo.currentData()
        
        # Get other metadata
        description = self.description_edit.text()
        tags = self.tags_edit.text()
        category_id = self.category_combo.currentData()
        privacy_status = self.privacy_combo.currentText()
        
        # Start the upload thread
        self.upload_thread = UploadThread(
            self.current_credentials,
            video_file,
            title,
            description,
            tags,
            category_id,
            privacy_status,
            channel_id
        )
        
        # Connect signals
        self.upload_thread.progress_signal.connect(self.update_progress)
        self.upload_thread.finished_signal.connect(self.upload_finished)
        self.upload_thread.error_signal.connect(self.upload_error)
        
        # Disable the upload button during upload
        self.upload_btn.setEnabled(False)
        self.upload_btn.setText("Uploading...")
        self.progress_bar.setValue(0)
        
        # Start the thread
        self.upload_thread.start()
    
    def update_progress(self, progress):
        """Update the progress bar"""
        self.progress_bar.setValue(progress)
    
    def upload_finished(self, video_id, video_url):
        """Handle successful upload"""
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("Upload Video")
        self.progress_bar.setValue(100)
        
        self.url_label.setText(f"Video URL: {video_url}")
        
        QMessageBox.information(
            self, "Upload Successful", 
            f"Video uploaded successfully!\nVideo ID: {video_id}\nURL: {video_url}"
        )
    
    def upload_error(self, error_msg):
        """Handle upload error"""
        self.upload_btn.setEnabled(True)
        self.upload_btn.setText("Upload Video")
        self.progress_bar.setValue(0)
        
        QMessageBox.critical(self, "Upload Error", f"Upload failed: {error_msg}")


def main():
    app = QApplication(sys.argv)
    window = YouTubeUploader()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
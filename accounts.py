import os
import pickle
import json
import base64  # Added for base64 encoding/decoding
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
                            QListWidget, QInputDialog, QMessageBox, QLineEdit,
                            QComboBox, QGroupBox, QFrame, QSplitter)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
import google_auth_oauthlib.flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Constants
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly'
]
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'

class AccountManager:
    """Class to manage multiple Google accounts"""
    
    def __init__(self, accounts_file, client_secrets_file=None, logger=None):
        self.accounts_file = accounts_file
        self.client_secrets_file = client_secrets_file
        self.accounts = {}
        self.current_account = None
        self.logger = logger
        self.load_accounts()
    
    def log(self, message, level="info"):
        """Log message if logger is available"""
        if self.logger:
            if level == "info":
                self.logger.info(message)
            elif level == "error":
                self.logger.error(message)
            elif level == "warning":
                self.logger.warning(message)
    
    def load_accounts(self):
        """Load saved accounts from file"""
        if os.path.exists(self.accounts_file):
            try:
                with open(self.accounts_file, 'r') as f:
                    data = json.load(f)
                    # Convert base64 string back to credentials bytes
                    accounts_data = data.get('accounts', {})
                    for name, account_info in accounts_data.items():
                        if 'credentials' in account_info:
                            try:
                                # Decode the base64 string to bytes
                                creds_bytes = base64.b64decode(account_info['credentials'])
                                # Store the bytes directly
                                account_info['credentials'] = creds_bytes
                            except:
                                self.log(f"Failed to decode credentials for account {name}", "error")
                    
                    self.accounts = accounts_data
                    self.current_account = data.get('current_account')
                self.log(f"Loaded {len(self.accounts)} accounts")
            except Exception as e:
                self.log(f"Error loading accounts: {str(e)}", "error")
                self.accounts = {}
                self.current_account = None
    
    def save_accounts(self):
        """Save accounts to file"""
        try:
            # Create a copy of accounts to modify for JSON serialization
            serializable_accounts = {}
            for name, account_info in self.accounts.items():
                serializable_account = account_info.copy()
                if 'credentials' in serializable_account:
                    # Convert credentials bytes to base64 encoded string for JSON serialization
                    credentials_bytes = serializable_account['credentials']
                    serializable_account['credentials'] = base64.b64encode(credentials_bytes).decode('utf-8')
                serializable_accounts[name] = serializable_account
            
            data = {
                'accounts': serializable_accounts,
                'current_account': self.current_account
            }
            
            with open(self.accounts_file, 'w') as f:
                json.dump(data, f, indent=2)
            self.log(f"Saved {len(self.accounts)} accounts")
            return True
        except Exception as e:
            self.log(f"Error saving accounts: {str(e)}", "error")
            return False
    
    def set_client_secrets_file(self, path):
        """Set the client secrets file path"""
        self.client_secrets_file = path
        self.log(f"Set client secrets file: {path}")
    
    def add_account(self, name, credentials=None):
        """Add a new account"""
        if name in self.accounts:
            self.log(f"Account {name} already exists", "warning")
            return False
        
        if credentials is None:
            # Authenticate with Google
            if not self.client_secrets_file:
                self.log("Client secrets file not set", "error")
                return False
            
            try:
                flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_file, SCOPES)
                credentials = flow.run_local_server(port=8080)
                
                # Test the credentials by getting user info
                youtube = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
                response = youtube.channels().list(part="snippet", mine=True).execute()
                
                if not response.get('items'):
                    self.log("Failed to get channel info for new account", "error")
                    return False
                
                # Get the first channel as the default identifier
                channel_name = response['items'][0]['snippet']['title']
                
                # Serialize credentials to bytes
                credentials_bytes = pickle.dumps(credentials)
                
                # Store account
                self.accounts[name] = {
                    'credentials': credentials_bytes,
                    'display_name': name,
                    'default_channel': channel_name,
                    'channels': self._get_channels(credentials)
                }
                
                self.current_account = name
                self.save_accounts()
                self.log(f"Added new account: {name}")
                return True
                
            except Exception as e:
                self.log(f"Error adding account: {str(e)}", "error")
                return False
        else:
            # Add with provided credentials
            credentials_bytes = pickle.dumps(credentials)
            self.accounts[name] = {
                'credentials': credentials_bytes,
                'display_name': name,
                'channels': self._get_channels(credentials)
            }
            self.save_accounts()
            return True
    
    def rename_account(self, old_name, new_name):
        """Rename an account"""
        if old_name not in self.accounts:
            self.log(f"Account {old_name} not found", "error")
            return False
        
        if new_name in self.accounts:
            self.log(f"Account {new_name} already exists", "error")
            return False
        
        self.accounts[new_name] = self.accounts[old_name]
        self.accounts[new_name]['display_name'] = new_name
        del self.accounts[old_name]
        
        if self.current_account == old_name:
            self.current_account = new_name
            
        self.save_accounts()
        self.log(f"Renamed account {old_name} to {new_name}")
        return True
    
    def remove_account(self, name):
        """Remove an account"""
        if name not in self.accounts:
            self.log(f"Account {name} not found", "error")
            return False
        
        del self.accounts[name]
        
        if self.current_account == name:
            self.current_account = None if not self.accounts else list(self.accounts.keys())[0]
            
        self.save_accounts()
        self.log(f"Removed account: {name}")
        return True
    
    def select_account(self, name):
        """Select an account as current"""
        if name not in self.accounts:
            self.log(f"Account {name} not found", "error")
            return False
        
        self.current_account = name
        # self.save_accounts()
        self.log(f"Selected account: {name}")
        return True
    
    def get_account_credentials(self, name=None):
        """Get credentials for an account"""
        account_name = name if name else self.current_account
        
        if not account_name or account_name not in self.accounts:
            self.log(f"Account {account_name} not found", "error")
            return None
        
        try:
            # Deserialize credentials
            credentials = pickle.loads(self.accounts[account_name]['credentials'])
            
            # Check if credentials need refreshing
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                # Update stored credentials
                self.accounts[account_name]['credentials'] = pickle.dumps(credentials)
                # self.save_accounts()
                self.log(f"Refreshed credentials for {account_name}")
            
            return credentials
        except Exception as e:
            self.log(f"Error getting credentials: {str(e)}", "error")
            return None
    
    def get_current_credentials(self):
        """Get credentials for current account"""
        return self.get_account_credentials(self.current_account)
    
    def get_accounts_list(self):
        """Get list of account names"""
        return list(self.accounts.keys())
    
    def get_account_channels(self, name=None):
        """Get channels for an account"""
        account_name = name if name else self.current_account
        
        if not account_name or account_name not in self.accounts:
            return []
        
        credentials = self.get_account_credentials(account_name)
        if not credentials:
            return []
        
        # Refresh channels list
        channels = self._get_channels(credentials)
        
        # Update stored channels
        if channels:
            self.accounts[account_name]['channels'] = channels
            self.save_accounts()
            
        return channels
    
    def _get_channels(self, credentials):
        """Get channels for credentials"""
        try:
            youtube = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
            
            response = youtube.channels().list(
                part="snippet",
                mine=True
            ).execute()
            
            channels = []
            for channel in response.get("items", []):
                channels.append({
                    "id": channel["id"],
                    "title": channel["snippet"]["title"]
                })
            
            return channels
        except Exception as e:
            self.log(f"Error getting channels: {str(e)}", "error")
            return []


class AccountManagerDialog(QDialog):
    """Dialog for managing Google accounts"""
    
    account_changed = pyqtSignal(str, object, object)  # Signal when account is changed (name, credentials)
    
    def __init__(self, account_manager, parent=None):
        super().__init__(parent)
        self.account_manager = account_manager
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle("Google Account Manager")
        self.setMinimumSize(600, 400)
        
        main_layout = QVBoxLayout(self)
                
        # Account list
        accounts_group = QGroupBox("Accounts")
        accounts_layout = QVBoxLayout()
        
        self.account_list = QListWidget()
        
        accounts_layout.addWidget(self.account_list)
        
        # Account buttons
        account_buttons_layout = QHBoxLayout()
        
        self.add_account_btn = QPushButton("Add Account")
        self.add_account_btn.clicked.connect(self.add_account)
        self.add_account_btn.setEnabled(bool(self.account_manager.client_secrets_file))
        
        self.rename_account_btn = QPushButton("Rename")
        self.rename_account_btn.clicked.connect(self.rename_account)
        self.rename_account_btn.setEnabled(False)
        
        self.remove_account_btn = QPushButton("Remove")
        self.remove_account_btn.clicked.connect(self.remove_account)
        self.remove_account_btn.setEnabled(False)
        
        account_buttons_layout.addWidget(self.add_account_btn)
        account_buttons_layout.addWidget(self.rename_account_btn)
        account_buttons_layout.addWidget(self.remove_account_btn)
        
        accounts_layout.addLayout(account_buttons_layout)
        accounts_group.setLayout(accounts_layout)
        main_layout.addWidget(accounts_group)
        
        # Channel selection section
        channel_group = QGroupBox("YouTube Channels")
        channel_layout = QVBoxLayout()
        
        self.channel_select_label = QLabel("Selected Account Channels:")
        channel_layout.addWidget(self.channel_select_label)
        
        self.channel_combo = QComboBox()
        self.channel_combo.setEnabled(False)
        channel_layout.addWidget(self.channel_combo)
        
        self.refresh_channels_btn = QPushButton("Refresh Channels")
        self.refresh_channels_btn.clicked.connect(self.refresh_channels)
        self.refresh_channels_btn.setEnabled(False)
        channel_layout.addWidget(self.refresh_channels_btn)
        
        channel_group.setLayout(channel_layout)
        main_layout.addWidget(channel_group)
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        
        self.select_btn = QPushButton("Select")
        self.select_btn.clicked.connect(self.accept)
        self.select_btn.setEnabled(False)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.select_btn)
        button_layout.addWidget(self.cancel_btn)
        
        main_layout.addLayout(button_layout)

        self.refresh_account_list()
        self.account_list.itemClicked.connect(self.on_account_selected)
            
    def refresh_account_list(self):
        """Refresh the accounts list widget"""
        self.account_list.clear()
        
        for name in self.account_manager.get_accounts_list():
            self.account_list.addItem(name)
            
            # Select current account if there is one
            if name == self.account_manager.current_account:
                self.account_list.setCurrentRow(self.account_list.count() - 1)
        
        # Update channel combo if current account exists
        if self.account_manager.current_account:
            self.on_account_selected(self.account_list.currentItem())
    
    def on_account_selected(self, item):
        """Handle account selection in the list"""
        if item is None:
            self.rename_account_btn.setEnabled(False)
            self.remove_account_btn.setEnabled(False)
            self.select_btn.setEnabled(False)
            self.refresh_channels_btn.setEnabled(False)
            self.channel_combo.setEnabled(False)
            return
        
        account_name = item.text()
        self.account_manager.select_account(account_name)
        
        self.rename_account_btn.setEnabled(True)
        self.remove_account_btn.setEnabled(True)
        self.select_btn.setEnabled(True)
        self.refresh_channels_btn.setEnabled(True)
        
        # Populate channel combo
        self.refresh_channels()
    
    def refresh_channels(self):
        """Refresh channels for the selected account"""
        if not self.account_manager.current_account:
            return
            
        self.channel_combo.clear()
        channels = self.account_manager.get_account_channels()
        
        if channels:
            for channel in channels:
                self.channel_combo.addItem(channel['title'], channel['id'])
            
            self.channel_combo.setEnabled(True)
        else:
            self.channel_combo.setEnabled(False)
    
    def add_account(self):
        """Add a new Google account"""
        if not self.account_manager.client_secrets_file:
            QMessageBox.warning(self, "Warning", "Please select a client secrets file first")
            return
            
        name, ok = QInputDialog.getText(self, "Add Account", "Enter account name:")
        
        if ok and name:
            # Start authentication process
            QMessageBox.information(
                self, "Authentication", 
                "The browser will open for you to sign in to your Google account.\n"
                "Please complete the authentication process."
            )
            
            if self.account_manager.add_account(name):
                self.refresh_account_list()
                QMessageBox.information(self, "Success", f"Account '{name}' was added successfully")
            else:
                QMessageBox.critical(self, "Error", f"Failed to add account '{name}'")
    
    def rename_account(self):
        """Rename the selected account"""
        if not self.account_list.currentItem():
            return
            
        old_name = self.account_list.currentItem().text()
        new_name, ok = QInputDialog.getText(
            self, "Rename Account", 
            "Enter new account name:", 
            text=old_name
        )
        
        if ok and new_name and new_name != old_name:
            if self.account_manager.rename_account(old_name, new_name):
                self.refresh_account_list()
            else:
                QMessageBox.critical(self, "Error", f"Failed to rename account to '{new_name}'")
    
    def remove_account(self):
        """Remove the selected account"""
        if not self.account_list.currentItem():
            return
            
        account_name = self.account_list.currentItem().text()
        
        reply = QMessageBox.question(
            self, "Confirm Removal",
            f"Are you sure you want to remove account '{account_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            if self.account_manager.remove_account(account_name):
                self.refresh_account_list()
            else:
                QMessageBox.critical(self, "Error", f"Failed to remove account '{account_name}'")
    
    def get_selected_channel(self):
        """Get the selected channel ID"""
        if self.channel_combo.currentIndex() >= 0:
            return {
                'id': self.channel_combo.currentData(),
                'title': self.channel_combo.currentText()
            }
        return None
    
    def accept(self):
        """Accept dialog and emit signal with selected account"""
        if self.account_manager.current_account:
            credentials = self.account_manager.get_current_credentials()
            channel = self.get_selected_channel()
            if credentials:
                self.account_changed.emit(self.account_manager.current_account, credentials, channel)
                super().accept()
            else:
                QMessageBox.critical(self, "Error", "Could not get account credentials")
import os
import sys
current_directory = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(current_directory)

import json
import log
from utils import get_default_settings
from worker import GenerationWorker
from PyQt5.QtGui import QFont, QPalette, QColor
from PyQt5.QtCore import Qt, QDateTime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar, QFileDialog,
                             QGroupBox, QSpinBox, QGridLayout, QSplitter, QSpacerItem, QSizePolicy,
                             QMessageBox, QTabWidget, QScrollArea, QStyleFactory,
                             QCheckBox, QDateTimeEdit, QDialog)

from accounts import AccountManagerDialog, AccountManager  # Your account logic
from uploader import UploadThread
from variables import VariableDialog


class VideoGeneratorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logger = log.setup_logger()
        self.setup_style()
        self.init_ui()

    def setup_style(self):
        """Setup application style and color scheme"""
        self.setStyle(QStyleFactory.create("Fusion"))

    def init_ui(self):
        self.setWindowTitle('AI Video Generator')
        self.setGeometry(100, 100, 1200, 800)
        # self.setMaximumSize(1920, 1080)
        self.setMinimumSize(900, 700)
        
        self.account_manager = AccountManager(
            accounts_file=os.path.join(current_directory, 'accounts.json'),
            client_secrets_file=os.path.join(current_directory, 'google_auth.json'),
            logger=self.logger
        )
        self.selected_channel = None  # Store selected channel (dict with 'id' and 'title')
        self.variables = {}

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout(central_widget)

        # Create a splitter for left and right panels
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel with tabs for better organization
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        self.tab_widget.setDocumentMode(True)

        # Create tabs
        self.setup_general_tab()
        self.setup_prompts_tab()
        self.setup_settings_tab()
        self.setup_youtube_tab()

        left_layout.addWidget(self.tab_widget)

        # Generate button
        generate_button_container = QWidget()
        generate_layout = QVBoxLayout(generate_button_container)

        self.generate_btn = QPushButton("GENERATE VIDEO")
        self.generate_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.generate_btn.setFixedHeight(50)
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.generate_btn.clicked.connect(self.start_generation)

        generate_layout.addWidget(self.generate_btn)
        left_layout.addWidget(generate_button_container)

        # Right panel containing progress and logs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Progress group
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bbb;
                border-radius: 4px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
        """)
        progress_layout.addWidget(self.progress_bar)

        # Current operation label
        self.current_operation_label = QLabel("Ready")
        self.current_operation_label.setAlignment(Qt.AlignCenter)
        self.current_operation_label.setStyleSheet(
            "font-weight: bold; color: #4CAF50;")
        progress_layout.addWidget(self.current_operation_label)

        progress_group.setLayout(progress_layout)
        right_layout.addWidget(progress_group)

        # Progress section
        youtube_upload_progress_group = QGroupBox("Upload Progress")
        youtube_upload_progress_layout = QVBoxLayout()

        self.youtube_upload_progress_bar = QProgressBar()
        self.youtube_upload_progress_bar.setRange(0, 100)
        self.youtube_upload_progress_bar.setValue(0)
        self.youtube_upload_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bbb;
                border-radius: 4px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
        """)
        youtube_upload_progress_layout.addWidget(
            self.youtube_upload_progress_bar)

        self.youtube_status_label = QLabel("Status: Ready")
        youtube_upload_progress_layout.addWidget(self.youtube_status_label)

        self.result_url = QLineEdit()
        self.result_url.setReadOnly(True)
        self.result_url.setPlaceholderText(
            "Video URL will appear here after upload")
        youtube_upload_progress_layout.addWidget(self.result_url)

        youtube_upload_progress_group.setLayout(youtube_upload_progress_layout)
        right_layout.addWidget(youtube_upload_progress_group)

        # Log group
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout()

        # Log window
        self.log_window = QTextEdit()
        self.log_window.setReadOnly(True)
        self.log_window.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #f0f0f0;
                border: 1px solid #444;
                border-radius: 4px;
                font-family: Consolas, monospace;
            }
        """)
        log_layout.addWidget(self.log_window)

        # Clear log button
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #666;
            }
            QPushButton:pressed {
                background-color: #444;
            }
        """)
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_layout.addWidget(self.clear_log_btn)

        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group)

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([800, 400])  # Initial sizes

        # Set up log handler to display logs in the log window
        log_handler = log.LogHandler(self.update_log)
        self.logger.addHandler(log_handler)

        # Set up youtube credential
        self.google_token_path = os.path.join(
            current_directory, 'token.pickle')
        self.client_secrets_file = None
        self.credentials = None

        self.logger.info("Application initialized and ready")

    def setup_general_tab(self):
        """Setup general tab with API key, video title, etc."""
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)

        # API Key Group
        api_key_group = self.create_group_box("OpenAI API Key")
        api_key_layout = QHBoxLayout()

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("Enter your OpenAI API key")
        self.api_key_input.setStyleSheet("padding: 8px;")

        self.toggle_key_visibility_btn = QPushButton("Show")
        self.toggle_key_visibility_btn.setFixedWidth(80)
        self.toggle_key_visibility_btn.clicked.connect(
            self.toggle_key_visibility)

        api_key_layout.addWidget(self.api_key_input)
        api_key_layout.addWidget(self.toggle_key_visibility_btn)
        api_key_group.setLayout(api_key_layout)
        general_layout.addWidget(api_key_group)

        # Video Title Group
        video_title_group = self.create_group_box("Video Details")
        video_title_layout = QGridLayout()

        video_title_label = QLabel("Video Title:")
        self.video_title_input = QLineEdit()
        self.video_title_input.setPlaceholderText("Enter your video title")
        self.video_title_input.setStyleSheet("padding: 8px;")

        video_title_layout.addWidget(video_title_label, 0, 0)
        video_title_layout.addWidget(self.video_title_input, 0, 1)

        video_title_group.setLayout(video_title_layout)
        general_layout.addWidget(video_title_group)

        # Presets Group
        presets_group = self.create_group_box("Presets")
        presets_layout = QVBoxLayout()

        self.settings_filepath_input = QLineEdit()
        self.settings_filepath_input.setReadOnly(True)
        self.settings_filepath_input.setPlaceholderText(
            "No preset file selected")
        self.settings_filepath_input.setStyleSheet("padding: 8px;")

        presets_buttons_layout = QHBoxLayout()

        self.settings_save_button = QPushButton("Save Presets")
        self.settings_save_button.clicked.connect(self.toggle_save_settings)
        self.settings_save_button.setStyleSheet("padding: 8px;")

        self.settings_load_button = QPushButton("Load Presets")
        self.settings_load_button.clicked.connect(self.toggle_load_settings)
        self.settings_load_button.setStyleSheet("padding: 8px;")

        presets_buttons_layout.addItem(QSpacerItem(
            20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        presets_buttons_layout.addWidget(self.settings_save_button)
        presets_buttons_layout.addWidget(self.settings_load_button)

        presets_layout.addWidget(self.settings_filepath_input)
        presets_layout.addLayout(presets_buttons_layout)
        presets_group.setLayout(presets_layout)
        general_layout.addWidget(presets_group)

        # Add stretch to push everything up
        general_layout.addStretch()

        # Add tab
        self.tab_widget.addTab(general_tab, "General")

    def setup_prompts_tab(self):
        """Setup prompts tab with all prompt input fields"""
        prompts_tab = QScrollArea()
        prompts_tab.setWidgetResizable(True)
        prompts_content = QWidget()
        prompts_layout = QVBoxLayout(prompts_content)
        prompts_input_layout = QGridLayout()

        # Thumbnail Prompt Group
        thumbnail_group = self.create_group_box("Thumbnail Prompt")
        thumbnail_layout = QVBoxLayout()

        thumbnail_label = QLabel(
            "Enter prompt for generating a youtube thumbnail:")
        self.thumbnail_prompt_input = QTextEdit()
        self.thumbnail_prompt_input.setPlaceholderText(
            "For example: A vibrant, eye-catching thumbnail for a video about $title...")
        self.thumbnail_prompt_input.setMinimumHeight(80)

        thumbnail_layout.addWidget(thumbnail_label)
        thumbnail_layout.addWidget(self.thumbnail_prompt_input)
        thumbnail_group.setLayout(thumbnail_layout)
        prompts_input_layout.addWidget(thumbnail_group, 0, 0)

        # Images Prompt Group
        images_group = self.create_group_box("Images Prompt")
        images_layout = QVBoxLayout()

        images_label = QLabel("Enter prompt for generating images:")
        self.images_prompt_input = QTextEdit()
        self.images_prompt_input.setPlaceholderText(
            "For example: High quality images that illustrate $title...")
        self.images_prompt_input.setMinimumHeight(80)

        images_layout.addWidget(images_label)
        images_layout.addWidget(self.images_prompt_input)
        images_group.setLayout(images_layout)
        prompts_input_layout.addWidget(images_group, 1, 0)
        
        # Disclamier Text Group
        disclaimer_group = self.create_group_box("Disclaimer Text")
        disclaimer_layout = QVBoxLayout()
        
        disclaimer_label = QLabel("Enter text for disclaimer in the description:")
        self.disclaimer_input = QTextEdit()
        self.disclaimer_input.setPlaceholderText(
            "DISCLAIMER: ...")
        self.disclaimer_input.setMinimumHeight(80)
        
        disclaimer_layout.addWidget(disclaimer_label)
        disclaimer_layout.addWidget(self.disclaimer_input)
        disclaimer_group.setLayout(disclaimer_layout)
        prompts_input_layout.addWidget(disclaimer_group, 2,0)

        # Script Prompts Group
        script_group = self.create_group_box("Script Prompts")
        script_layout = QVBoxLayout()

        # Intro Prompt
        intro_label = QLabel("Intro Prompt:")
        self.intro_prompt_input = QTextEdit()
        self.intro_prompt_input.setPlaceholderText(
            "Enter first prompt for generating the introduction part of the script")
        self.intro_prompt_input.setMinimumHeight(80)

        # Looping Prompt
        looping_label = QLabel("Looping Prompt:")
        self.looping_prompt_input = QTextEdit()
        self.looping_prompt_input.setPlaceholderText(
            "Enter second prompt for generating the main content of the script")
        self.looping_prompt_input.setMinimumHeight(80)

        # Outro Prompt
        outro_label = QLabel("Outro Prompt:")
        self.outro_prompt_input = QTextEdit()
        self.outro_prompt_input.setPlaceholderText(
            "Enter third prompt for generating the conclusion part of the script")
        self.outro_prompt_input.setMinimumHeight(80)

        script_layout.addWidget(intro_label)
        script_layout.addWidget(self.intro_prompt_input)
        script_layout.addWidget(looping_label)
        script_layout.addWidget(self.looping_prompt_input)
        script_layout.addWidget(outro_label)
        script_layout.addWidget(self.outro_prompt_input)

        script_group.setLayout(script_layout)
        prompts_input_layout.addWidget(script_group, 0, 1, 3, 1)
        
        # Button to manage variables.
        manage_prompt_variables_layout = QHBoxLayout()
        space = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.manage_prompt_variables_button = QPushButton("Manage Variables")
        self.manage_prompt_variables_button.clicked.connect(self.open_variable_dialog)
        manage_prompt_variables_layout.addItem(space)
        self.manage_prompt_variables_button.setStyleSheet("""
            QPushButton {
                background-color: #3d85c6;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #5a9bd5;
            }
            QPushButton:pressed {
                background-color: #2a5885;
            }
        """)
        manage_prompt_variables_layout.addWidget(self.manage_prompt_variables_button)
        
        prompts_layout.addLayout(prompts_input_layout)
        prompts_layout.addLayout(manage_prompt_variables_layout)

        # Set content widget for scroll area
        prompts_tab.setWidget(prompts_content)

        # Add tab
        self.tab_widget.addTab(prompts_tab, "Prompts")

    def setup_settings_tab(self):
        """Setup settings tab with generation parameters"""
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)

        # Script Settings Group
        script_settings = self.create_group_box("Script Generation Settings")
        script_layout = QGridLayout()

        # Prompt looping length
        prompt_loop_label = QLabel("Prompt Looping Length:")
        self.prompt_loop_spinbox = QSpinBox()
        self.prompt_loop_spinbox.setRange(1, 100)
        self.prompt_loop_spinbox.setValue(3)
        self.prompt_loop_spinbox.setStyleSheet("padding: 5px;")

        prompt_loop_help = QLabel(
            "Number of times to repeat the looping prompt")
        prompt_loop_help.setStyleSheet("color: #aaa; font-style: italic;")

        script_layout.addWidget(prompt_loop_label, 0, 0)
        script_layout.addWidget(self.prompt_loop_spinbox, 0, 1)
        script_layout.addWidget(prompt_loop_help, 1, 0, 1, 2)

        # Word limit per audio chunk
        audio_word_limit_label = QLabel("Word Limit per Audio Chunk:")
        self.audio_word_limit_spinbox = QSpinBox()
        self.audio_word_limit_spinbox.setRange(10, 800)
        self.audio_word_limit_spinbox.setValue(400)
        self.audio_word_limit_spinbox.setStyleSheet("padding: 5px;")

        audio_word_limit_help = QLabel(
            "Maximum number of words in each audio chunk")
        audio_word_limit_help.setStyleSheet("color: #aaa; font-style: italic;")

        script_layout.addWidget(audio_word_limit_label, 2, 0)
        script_layout.addWidget(self.audio_word_limit_spinbox, 2, 1)
        script_layout.addWidget(audio_word_limit_help, 3, 0, 1, 2)

        script_settings.setLayout(script_layout)
        settings_layout.addWidget(script_settings)

        # Image Settings Group
        image_settings = self.create_group_box("Image Generation Settings")
        image_layout = QGridLayout()

        # Image chunk count
        image_chunk_count_label = QLabel("Image Chunks Count:")
        self.image_chunk_count_spinbox = QSpinBox()
        self.image_chunk_count_spinbox.setRange(1, 20)
        self.image_chunk_count_spinbox.setValue(3)
        self.image_chunk_count_spinbox.setStyleSheet("padding: 5px;")

        image_chunk_count_help = QLabel("Number of images to generate")
        image_chunk_count_help.setStyleSheet(
            "color: #aaa; font-style: italic;")

        image_layout.addWidget(image_chunk_count_label, 0, 0)
        image_layout.addWidget(self.image_chunk_count_spinbox, 0, 1)
        image_layout.addWidget(image_chunk_count_help, 1, 0, 1, 2)

        # Image chunk word limit
        image_chunk_word_limit_label = QLabel(
            "Word Limit For Image Prompt Chunk:")
        self.image_chunk_word_limit_spinbox = QSpinBox()
        self.image_chunk_word_limit_spinbox.setRange(5, 100)
        self.image_chunk_word_limit_spinbox.setValue(15)
        self.image_chunk_word_limit_spinbox.setStyleSheet("padding: 5px;")

        image_chunk_word_limit_help = QLabel(
            "Maximum number of words in each image prompt")
        image_chunk_word_limit_help.setStyleSheet(
            "color: #aaa; font-style: italic;")

        image_layout.addWidget(image_chunk_word_limit_label, 2, 0)
        image_layout.addWidget(self.image_chunk_word_limit_spinbox, 2, 1)
        image_layout.addWidget(image_chunk_word_limit_help, 3, 0, 1, 2)

        image_settings.setLayout(image_layout)
        settings_layout.addWidget(image_settings)

        # Add stretch to push everything up
        settings_layout.addStretch()

        # Add tab
        self.tab_widget.addTab(settings_tab, "Settings")

    def setup_youtube_tab(self):
        """Setup YouTube tab with credentials settings"""
        youtube_tab = QWidget()
        youtube_layout = QVBoxLayout(youtube_tab)

        # YouTube Credentials Group
        youtube_group = self.create_group_box("YouTube API Credentials")

        youtube_cred_layout = QVBoxLayout()

        youtube_info = QLabel(
            "Configure your YouTube API credentials to enable video uploads.")
        youtube_info.setWordWrap(True)
        youtube_info.setStyleSheet("color: #ddd; margin-bottom: 10px;")

        credential_detail_layout = QGridLayout()

        account_name_label = QLabel("Account:")
        self.account_name_edit = QLineEdit()
        self.account_name_edit.setReadOnly(True)
        self.account_name_edit.setPlaceholderText("No credentials loaded")
        self.account_name_edit.setStyleSheet("padding: 8px;")
                
        channel_combo_label = QLabel("Channel:")
        self.channel_edit = QLineEdit()
        self.channel_edit.setReadOnly(True)
        self.channel_edit.setPlaceholderText("No channel selected")
        self.channel_edit.setStyleSheet("padding: 8px;")

        category_id_label = QLabel("Category ID:")
        self.category_id_edit = QLineEdit()
        self.category_id_edit.setPlaceholderText("Input the category id")
        self.category_id_edit.setText('24')
        self.category_id_edit.setStyleSheet("padding: 8px;")

        # Scheduling
        # schedule_layout = QHBoxLayout()
        self.schedule_checkbox = QCheckBox("Schedule publication")
        self.schedule_checkbox.stateChanged.connect(self.toggle_schedule)

        self.schedule_datetime = QDateTimeEdit()
        self.schedule_datetime.setMinimumDateTime(QDateTime.currentDateTime().addSecs(300))
        self.schedule_datetime.setEnabled(False)
        self.schedule_datetime.setStyleSheet("padding: 8px;")

        credential_detail_layout.addWidget(account_name_label, 0, 0)
        credential_detail_layout.addWidget(self.account_name_edit, 0, 1)
        credential_detail_layout.addWidget(channel_combo_label, 1, 0)
        credential_detail_layout.addWidget(self.channel_edit, 1, 1)
        credential_detail_layout.addWidget(category_id_label, 2, 0)
        credential_detail_layout.addWidget(self.category_id_edit, 2, 1)
        credential_detail_layout.addWidget(self.schedule_checkbox, 3, 0)
        credential_detail_layout.addWidget(self.schedule_datetime, 3, 1)

        credential_control_layout = QHBoxLayout()

        self.load_youtube_credential_button = QPushButton("Load Credentials")
        self.load_youtube_credential_button.clicked.connect(
            self.load_youtube_credential)
        self.load_youtube_credential_button.setStyleSheet("""
            QPushButton {
                background-color: #3d85c6;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #5a9bd5;
            }
            QPushButton:pressed {
                background-color: #2a5885;
            }
        """)

        credential_control_layout.addItem(QSpacerItem(
            20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        credential_control_layout.addWidget(
            self.load_youtube_credential_button)

        youtube_guide = QLabel(
            "1. Go to Google Cloud Console and create a project\n"
            "2. Enable the YouTube Data API v3\n"
            "3. Create OAuth 2.0 credentials\n"
            "4. Download the JSON file and load it here"
        )
        youtube_guide.setStyleSheet(
            "color: #aaa; font-style: italic; margin-top: 15px;")
        youtube_guide.setWordWrap(True)

        youtube_cred_layout.addWidget(youtube_info)
        youtube_cred_layout.addLayout(credential_detail_layout)
        youtube_cred_layout.addLayout(credential_control_layout)
        youtube_cred_layout.addWidget(youtube_guide)

        youtube_group.setLayout(youtube_cred_layout)
        youtube_layout.addWidget(youtube_group)

        # Add stretch to push everything up
        youtube_layout.addStretch()

        # Add tab
        self.tab_widget.addTab(youtube_tab, "YouTube")

    def create_group_box(self, title):
        """Helper method to create styled group boxes"""
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 5px;
                margin-top: 1ex;
                padding: 10px;
                color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 5px;
            }
        """)
        return group

    def save_settings(self, file_path):
        """Save current settings to a JSON file"""
        try:
            settings = {
                "api_key": self.api_key_input.text(),
                "video_title": self.video_title_input.text(),
                "thumbnail_prompt": self.thumbnail_prompt_input.toPlainText(),
                "images_prompt": self.images_prompt_input.toPlainText(),
                "disclaimer": self.disclaimer_input.toPlainText(),
                "intro_prompt": self.intro_prompt_input.toPlainText(),
                "looping_prompt": self.looping_prompt_input.toPlainText(),
                "outro_prompt": self.outro_prompt_input.toPlainText(),
                "prompt_variables": self.variables,
                "loop_length": self.prompt_loop_spinbox.value(),
                "audio_word_limit": self.audio_word_limit_spinbox.value(),
                "thumbnail_count": self.image_chunk_count_spinbox.value(),
                "thumbnail_word_limit": self.image_chunk_word_limit_spinbox.value()
            }

            with open(file_path, 'w') as f:
                json.dump(settings, f, indent=4)

            self.logger.info(f"Settings saved to {file_path}")
            QMessageBox.information(
                self, "Settings Saved", "Settings have been saved successfully!")
        except Exception as e:
            self.logger.error(f"Error saving settings: {str(e)}")
            QMessageBox.critical(
                self, "Error", f"Failed to save settings: {str(e)}")

    def load_settings(self, file_path):
        """Load settings from JSON file or create default if file doesn't exist"""
        try:
            # Check if settings file exists
            if not os.path.exists(file_path):
                # Create default settings
                default_settings = get_default_settings()
                with open(file_path, 'w') as f:
                    json.dump(default_settings, f, indent=4)
                self.logger.info(
                    f"Created default settings file at {file_path}")
                settings = default_settings
            else:
                # Load existing settings
                with open(file_path, 'r') as f:
                    settings = json.load(f)
                self.logger.info(f"Loaded settings from {file_path}")

            # Apply settings to UI
            self.api_key_input.setText(settings.get("api_key", ""))
            self.video_title_input.setText(settings.get("video_title", ""))
            self.thumbnail_prompt_input.setPlainText(
                settings.get("thumbnail_prompt", ""))
            self.images_prompt_input.setPlainText(
                settings.get("images_prompt", ""))
            self.disclaimer_input.setPlainText(
                settings.get("disclaimer", "")
            )
            self.intro_prompt_input.setPlainText(
                settings.get("intro_prompt", ""))
            self.looping_prompt_input.setPlainText(
                settings.get("looping_prompt", ""))
            self.outro_prompt_input.setPlainText(
                settings.get("outro_prompt", ""))
            self.prompt_loop_spinbox.setValue(settings.get("loop_length", 3))
            self.variables = settings.get("prompt_variables")
            self.audio_word_limit_spinbox.setValue(
                settings.get("audio_word_limit", 400))
            self.image_chunk_count_spinbox.setValue(
                settings.get("image_count", 3))
            self.image_chunk_word_limit_spinbox.setValue(
                settings.get("image_word_limit", 15))

            QMessageBox.information(
                self, "Settings Loaded", f"Successfully loaded settings from {file_path}")

        except Exception as e:
            self.logger.error(f"Error loading settings: {str(e)}")
            # Use default settings on error
            QMessageBox.warning(self, "Settings Error",
                                f"Failed to load settings: {str(e)}\nUsing default settings.")

    def toggle_key_visibility(self):
        if self.api_key_input.echoMode() == QLineEdit.Password:
            self.api_key_input.setEchoMode(QLineEdit.Normal)
            self.toggle_key_visibility_btn.setText("Hide")
        else:
            self.api_key_input.setEchoMode(QLineEdit.Password)
            self.toggle_key_visibility_btn.setText("Show")

    def update_log(self, message):
        self.log_window.append(message)
        # Auto-scroll to bottom
        self.log_window.verticalScrollBar().setValue(
            self.log_window.verticalScrollBar().maximum()
        )

    def clear_log(self):
        self.log_window.clear()
        self.logger.info("Log cleared")

    def start_generation(self):
        # Validate input
        api_key = self.api_key_input.text().strip()
        if not api_key:
            self.logger.error("API key is required")
            QMessageBox.critical(self, "Error", f"API key is required!")
            return

        # Get all input values
        video_title = self.video_title_input.text().strip()
        thumbnail_prompt = self.thumbnail_prompt_input.toPlainText().strip()
        images_prompt = self.images_prompt_input.toPlainText().strip()
        intro_prompt = self.intro_prompt_input.toPlainText().strip()
        looping_prompt = self.looping_prompt_input.toPlainText().strip()
        outro_prompt = self.outro_prompt_input.toPlainText().strip()

        if not all([thumbnail_prompt, intro_prompt, looping_prompt, outro_prompt]):
            self.logger.error("All prompts are required")
            QMessageBox.critical(self, "Error", f"All prompts are required")
            return

        # if not hasattr(self, 'credentials') or not self.credentials:
        #     self.logger.error(
        #         "Need to load Google client secret JSON file to upload video to YouTube!")
        #     QMessageBox.critical(
        #         self, "Error", f"Need to load Google client secret JSON file to upload video to YouTube!")
        #     return

        video_title = video_title.replace(' ', '-')
        self.video_title = video_title
        thumbnail_prompt = thumbnail_prompt.replace('$title', video_title)
        intro_prompt = intro_prompt.replace('$title', video_title)
        looping_prompt = looping_prompt.replace('$title', video_title)
        outro_prompt = outro_prompt.replace('$title', video_title)
        images_prompt = outro_prompt.replace('$title', video_title)

        loop_length = self.prompt_loop_spinbox.value()
        word_limit = self.audio_word_limit_spinbox.value()
        image_count = self.image_chunk_count_spinbox.value()
        image_word_limit = self.image_chunk_word_limit_spinbox.value()
        
        for key in self.variables:
            keyword = f"${key}"
            value = self.variables[key]
            thumbnail_prompt = thumbnail_prompt.replace(keyword, value)
            intro_prompt = intro_prompt.replace(keyword, value)
            looping_prompt = looping_prompt.replace(keyword, value)
            outro_prompt = outro_prompt.replace(keyword, value)
            images_prompt = images_prompt.replace(keyword, value)

        # Create a worker thread to handle the generation process
        self.worker = GenerationWorker(
            api_key, video_title,
            thumbnail_prompt, images_prompt,
            intro_prompt, looping_prompt, outro_prompt,
            loop_length, word_limit,
            image_count, image_word_limit,
            self.logger
        )

        # Connect signals
        self.worker.progress_update.connect(self.update_progress)
        self.worker.operation_update.connect(self.update_operation)
        self.worker.finished.connect(self.generation_finished)

        # Disable UI elements
        self.toggle_ui_elements(False)

        # Start worker
        self.worker.start()
        self.logger.info("Starting video generation process...")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_operation(self, operation):
        self.current_operation_label.setText(operation)

    def generation_finished(self, description):
        self.logger.info("Video generation completed")
        self.current_operation_label.setText("Generation completed")
        self.progress_bar.setValue(100)
        
        # Upload Progress Start
        if not self.credentials or not self.credentials.valid:
            QMessageBox.warning(self, "Warning", "Please authenticate with YouTube first.")
            return
        
        video_path = os.path.join(self.video_title, "final_slideshow_with_audio.mp4")
        thumbnail_path = os.path.join(self.video_title, "thumbnail.jpg")
        title = self.video_title_input.text()
        category = self.category_id_edit.text()
        video_description = description + "\n\n" + self.disclaimer_input.toPlainText()
        privacy_status = "public"
        made_for_kids = False
        publish_at = None
        if self.schedule_checkbox.isChecked():
            publish_at = self.schedule_datetime.dateTime().toPyDateTime()
            # Convert local datetime to UTC
            import datetime
            import pytz
            
            # Get your local timezone
            local_timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
            
            # Make the datetime timezone-aware with your local timezone
            aware_local_time = publish_at.replace(tzinfo=local_timezone)
            
            # Convert to UTC
            publish_at = aware_local_time.astimezone(pytz.UTC)
        
        self.youtube_upload_progress_bar.setValue(0)
        self.youtube_status_label.setText("Status: Preparing upload...")
        
        self.upload_thread = UploadThread(
            credentials=self.credentials, 
            video_path=video_path, 
            title=title, 
            description=video_description, 
            category=category, 
            tags="", 
            privacy_status=privacy_status, 
            thumbnail_path=thumbnail_path, 
            publish_at=publish_at, 
            made_for_kids=made_for_kids
        )
        
        # Connect signals
        self.upload_thread.progress_signal.connect(self.update_youtube_upload_progress)
        self.upload_thread.finished_signal.connect(self.upload_youtube_upload_finished)
        self.upload_thread.error_signal.connect(self.upload_youtube_error)
        self.upload_thread.status_signal.connect(self.update_upload_youtube_status)
        
        # Start the thread
        self.upload_thread.start()
        
    def update_youtube_upload_progress(self, progress):
        self.youtube_upload_progress_bar.setValue(progress)
    
    def update_upload_youtube_status(self, status):
        self.youtube_status_label.setText(f"Status: {status}")

    def upload_youtube_upload_finished(self, url, video_id):
        self.toggle_ui_elements(True)
        # Update status
        self.youtube_upload_progress_bar.setValue(100)
        
        # Show URL
        self.result_url.setText(url)
        
        # Show success message with different text based on privacy status
        if self.schedule_checkbox.isChecked():
            success_msg = f"Video uploaded and scheduled for publication!\nURL: {url}\nVideo ID: {video_id}"
        else:
            success_msg = f"Video uploaded and published publicly!\nURL: {url}\nVideo ID: {video_id}\n\nYour video is now live and can be viewed by anyone!"
            
        self.logger.info(success_msg)
    
    def upload_youtube_error(self, error_msg):
        self.toggle_ui_elements(True)
        # Re-enable UI elements
        
        # Update status
        self.youtube_status_label.setText(f"Status: Error: {str(error_msg)}")
        
        # Show error message
        self.logger.error(self, "Upload Error", f"Failed to upload video: {str(error_msg)}")

    def toggle_load_settings(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, 'Open Settings File', '', 'JSON Files (*.json);;All Files (*)')
        if file_name:
            self.logger.info(f'Selected settings file: {file_name}')
            self.settings_filepath_input.setText(file_name)
            self.load_settings(file_name)

    def toggle_save_settings(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self, 'Save File', '', 'JSON Files (*.json)')
        if file_name:
            self.logger.info(f'Save settings to: {file_name}')
            self.save_settings(file_name)

    def load_youtube_credential(self):
        dialog = AccountManagerDialog(self.account_manager, self)
        dialog.account_changed.connect(self.on_account_changed)
        if dialog.exec_():
            # Account selected and dialog accepted
            self.logger.info(f"Selected account: {self.account_manager.current_account}")

    def on_account_changed(self, account_name, credentials, channel_title):
        self.credentials = credentials  # Save current account's credentials
        self.account_name_edit.setText(account_name)
        self.channel_edit.setText(channel_title)
    
    def on_channel_selected(self, index):
        if index >= 0:
            self.selected_channel = {
                'title': self.channel_edit.currentText(),
                'id': self.channel_edit.itemData(index)
            }
        
    def toggle_schedule(self, state):
        self.schedule_datetime.setEnabled(state == Qt.Checked)
        
    def open_variable_dialog(self):
        """Open the variable management dialog"""
        dialog = VariableDialog(self.variables, self)
        dialog.variables_saved.connect(self.handle_variables_saved)
        
        # Show dialog and process result
        if dialog.exec_() == QDialog.Accepted:
            # Variables are handled through signal
            pass
    
    def handle_variables_saved(self, variables):
        """Handle the variables saved from dialog"""
        self.variables = variables
        
        # Update status label
        if self.variables:
            count = len(self.variables)
            print(self.variables)
            self.logger.info(f"{count} variable{'s' if count > 1 else ''} defined")

    def toggle_ui_elements(self, enabled):
        # Enable/disable all input widgets
        self.api_key_input.setEnabled(enabled)
        self.toggle_key_visibility_btn.setEnabled(enabled)
        self.video_title_input.setEnabled(enabled)
        self.thumbnail_prompt_input.setEnabled(enabled)
        self.images_prompt_input.setEnabled(enabled)
        self.intro_prompt_input.setEnabled(enabled)
        self.looping_prompt_input.setEnabled(enabled)
        self.outro_prompt_input.setEnabled(enabled)
        self.prompt_loop_spinbox.setEnabled(enabled)
        self.audio_word_limit_spinbox.setEnabled(enabled)
        self.image_chunk_count_spinbox.setEnabled(enabled)
        self.image_chunk_word_limit_spinbox.setEnabled(enabled)
        self.settings_save_button.setEnabled(enabled)
        self.settings_load_button.setEnabled(enabled)
        self.generate_btn.setEnabled(enabled)
        self.load_youtube_credential_button.setEnabled(enabled)
        self.manage_prompt_variables_button.setEnabled(enabled)

        # Update button appearance
        if not enabled:
            self.generate_btn.setText("GENERATING...")
            self.generate_btn.setStyleSheet("""
                QPushButton {
                    background-color: #cccccc;
                    color: #666666;
                    border-radius: 4px;
                }
            """)
        else:
            self.generate_btn.setText("GENERATE VIDEO")
            self.generate_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3d8b40;
                }
            """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Use Fusion style for cross-platform consistency
    app.setStyle(QStyleFactory.create('Fusion'))

    # Set up application palette for a modern look
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)
    window = VideoGeneratorApp()
    window.show()
    sys.exit(app.exec_())

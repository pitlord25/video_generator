from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar, QFileDialog,
                             QGroupBox, QSpinBox, QGridLayout, QSplitter, QSpacerItem, QSizePolicy, QMessageBox)
import json
import log
from worker import GenerationWorker
from utils import get_default_settings, get_settings_filepath
from PyQt5.QtCore import Qt
import sys
import os
current_directory = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(current_directory)


class VideoGeneratorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logger = log.setup_logger()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Video Generator')
        self.setGeometry(100, 100, 1000, 800)
        self.setMaximumSize(1920, 1080)
        self.setMinimumSize(800, 600)

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout(central_widget)

        # Create a splitter for left and right panels
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel containing settings
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # Settings Group
        settings_file_group = QGroupBox('Settings File Path')
        settings_file_layout = QVBoxLayout()
        self.settings_filepath_input = QLineEdit()
        self.settings_filepath_input.setReadOnly(True)
        settings_file_button_layout = QHBoxLayout()
        self.settings_save_button = QPushButton("Save Settings")
        self.settings_load_button = QPushButton("Load Settings")
        self.settings_save_button.clicked.connect(self.toggle_save_settings)
        self.settings_load_button.clicked.connect(self.toggle_load_settings)

        spaceItem = QSpacerItem(
            20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        settings_file_button_layout.addItem(spaceItem)
        settings_file_button_layout.addWidget(self.settings_save_button)
        settings_file_button_layout.addWidget(self.settings_load_button)
        settings_file_layout.addWidget(self.settings_filepath_input)
        settings_file_layout.addLayout(settings_file_button_layout)
        settings_file_group.setLayout(settings_file_layout)
        left_layout.addWidget(settings_file_group)
        # self.

        # API Key Group
        api_key_group = QGroupBox("OpenAI API Key")
        api_key_layout = QHBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("Enter your OpenAI API key")
        self.toggle_key_visibility_btn = QPushButton("Show")
        self.toggle_key_visibility_btn.setFixedWidth(80)
        self.toggle_key_visibility_btn.clicked.connect(
            self.toggle_key_visibility)
        api_key_layout.addWidget(self.api_key_input)
        api_key_layout.addWidget(self.toggle_key_visibility_btn)
        api_key_group.setLayout(api_key_layout)
        left_layout.addWidget(api_key_group)

        # Video Title
        video_title_layout = QGridLayout()
        video_title_label = QLabel("Video Title:")
        self.video_title_input = QLineEdit()
        video_title_layout.addWidget(video_title_label, 0, 0)
        video_title_layout.addWidget(self.video_title_input, 0, 1)
        left_layout.addLayout(video_title_layout)

        # Prompts Group
        prompts_group = QGroupBox("Prompts")
        prompts_layout = QHBoxLayout()
        image_prompts_layout = QVBoxLayout()
        script_prompts_layout = QVBoxLayout()

        # Thumbnail Prompt
        thumbnail_prompt_label = QLabel("Thumbnail Prompt:")
        self.thumbnail_prompt_input = QTextEdit()
        self.thumbnail_prompt_input.setPlaceholderText(
            "Enter prompt for generating youtube thumbnail")
        self.thumbnail_prompt_input.setMinimumHeight(100)
        image_prompts_layout.addWidget(thumbnail_prompt_label)
        image_prompts_layout.addWidget(self.thumbnail_prompt_input)

        # Images Prompt
        images_prompt_label = QLabel("Images Prompt:")
        self.images_prompt_input = QTextEdit()
        self.images_prompt_input.setPlaceholderText(
            "Enter prompt for generating images")
        self.images_prompt_input.setMinimumHeight(100)
        image_prompts_layout.addWidget(images_prompt_label)
        image_prompts_layout.addWidget(self.images_prompt_input)

        # Intro Prompt
        intro_prompt = QLabel("Intro Prompt:")
        self.intro_prompt_input = QTextEdit()
        self.intro_prompt_input.setPlaceholderText(
            "Enter first prompt for generating script")
        self.intro_prompt_input.setMinimumHeight(100)
        script_prompts_layout.addWidget(intro_prompt)
        script_prompts_layout.addWidget(self.intro_prompt_input)

        # Looping Prompt
        looping_prompt_label = QLabel("Looping Prompt:")
        self.looping_prompt_input = QTextEdit()
        self.looping_prompt_input.setPlaceholderText(
            "Enter second prompt for generating script")
        self.looping_prompt_input.setMinimumHeight(100)
        script_prompts_layout.addWidget(looping_prompt_label)
        script_prompts_layout.addWidget(self.looping_prompt_input)

        # Outro Prompt
        outro_prompt_label = QLabel("Outro Prompt:")
        self.outro_prompt_input = QTextEdit()
        self.outro_prompt_input.setPlaceholderText(
            "Enter third prompt for generating script")
        self.outro_prompt_input.setMinimumHeight(100)
        script_prompts_layout.addWidget(outro_prompt_label)
        script_prompts_layout.addWidget(self.outro_prompt_input)

        prompts_layout.addLayout(image_prompts_layout)
        prompts_layout.addLayout(script_prompts_layout)
        prompts_group.setLayout(prompts_layout)
        left_layout.addWidget(prompts_group)

        # Settings Group
        settings_group = QGroupBox("Settings")
        settings_layout = QGridLayout()

        # Prompt looping length
        prompt_loop_label = QLabel("Prompt Looping Length:")
        self.prompt_loop_spinbox = QSpinBox()
        self.prompt_loop_spinbox.setRange(1, 100)
        self.prompt_loop_spinbox.setValue(3)
        settings_layout.addWidget(prompt_loop_label, 0, 0)
        settings_layout.addWidget(self.prompt_loop_spinbox, 0, 1)

        # Word limit per audio chunk
        audio_word_limit_label = QLabel("Word Limit per Audio Chunk:")
        self.audio_word_limit_spinbox = QSpinBox()
        self.audio_word_limit_spinbox.setRange(10, 800)
        self.audio_word_limit_spinbox.setValue(400)
        settings_layout.addWidget(audio_word_limit_label, 1, 0)
        settings_layout.addWidget(self.audio_word_limit_spinbox, 1, 1)

        # Thumbnail chunks settings
        image_chunk_count_label = QLabel("Image Chunks Count:")
        self.image_chunk_count_spinbox = QSpinBox()
        self.image_chunk_count_spinbox.setRange(1, 20)
        self.image_chunk_count_spinbox.setValue(3)
        settings_layout.addWidget(image_chunk_count_label, 2, 0)
        settings_layout.addWidget(self.image_chunk_count_spinbox, 2, 1)

        image_chunk_word_limit_label = QLabel(
            "Word Limit For Image Prompt Chunk:")
        self.image_chunk_word_limit_spinbox = QSpinBox()
        self.image_chunk_word_limit_spinbox.setRange(5, 100)
        self.image_chunk_word_limit_spinbox.setValue(15)
        settings_layout.addWidget(image_chunk_word_limit_label, 3, 0)
        settings_layout.addWidget(self.image_chunk_word_limit_spinbox, 3, 1)

        settings_group.setLayout(settings_layout)
        left_layout.addWidget(settings_group)

        # Generate button
        self.generate_btn = QPushButton("Generate Video")
        self.generate_btn.setFixedHeight(40)
        self.generate_btn.clicked.connect(self.start_generation)
        left_layout.addWidget(self.generate_btn)

        # Add stretch to push everything up
        left_layout.addStretch()

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
        progress_layout.addWidget(self.progress_bar)

        # Current operation label
        self.current_operation_label = QLabel("Ready")
        progress_layout.addWidget(self.current_operation_label)

        progress_group.setLayout(progress_layout)
        right_layout.addWidget(progress_group)

        # Log group
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout()

        # Log window
        self.log_window = QTextEdit()
        self.log_window.setReadOnly(True)
        log_layout.addWidget(self.log_window)

        # Clear log button
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_layout.addWidget(self.clear_log_btn)

        log_group.setLayout(log_layout)
        right_layout.addWidget(log_group)

        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 600])  # Initial sizes

        # Set up log handler to display logs in the log window
        log_handler = log.LogHandler(self.update_log)
        self.logger.addHandler(log_handler)

        self.logger.info("Application initialized and ready")

    def save_settings(self, file_path):
        """Save current settings to a JSON file"""
        try:
            settings = {
                "api_key": self.api_key_input.text(),
                "video_title": self.video_title_input.text(),
                "thumbnail_prompt": self.thumbnail_prompt_input.toPlainText(),
                "images_prompt": self.images_prompt_input.toPlainText(),
                "intro_prompt": self.intro_prompt_input.toPlainText(),
                "looping_prompt": self.looping_prompt_input.toPlainText(),
                "outro_prompt": self.outro_prompt_input.toPlainText(),
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
            self.intro_prompt_input.setPlainText(
                settings.get("intro_prompt", ""))
            self.looping_prompt_input.setPlainText(
                settings.get("looping_prompt", ""))
            self.outro_prompt_input.setPlainText(
                settings.get("outro_prompt", ""))
            self.prompt_loop_spinbox.setValue(settings.get("loop_length", 3))
            self.audio_word_limit_spinbox.setValue(
                settings.get("audio_word_limit", 400))
            self.image_chunk_count_spinbox.setValue(
                settings.get("image_count", 3))
            self.image_chunk_word_limit_spinbox.setValue(
                settings.get("image_word_limit", 15))

            QMessageBox.information(
                self, "Information", f"Succeed to load settings: {file_path}")

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

        video_title = video_title.replace(' ', '-')
        thumbnail_prompt = thumbnail_prompt.replace('$title', video_title)
        intro_prompt = intro_prompt.replace('$title', video_title)
        looping_prompt = looping_prompt.replace('$title', video_title)
        outro_prompt = outro_prompt.replace('$title', video_title)

        loop_length = self.prompt_loop_spinbox.value()
        word_limit = self.audio_word_limit_spinbox.value()
        image_count = self.image_chunk_count_spinbox.value()
        image_word_limit = self.image_chunk_word_limit_spinbox.value()

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

    def generation_finished(self):
        self.toggle_ui_elements(True)
        self.logger.info("Video generation completed")
        self.progress_bar.setValue(100)

    def toggle_load_settings(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, 'Open Settings File', '', 'JSON Files (*.json);;All Files (*)')
        if file_name:
            self.logger.info(f'Selected settings file: {file_name}')
            self.settings_filepath_input.setText(file_name)
            self.load_settings(file_name)
        pass

    def toggle_save_settings(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self, 'Save File', '', 'JSON Files (*.json)')
        if file_name:
            self.logger.info(f'Save settings to: {file_name}')
            # You can write to the file here
            self.save_settings(file_name)
        pass

    def toggle_ui_elements(self, enabled):
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
        self.generate_btn.setEnabled(enabled)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for cross-platform consistency
    window = VideoGeneratorApp()
    window.show()
    sys.exit(app.exec_())

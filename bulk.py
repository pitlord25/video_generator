import os
import sys
current_directory = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(current_directory)

import json
import pandas as pd
import log
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTableWidget, QTableWidgetItem, 
                             QPushButton, QProgressBar, QTextEdit, QLabel,
                             QFileDialog, QMessageBox, QDialog, QFormLayout,
                             QLineEdit, QComboBox, QDialogButtonBox, QHeaderView,
                             QSplitter, QFrame, QStyleFactory, QAbstractItemView,
                             QCheckBox, QDateTimeEdit)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QDateTime, pyqtSlot, Q_ARG
from PyQt5.QtGui import QPalette, QColor, QFont
from accounts import AccountManager
from worker import GenerationWorker
from uploader import UploadThread
import datetime
import traceback
import logging
import queue


class BulkGenerationWorker(QThread):
    """Worker thread for handling bulk generation operations"""
    progress_update = pyqtSignal(int)
    operation_update = pyqtSignal(str)
    finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    row_status_update = pyqtSignal(int, str, str)  # row, status, progress
    
    def __init__(self, generation_data, main_window):
        super().__init__()
        self.generation_data = generation_data
        self.main_window = main_window
        self.is_cancelled = False
        self.current_item_index = 0
        self.current_generation_worker = None
        
        # Track results
        self.successful_items = 0
        self.failed_items = 0
        self.error_messages = []
    
    def cancel(self):
        """Cancel the generation process"""
        self.is_cancelled = True
        if self.current_generation_worker and self.current_generation_worker.isRunning():
            # Cancel current generation worker if it has cancel method
            if hasattr(self.current_generation_worker, 'cancel'):
                self.current_generation_worker.cancel()
    
    def run(self):
        """Main bulk generation process - processes items one by one"""
        try:
            self.operation_update.emit("Starting bulk generation...")
            # Reset all row statuses and counters
            for i in range(len(self.generation_data)):
                self.row_status_update.emit(i, "Ready", "0")
            
            self.successful_items = 0
            self.failed_items = 0
            self.error_messages = []
            
            self.process_next_item()
        except Exception as e:
            self.error_occurred.emit(f"Error during bulk generation: {str(e)}")
    
    def process_next_item(self):
        """Process the next item in the queue"""
        if self.is_cancelled:
            self.finished.emit(f"Bulk generation cancelled by user. Completed: {self.successful_items}, Failed: {self.failed_items}")
            return
        
        if self.current_item_index >= len(self.generation_data):
            # All items processed - provide summary
            total_items = len(self.generation_data)
            summary = f"Bulk generation completed! Total: {total_items}, Successful: {self.successful_items}, Failed: {self.failed_items}"
            
            if self.failed_items > 0:
                summary += f"\n\nFailed items:"
                for i, error_msg in enumerate(self.error_messages[-5:], 1):  # Show last 5 errors
                    summary += f"\n{i}. {error_msg}"
                if len(self.error_messages) > 5:
                    summary += f"\n... and {len(self.error_messages) - 5} more errors (see logs for details)"
            
            self.progress_update.emit(100)
            self.finished.emit(summary)
            return
        
        # Get current item
        current_item = self.generation_data[self.current_item_index]
        total_items = len(self.generation_data)
        
        # Update row status to validating
        self.row_status_update.emit(self.current_item_index, "Validating", "0")
        
        # Validate current item
        self.operation_update.emit(f"Validating item {self.current_item_index + 1}/{total_items}")
        
        if not self.validate_item(current_item):
            self.row_status_update.emit(self.current_item_index, "Error (Validation)", "0")
            error_msg = f"Item {self.current_item_index + 1}: Validation failed"
            self.error_messages.append(error_msg)
            self.operation_update.emit(error_msg)
            self.failed_items += 1
            
            # Continue to next item instead of stopping
            self.current_item_index += 1
            QTimer.singleShot(100, self.process_next_item)
            return
        
        # Update row status to processing
        self.row_status_update.emit(self.current_item_index, "Processing", "0")
        
        # Update progress for validation
        base_progress = int(self.current_item_index / total_items * 100)
        self.progress_update.emit(base_progress)
        
        # Start generation for current item
        self.operation_update.emit(f"Starting generation for item {self.current_item_index + 1}/{total_items}")
        
        # Extract data from preset
        with open(current_item['preset_path'], 'r') as f:
            data = json.load(f)
        
        api_key = data['api_key']
        video_title = current_item['video_title']
        thumbnail_prompt = data['thumbnail_prompt']
        images_prompt = data['images_prompt']
        intro_prompt = data['intro_prompt']
        looping_prompt = data['looping_prompt']
        outro_prompt = data['outro_prompt']
        loop_length = data['loop_length']
        word_limit = data['audio_word_limit']
        image_count = data['thumbnail_count']
        image_word_limit = data['thumbnail_word_limit']
        
        workflow_file = current_item['workflow_path']
        # Create GenerationWorker for this item (you'll modify the parameters)
        self.current_generation_worker = self.worker = GenerationWorker(
            api_key, video_title.replace(' ', '-'),
            thumbnail_prompt, images_prompt,
            intro_prompt, looping_prompt, outro_prompt,
            loop_length, word_limit,
            image_count, image_word_limit,
            workflow_file, self.main_window.logger
        )
        
        # Connect signals
        self.current_generation_worker.progress_update.connect(self.on_item_progress)
        self.current_generation_worker.operation_update.connect(self.on_item_operation)
        self.current_generation_worker.finished.connect(self.on_item_generation_finished)
        self.current_generation_worker.error_occurred.connect(self.on_item_error)
        
        # Start generation for this item
        self.current_generation_worker.start()
    
    def validate_item(self, item):
        """Validate a single item"""
        preset_path = item['preset_path']
        workflow_path = item['workflow_path']
        account = item['account']
        
        # Check file existence
        if not preset_path or not os.path.exists(preset_path):
            self.operation_update.emit(f"Preset file not found: {preset_path}")
            return False
        
        if not workflow_path or not os.path.exists(workflow_path):
            self.operation_update.emit(f"Workflow file not found: {workflow_path}")
            return False
        
        if not account:
            self.operation_update.emit("Account name is required")
            return False
        
        # Validate content
        if not self.main_window.validate_preset_content(preset_path):
            self.operation_update.emit(f"Invalid preset content: {preset_path}")
            return False
        
        if not self.main_window.validate_workflow_content(workflow_path):
            self.operation_update.emit(f"Invalid workflow content: {workflow_path}")
            return False
        
        return True
    
    def on_item_progress(self, progress):
        """Handle progress update from individual item generation"""
        total_items = len(self.generation_data)
        base_progress = int(self.current_item_index / total_items * 100)
        item_progress = int(progress / total_items)
        total_progress = min(base_progress + item_progress, 100)
        self.progress_update.emit(total_progress)
        
        # Update row progress
        self.row_status_update.emit(self.current_item_index, "Processing", str(progress))
    
    def on_item_operation(self, operation):
        """Handle operation update from individual item generation"""
        total_items = len(self.generation_data)
        message = f"[{self.current_item_index + 1}/{total_items}] {operation}"
        self.operation_update.emit(message)
    
    def on_item_generation_finished(self, description):
        current_item = self.generation_data[self.current_item_index]
        
        with open(current_item['preset_path'], 'r') as f:
            preset = json.load(f)
        
        video_title = preset['video_title']
        video_path = os.path.join(video_title.replace(' ', '-'), "final_slideshow_with_audio.mp4")
        thumbnail_path = os.path.join(video_title, "thumbnail.jpg")
        title = video_title
        category = current_item['category']
        video_description = description + "\n\n" + preset['disclaimer']
        privacy_status = "public"
        made_for_kids = False
        
        if current_item['schedule'] == "":
            publish_at = None
        else : 
            # Convert local datetime to UTC
            import datetime
            import pytz
            
            publish_at = datetime.datetime.fromisoformat(current_item['schedule'])
            
            # Get your local timezone
            local_timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
            
            # Make the datetime timezone-aware with your local timezone
            aware_local_time = publish_at.replace(tzinfo=local_timezone)
            
            # Convert to UTC
            publish_at = aware_local_time.astimezone(pytz.UTC)
        
        # self.youtube_upload_progress_bar.setValue(0)
        # self.youtube_status_label.setText("Status: Preparing upload...")
        
        self.upload_thread = UploadThread(
            credentials=current_item['credentials'], 
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
        self.upload_thread.progress_signal.connect(self.on_item_progress)
        self.upload_thread.finished_signal.connect(self.on_item_finished)
        self.upload_thread.error_signal.connect(self.on_item_error)
        
        # Start the thread
        self.upload_thread.start()
    
    def on_item_finished(self, url, video_id):
        """Handle completion of individual item generation"""
        total_items = len(self.generation_data)
        self.operation_update.emit(f"✓ Completed item {self.current_item_index + 1}/{total_items}")
        
        # Update row status to completed
        self.row_status_update.emit(self.current_item_index, "Completed", url)
        self.successful_items += 1
        
        # Move to next item
        self.current_item_index += 1
        self.current_generation_worker = None
        
        # Process next item
        QTimer.singleShot(100, self.process_next_item)  # Small delay before next item
    
    def on_item_error(self, error_message):
        """Handle error from individual item generation - CONTINUE processing instead of stopping"""
        total_items = len(self.generation_data)
        error_msg = f"✗ Item {self.current_item_index + 1}/{total_items}: {error_message}"
        
        # Update row status to error
        self.row_status_update.emit(self.current_item_index, "Error", "0")
        
        # Log the error but don't stop the entire process
        self.operation_update.emit(error_msg)
        self.error_messages.append(error_msg)
        self.failed_items += 1
        
        # Continue to next item instead of stopping the entire process
        self.current_item_index += 1
        self.current_generation_worker = None
        
        # Process next item
        QTimer.singleShot(100, self.process_next_item)  # Small delay before next item


class SettingsDialog(QDialog):
    """Dialog for editing generation settings"""
    
    def __init__(self, parent=None, row_data=None, accounts= []):
        super().__init__(parent)
        self.setWindowTitle("Edit Generation Settings")
        self.setModal(True)
        self.resize(500, 200)
        
        # Available accounts (you can modify this list)
        self.available_accounts = accounts
        
        self.setup_ui()
        
        if row_data:
            self.load_data(row_data)
    
    def setup_ui(self):
        layout = QFormLayout()
        
        # Video Title
        self.video_title_edit = QLineEdit()
        self.video_title_edit.setPlaceholderText("Input the video title")
        
        # Preset file path
        self.preset_layout = QHBoxLayout()
        self.preset_edit = QLineEdit()
        self.preset_edit.setReadOnly(True)  # Make read-only
        self.preset_browse_btn = QPushButton("Browse")
        self.preset_browse_btn.clicked.connect(self.browse_preset_file)
        self.preset_layout.addWidget(self.preset_edit)
        self.preset_layout.addWidget(self.preset_browse_btn)
        
        # Workflow file path
        self.workflow_layout = QHBoxLayout()
        self.workflow_edit = QLineEdit()
        self.workflow_edit.setReadOnly(True)  # Make read-only
        self.workflow_browse_btn = QPushButton("Browse")
        self.workflow_browse_btn.clicked.connect(self.browse_workflow_file)
        self.workflow_layout.addWidget(self.workflow_edit)
        self.workflow_layout.addWidget(self.workflow_browse_btn)
        
        # Account selection
        self.account_combo = QComboBox()
        self.account_combo.setEditable(False)
        self.account_combo.addItems(self.available_accounts)
        
        self.category_id_edit = QLineEdit()
        self.category_id_edit.setPlaceholderText("Input the category id")
        self.category_id_edit.setText('24')

        # Scheduling
        # schedule_layout = QHBoxLayout()
        self.schedule_checkbox = QCheckBox("")
        self.schedule_checkbox.stateChanged.connect(self.toggle_schedule)

        self.schedule_datetime = QDateTimeEdit()
        self.schedule_datetime.setMinimumDateTime(QDateTime.currentDateTime().addSecs(300))
        self.schedule_datetime.setEnabled(False)
        
        # Add to layout
        layout.addRow("Video Title:", self.video_title_edit)
        layout.addRow("Preset File:", self.preset_layout)
        layout.addRow("Workflow File:", self.workflow_layout)
        layout.addRow("Account:", self.account_combo)
        layout.addRow("Category Id:", self.category_id_edit)
        layout.addRow("Schedule publication:", self.schedule_checkbox)
        layout.addRow("", self.schedule_datetime)
        
        # Dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)
        
        self.setLayout(layout)
    
    def toggle_schedule(self, state):
        self.schedule_datetime.setEnabled(state == Qt.Checked)
        
    def browse_preset_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Preset File", "", "JSON Files (*.json)")
        if file_path:
            self.preset_edit.setText(file_path)
    
    def browse_workflow_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Workflow File", "", "JSON Files (*.json)")
        if file_path:
            self.workflow_edit.setText(file_path)
    
    def load_data(self, row_data):
        self.preset_edit.setText(row_data.get('preset_path', ''))
        self.workflow_edit.setText(row_data.get('workflow_path', ''))
        self.video_title_edit.setText(row_data.get('video_title', ''))
        account = row_data.get('account', '')
        index = self.account_combo.findText(account)
        if index >= 0:
            self.account_combo.setCurrentIndex(index)
        else:
            self.account_combo.setCurrentText(account)
    
    def get_data(self):
        publish_at = self.schedule_datetime.dateTime().toPyDateTime()
        
        return {
            'video_title': self.video_title_edit.text(),
            'preset_path': self.preset_edit.text(),
            'workflow_path': self.workflow_edit.text(),
            'account': self.account_combo.currentText(),
            'category': self.category_id_edit.text(),
            'schedule': publish_at.strftime("%Y-%m-%dT%H:%M:%S") if self.schedule_checkbox.isChecked() else ""
        }

class BulkGenerationApp(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.logger, _ = log.setup_logger()
        
        self.generation_worker = None
        self.setup_ui()
        self.setup_connections()
        self.setup_timer_based_logging()
        
    def setup_ui(self):
        self.setWindowTitle("Bulk Generation Manager")
        self.setGeometry(100, 100, 1200, 800)
        
        self.account_manager = AccountManager(
            accounts_file=os.path.join(current_directory, 'accounts.json'),
            client_secrets_file=os.path.join(current_directory, 'google_auth.json'),
            logger=self.logger
        )
        
        # Central widget with splitter
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left panel - Settings
        left_panel = self.create_left_panel()
        splitter.addWidget(left_panel)
        
        # Right panel - Progress and logs
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)
        
        # Set splitter proportions
        splitter.setSizes([900, 300])
    
    def create_left_panel(self):
        """Create the left panel with settings table"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        
        # Title
        title = QLabel("Generation Settings")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title)
        
        # Table
        self.settings_table = QTableWidget()
        self.settings_table.setColumnCount(9)
        self.settings_table.setHorizontalHeaderLabels(["Video Title", "Preset File", "Workflow File", "Account", "Category", "Scheduled Time", "Status", "Progress", "Video URL"])
        
        # Make table fill the width
        header = self.settings_table.horizontalHeader()
        
        header.setSectionResizeMode(QHeaderView.Interactive)
        self.settings_table.setColumnWidth(0, 200)
        self.settings_table.setColumnWidth(1, 200)
        self.settings_table.setColumnWidth(2, 200)
        # header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        # header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        # header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        
        self.settings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.settings_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.settings_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        self.settings_table.setAlternatingRowColors(True)
        layout.addWidget(self.settings_table)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.add_btn = QPushButton("Add Row")
        self.edit_btn = QPushButton("Edit Row")
        self.delete_btn = QPushButton("Delete Row")
        self.load_btn = QPushButton("Load Data")
        self.save_btn = QPushButton("Save Data")
        
        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.edit_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.load_btn)
        button_layout.addWidget(self.save_btn)
        
        layout.addLayout(button_layout)
        
        return panel
    
    def create_right_panel(self):
        """Create the right panel with progress and logs"""
        panel = QFrame()
        panel.setFrameStyle(QFrame.StyledPanel)
        layout = QVBoxLayout(panel)
        
        # Title
        title = QLabel("Generation Progress")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Ready to start generation")
        layout.addWidget(self.status_label)
        
        # Logs
        logs_label = QLabel("Logs:")
        logs_label.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(logs_label)
        
        self.log_window = QTextEdit()
        self.log_window.setReadOnly(True)
        self.log_window.setMaximumHeight(300)
        layout.addWidget(self.log_window)
        
        # Control buttons
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Generation")
        self.cancel_btn = QPushButton("Cancel Generation")
        self.cancel_btn.setEnabled(False)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.cancel_btn)
        control_layout.addStretch()
        
        layout.addLayout(control_layout)
        layout.addStretch()
        
        return panel
    
    def setup_connections(self):
        """Setup signal-slot connections"""
        self.add_btn.clicked.connect(self.add_row)
        self.edit_btn.clicked.connect(self.edit_row)
        self.delete_btn.clicked.connect(self.delete_row)
        self.load_btn.clicked.connect(self.load_data)
        self.save_btn.clicked.connect(self.save_data)
        self.start_btn.clicked.connect(self.start_generation)
        self.cancel_btn.clicked.connect(self.cancel_generation)
        
        # Table double-click to edit
        self.settings_table.doubleClicked.connect(self.edit_row)
    
    def setup_timer_based_logging(self):
        """Alternative approach using QTimer for even safer logging"""
        from PyQt5.QtCore import QTimer
        
        # Create a timer to periodically check for log messages
        self.log_timer = QTimer()
        self.log_timer.timeout.connect(self.process_log_queue)
        self.log_timer.start(100)  # Check every 100ms
        
        # Use a queue for log messages
        import queue
        self.log_message_queue = queue.Queue()
        
        # Create custom handler that uses the queue
        class QueueLogHandler(logging.Handler):
            def __init__(self, message_queue):
                super().__init__()
                self.message_queue = message_queue
                formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
                self.setFormatter(formatter)
            
            def emit(self, record):
                try:
                    msg = self.format(record)
                    try:
                        self.message_queue.put_nowait(msg)
                    except queue.Full:
                        pass  # Skip if queue is full
                except Exception:
                    pass
        
        # Add the queue handler to logger
        self.queue_handler = QueueLogHandler(self.log_message_queue)
        self.logger.addHandler(self.queue_handler)
    
    def process_log_queue(self):
        """Process log messages from queue (called by timer)"""
        messages_processed = 0
        max_messages_per_update = 10  # Limit to prevent UI blocking
        
        try:
            while messages_processed < max_messages_per_update:
                try:
                    message = self.log_message_queue.get_nowait()
                    self.update_log(message)
                    messages_processed += 1
                except queue.Empty:
                    break
        except Exception:
            pass  # Ignore errors in log processing
    def update_log(self, message):
        """Thread-safe log update method"""
        try:
            # Make sure we're in the main thread
            if QThread.currentThread() != QApplication.instance().thread():
                # If not in main thread, use QMetaObject.invokeMethod for thread safety
                from PyQt5.QtCore import QMetaObject, Qt
                QMetaObject.invokeMethod(
                    self, 
                    "_update_log_ui", 
                    Qt.QueuedConnection,
                    Q_ARG(str, message)
                )
            else:
                self._update_log_ui(message)
        except Exception:
            pass  # Ignore UI update errors
    
    @pyqtSlot(str)
    def _update_log_ui(self, message):
        """Actually update the UI (must be called from main thread)"""
        try:
            self.log_window.append(message)
            
            # Limit the number of lines in log window to prevent memory issues
            max_lines = 1000
            if self.log_window.document().lineCount() > max_lines:
                cursor = self.log_window.textCursor()
                cursor.movePosition(cursor.Start)
                cursor.movePosition(cursor.Down, cursor.KeepAnchor, 100)  # Remove first 100 lines
                cursor.removeSelectedText()
            
            # Auto-scroll to bottom
            scrollbar = self.log_window.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            
        except Exception:
            pass  # Ignore UI errors
    
    def closeEvent(self, event):
        """Clean up when closing the application"""
        try:
            # Stop the timer if using timer-based logging
            if hasattr(self, 'log_timer'):
                self.log_timer.stop()
            
            # Clean up logging handlers
            if hasattr(self, 'logger'):
                handlers = self.logger.handlers[:]
                for handler in handlers:
                    handler.close()
                    self.logger.removeHandler(handler)
            
        except Exception:
            pass
        
        event.accept()

    def add_row(self):
        """Add a new row to the settings table"""
        dialog = SettingsDialog(self, accounts=self.account_manager.get_accounts_list())
        if dialog.exec_() == QDialog.Accepted:
            data = dialog.get_data()
            self.add_table_row(data)
    
    def edit_row(self):
        """Edit the selected row"""
        current_row = self.settings_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a row to edit.")
            return
        
        # Get current row data
        row_data = self.get_row_data(current_row)
        
        dialog = SettingsDialog(self, row_data, accounts=self.account_manager.get_accounts_list())
        if dialog.exec_() == QDialog.Accepted:
            # Validate video title after dialog accepted
            video_title = dialog.video_title_edit.text().strip()
            if not video_title:
                QMessageBox.warning(self, "Input Error", "Video title cannot be empty.")
                # Optionally reopen the dialog
                self.edit_row()  # or just return
                return
            data = dialog.get_data()
            self.update_table_row(current_row, data)
    
    def delete_row(self):
        """Delete the selected row"""
        current_row = self.settings_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a row to delete.")
            return
        
        reply = QMessageBox.question(self, "Confirm Delete", 
                                   "Are you sure you want to delete this row?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.settings_table.removeRow(current_row)
    
    def get_row_data(self, row):
        """Get data from a table row"""
        return {
            'video_title': self.settings_table.item(row,0).text() if self.settings_table.item(row, 0) else '',
            'preset_path': self.settings_table.item(row, 1).text() if self.settings_table.item(row, 1) else '',
            'workflow_path': self.settings_table.item(row, 2).text() if self.settings_table.item(row, 2) else '',
            'account': self.settings_table.item(row, 3).text() if self.settings_table.item(row, 3) else '',
            'category': self.settings_table.item(row, 4).text() if self.settings_table.item(row, 4) else '',
            'schedule': self.settings_table.item(row, 5).text() if self.settings_table.item(row, 5) else '',
            'status': self.settings_table.item(row, 6).text() if self.settings_table.item(row, 6) else 'Ready',
            'progress': self.settings_table.item(row, 7).text() if self.settings_table.item(row, 7) else '0%'
        }
    
    def add_table_row(self, data):
        """Add data to a new table row"""
        row = self.settings_table.rowCount()
        self.settings_table.insertRow(row)
        self.update_table_row(row, data)
    
    def update_table_row(self, row, data):
        """Update a table row with data"""
        self.settings_table.setItem(row, 0, QTableWidgetItem(data['video_title']))
        self.settings_table.setItem(row, 1, QTableWidgetItem(data['preset_path']))
        self.settings_table.setItem(row, 2, QTableWidgetItem(data['workflow_path']))
        self.settings_table.setItem(row, 3, QTableWidgetItem(data['account']))
        self.settings_table.setItem(row, 4, QTableWidgetItem(data['category']))
        self.settings_table.setItem(row, 5, QTableWidgetItem(data['schedule']))
        
        # Set status and progress if not provided
        status = data.get('status', 'Ready')
        progress = data.get('progress', '0%')
        self.settings_table.setItem(row, 6, QTableWidgetItem(status))
        self.settings_table.setItem(row, 7, QTableWidgetItem(progress))
        self.settings_table.setItem(row, 8, QTableWidgetItem(""))
        
        # Make status and progress columns read-only
        if self.settings_table.item(row, 6):
            self.settings_table.item(row, 6).setFlags(self.settings_table.item(row, 6).flags() & ~Qt.ItemIsEditable)
        if self.settings_table.item(row, 7):
            self.settings_table.item(row, 7).setFlags(self.settings_table.item(row, 7).flags() & ~Qt.ItemIsEditable)
        
        # Color-code based on validation
        self.validate_and_color_row(row, data)
    
    def validate_and_color_row(self, row, data):
        """Validate row data and color-code accordingly"""
        is_valid = True
        
        # Validate preset file
        if not data['preset_path'] or not os.path.exists(data['preset_path']):
            self.settings_table.item(row, 1).setBackground(QColor(80, 40, 40))  # Dark red
            is_valid = False
        else:
            # Dummy content validation for preset
            if not self.validate_preset_content(data['preset_path']):
                self.settings_table.item(row, 1).setBackground(QColor(80, 60, 30))  # Dark yellow/orange
                is_valid = False
            else:
                self.settings_table.item(row, 1).setBackground(QColor(40, 80, 40))  # Dark green
        
        # Validate workflow file
        if not data['workflow_path'] or not os.path.exists(data['workflow_path']):
            self.settings_table.item(row, 2).setBackground(QColor(80, 40, 40))  # Dark red
            is_valid = False
        else:
            # Dummy content validation for workflow
            if not self.validate_workflow_content(data['workflow_path']):
                self.settings_table.item(row, 2).setBackground(QColor(80, 60, 30))  # Dark yellow/orange
                is_valid = False
            else:
                self.settings_table.item(row, 2).setBackground(QColor(40, 80, 40))  # Dark green
        
        # Validate account
        if not data['account']:
            self.settings_table.item(row, 3).setBackground(QColor(80, 40, 40))  # Dark red
            is_valid = False
        else:
            self.settings_table.item(row, 3).setBackground(QColor(40, 80, 40))  # Dark green
        
        return is_valid

    def update_row_status(self, row, status, progress=None):
        """Update the status and progress of a specific row"""
        if row < self.settings_table.rowCount():
            # Update status
            status_item = QTableWidgetItem(status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.settings_table.setItem(row, 6, status_item)
            
            # Color code based on status
            if status == "Completed":
                self.settings_table.item(row, 6).setBackground(QColor(40, 80, 40))  # Dark green
                self.settings_table.item(row, 7).setBackground(QColor(40, 80, 40))  # Dark green
                self.settings_table.item(row, 8).setText(progress)
                progress = "100"
                
            elif status == "Processing":
                self.settings_table.item(row, 6).setBackground(QColor(80, 60, 30))  # Dark yellow/orange
                self.settings_table.item(row, 7).setBackground(QColor(80, 60, 30))  # Dark yellow/orange
            elif status in ["Error", "Error (Validation)"]:
                self.settings_table.item(row, 6).setBackground(QColor(80, 40, 40))  # Dark red
                self.settings_table.item(row, 7).setBackground(QColor(80, 40, 40))  # Dark red
            elif status == "Validating":
                self.settings_table.item(row, 6).setBackground(QColor(50, 50, 80))  # Dark blue
                self.settings_table.item(row, 7).setBackground(QColor(50, 50, 80))  # Dark blue
            
            # Update progress if provided
            if progress is not None:
                progress_text = f"{progress}%" if isinstance(progress, int) else str(progress)
                progress_item = QTableWidgetItem(progress_text)
                progress_item.setFlags(progress_item.flags() & ~Qt.ItemIsEditable)
                self.settings_table.setItem(row, 7, progress_item)
                
    def validate_preset_content(self, file_path):
        """Preset content validation"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            if 'api_key' not in data:
                return False
            
            if 'video_title' not in data:
                return False
            
            if 'thumbnail_prompt' not in data:
                return False
            
            if 'images_prompt' not in data:
                return False
            
            if 'disclaimer' not in data:
                return False
            
            if 'intro_prompt' not in data:
                return False
            
            if 'looping_prompt' not in data:
                return False
            
            if 'outro_prompt' not in data:
                return False
            
            if 'loop_length' not in data:
                return False
            
            if 'audio_word_limit' not in data:
                return False
            
            if 'thumbnail_count' not in data:
                return False
            
            if 'thumbnail_word_limit' not in data:
                return False
            
            return True
            # return isinstance(data, dict)
        except:
            return False
    
    def validate_workflow_content(self, file_path):
        """Dummy workflow content validation - replace with actual logic"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                
            prompt_exist = False
            width_exist = False
            height_exist = False
            ksampler_exist = False
            
            for node_num, node in data.items():
                if '_meta' not in node or 'title' not in node['_meta']:
                    continue

                if node['_meta']['title'] == 'prompt':
                    prompt_exist = True
                
                if node['_meta']['title'] == 'width':
                    width_exist = True

                if node['_meta']['title'] == 'height':
                    height_exist = True

                if node['_meta']['title'] == 'KSampler':
                    ksampler_exist = True
            
            return prompt_exist or width_exist or height_exist or ksampler_exist
        
        except:
            return False
    
    def load_data(self):
        """Load data from CSV or XLSX file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Data", "", "Excel Files (*.xlsx);;CSV Files (*.csv)")
        
        if not file_path:
            return
        
        try:
            if file_path.endswith('.xlsx'):
                df = pd.read_excel(file_path)
            else:
                df = pd.read_csv(file_path)
        
            def safe_str(val):
                return '' if pd.isna(val) else str(val)
            
            # Clear existing data
            self.settings_table.setRowCount(0)
            
            # Load data into table
            for _, row in df.iterrows():
                data =  {
                    'video_title': safe_str(row.get('video_title')),
                    'preset_path': safe_str(row.get('preset_path')),
                    'workflow_path': safe_str(row.get('workflow_path')),
                    'account': safe_str(row.get('account')),
                    'category': safe_str(row.get('category')),
                    'schedule': safe_str(row.get('schedule')),
                    'status': 'Ready',
                    'progress': '0%'
                }
                print(row.get('schedule', ''))
                self.add_table_row(data)
            
            self.logger.info(f"Successfully loaded {len(df)} rows from {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load data: {str(e)}")
            
    def save_data(self):
        """Save data to CSV or XLSX file"""
        if self.settings_table.rowCount() == 0:
            QMessageBox.warning(self, "Warning", "No data to save.")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Data", "", "Excel Files (*.xlsx);;CSV Files (*.csv)")
        
        if not file_path:
            return
        
        try:
            data = []
            for row in range(self.settings_table.rowCount()):
                row_data = self.get_row_data(row)
                # Only save the core data, not status/progress
                data.append({
                    'video_title': row_data['video_title'],
                    'preset_path': row_data['preset_path'],
                    'workflow_path': row_data['workflow_path'],
                    'account': row_data['account'],
                    'category': row_data['category'],
                    'schedule': row_data['schedule'],
                })
            
            df = pd.DataFrame(data)
            
            if file_path.endswith('.xlsx'):
                df.to_excel(file_path, index=False)
            else:
                df.to_csv(file_path, index=False)
            
            self.logger.info(f"Successfully saved {len(data)} rows to {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save data: {str(e)}")
    
    def start_generation(self):
        """Start the bulk generation process"""
        if self.settings_table.rowCount() == 0:
            QMessageBox.warning(self, "Warning", "No data to generate.")
            return
        
        # Collect all row data (validation will be done per item in the worker)
        generation_data = []
        for row in range(self.settings_table.rowCount()):
            data = self.get_row_data(row)
            data['credentials'] = self.account_manager.get_account_credentials(data['account'])
            generation_data.append(data)
        
        if not generation_data:
            QMessageBox.warning(self, "Warning", "No data to generate.")
            return
        
        # Start bulk generation
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        self.bulk_generation_worker = BulkGenerationWorker(generation_data, self)
        self.bulk_generation_worker.progress_update.connect(self.update_progress)
        self.bulk_generation_worker.operation_update.connect(self.update_status)
        self.bulk_generation_worker.finished.connect(self.generation_finished)
        self.bulk_generation_worker.error_occurred.connect(self.generation_error)
        self.bulk_generation_worker.row_status_update.connect(self.update_row_status)
        
        self.bulk_generation_worker.start()
        self.logger.info(f"Started bulk generation for {len(generation_data)} items")
    
    def cancel_generation(self):
        """Cancel the ongoing generation"""
        if hasattr(self, 'bulk_generation_worker') and self.bulk_generation_worker and self.bulk_generation_worker.isRunning():
            self.bulk_generation_worker.cancel()
            self.logger.info("Cancellation requested...")
    
    def update_progress(self, value):
        """Update the progress bar"""
        self.progress_bar.setValue(value)
    
    def update_status(self, message):
        """Update the status label and log"""
        self.status_label.setText(message)
        self.logger.info(message)
    
    def generation_finished(self, message):
        """Handle generation completion"""
        self.logger.info(f"Generation finished: {message}")
        self.status_label.setText("Generation completed")
        self.reset_generation_ui()
    
    def generation_error(self, error_message):
        """Handle generation error"""
        self.logger.info(f"Error: {error_message}")
        self.status_label.setText("Generation failed")
        QMessageBox.critical(self, "Generation Error", error_message)
        self.reset_generation_ui()
    
    def reset_generation_ui(self):
        """Reset UI after generation completion/cancellation"""
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        if hasattr(self, 'bulk_generation_worker'):
            self.bulk_generation_worker = None


def main():
    app = QApplication(sys.argv)
    
    # Apply the specified style
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
    
    window = BulkGenerationApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
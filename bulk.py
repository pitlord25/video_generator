import sys
import os
import json
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTableWidget, QTableWidgetItem, 
                             QPushButton, QProgressBar, QTextEdit, QLabel,
                             QFileDialog, QMessageBox, QDialog, QFormLayout,
                             QLineEdit, QComboBox, QDialogButtonBox, QHeaderView,
                             QSplitter, QFrame, QStyleFactory, QAbstractItemView)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QPalette, QColor, QFont
import time
import traceback


class BulkGenerationWorker(QThread):
    """Worker thread for handling bulk generation operations"""
    progress_update = pyqtSignal(int)
    operation_update = pyqtSignal(str)
    finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    row_status_update = pyqtSignal(int, str, int)  # row, status, progress
    
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
                self.row_status_update.emit(i, "Ready", 0)
            
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
        self.row_status_update.emit(self.current_item_index, "Validating", 0)
        
        # Validate current item
        self.operation_update.emit(f"Validating item {self.current_item_index + 1}/{total_items}")
        
        if not self.validate_item(current_item):
            self.row_status_update.emit(self.current_item_index, "Error (Validation)", 0)
            error_msg = f"Item {self.current_item_index + 1}: Validation failed"
            self.error_messages.append(error_msg)
            self.operation_update.emit(error_msg)
            self.failed_items += 1
            
            # Continue to next item instead of stopping
            self.current_item_index += 1
            QTimer.singleShot(100, self.process_next_item)
            return
        
        # Update row status to processing
        self.row_status_update.emit(self.current_item_index, "Processing", 0)
        
        # Update progress for validation
        base_progress = int(self.current_item_index / total_items * 100)
        self.progress_update.emit(base_progress)
        
        # Start generation for current item
        self.operation_update.emit(f"Starting generation for item {self.current_item_index + 1}/{total_items}")
        
        # Create GenerationWorker for this item (you'll modify the parameters)
        self.current_generation_worker = GenerationWorker(current_item)  # Modify parameters as needed
        
        # Connect signals
        self.current_generation_worker.progress_update.connect(self.on_item_progress)
        self.current_generation_worker.operation_update.connect(self.on_item_operation)
        self.current_generation_worker.finished.connect(self.on_item_finished)
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
        self.row_status_update.emit(self.current_item_index, "Processing", progress)
    
    def on_item_operation(self, operation):
        """Handle operation update from individual item generation"""
        total_items = len(self.generation_data)
        message = f"[{self.current_item_index + 1}/{total_items}] {operation}"
        self.operation_update.emit(message)
    
    def on_item_finished(self, message):
        """Handle completion of individual item generation"""
        total_items = len(self.generation_data)
        self.operation_update.emit(f"✓ Completed item {self.current_item_index + 1}/{total_items}: {message}")
        
        # Update row status to completed
        self.row_status_update.emit(self.current_item_index, "Completed", 100)
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
        self.row_status_update.emit(self.current_item_index, "Error", 0)
        
        # Log the error but don't stop the entire process
        self.operation_update.emit(error_msg)
        self.error_messages.append(error_msg)
        self.failed_items += 1
        
        # Continue to next item instead of stopping the entire process
        self.current_item_index += 1
        self.current_generation_worker = None
        
        # Process next item
        QTimer.singleShot(100, self.process_next_item)  # Small delay before next item


# Placeholder for your existing GenerationWorker
class GenerationWorker(QThread):
    """Your existing GenerationWorker - modify parameters as needed"""
    progress_update = pyqtSignal(int)
    operation_update = pyqtSignal(str)
    finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, item_data):
        super().__init__()
        self.item_data = item_data
        self.is_cancelled = False
        # TODO: Modify constructor parameters according to your existing GenerationWorker
    
    def cancel(self):
        """Cancel the current generation"""
        self.is_cancelled = True
    
    def run(self):
        """Your existing generation logic"""
        # TODO: Replace this with your actual GenerationWorker implementation
        # This is just a placeholder that includes some error simulation
        try:
            preset_path = self.item_data['preset_path']
            workflow_path = self.item_data['workflow_path'] 
            account = self.item_data['account']
            
            self.operation_update.emit(f"Processing with account: {account}")
            
            # Simulate your generation process with occasional errors for testing
            # Remove this error simulation in your actual implementation
            import random
            if random.random() < 0.2:  # 20% chance of error for testing
                raise Exception("Simulated random error for testing")
            
            # Simulate work
            for i in range(100):
                if self.is_cancelled:
                    self.error_occurred.emit("Generation cancelled")
                    return
                    
                time.sleep(0.05)  # Simulate work
                self.progress_update.emit(i + 1)
                if i % 20 == 0:
                    self.operation_update.emit(f"Generation step {i + 1}/100")
            
            self.finished.emit("Generation completed successfully")
            
        except Exception as e:
            self.error_occurred.emit(f"Generation failed: {str(e)}")


class SettingsDialog(QDialog):
    """Dialog for editing generation settings"""
    
    def __init__(self, parent=None, row_data=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Generation Settings")
        self.setModal(True)
        self.resize(500, 200)
        
        # Available accounts (you can modify this list)
        self.available_accounts = ["Account1", "Account2", "Account3", "TestAccount", "MainAccount"]
        
        self.setup_ui()
        
        if row_data:
            self.load_data(row_data)
    
    def setup_ui(self):
        layout = QFormLayout()
        
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
        self.account_combo.addItems(self.available_accounts)
        self.account_combo.setEditable(True)
        
        # Add to layout
        layout.addRow("Preset File:", self.preset_layout)
        layout.addRow("Workflow File:", self.workflow_layout)
        layout.addRow("Account:", self.account_combo)
        
        # Dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)
        
        self.setLayout(layout)
    
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
        account = row_data.get('account', '')
        index = self.account_combo.findText(account)
        if index >= 0:
            self.account_combo.setCurrentIndex(index)
        else:
            self.account_combo.setCurrentText(account)
    
    def get_data(self):
        return {
            'preset_path': self.preset_edit.text(),
            'workflow_path': self.workflow_edit.text(),
            'account': self.account_combo.currentText()
        }


class BulkGenerationApp(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.generation_worker = None
        self.setup_ui()
        self.setup_connections()
        
    def setup_ui(self):
        self.setWindowTitle("Bulk Generation Manager")
        self.setGeometry(100, 100, 1200, 800)
        
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
        splitter.setSizes([700, 500])
    
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
        self.settings_table.setColumnCount(5)
        self.settings_table.setHorizontalHeaderLabels(["Preset File", "Workflow File", "Account", "Status", "Progress"])
        
        # Make table fill the width
        header = self.settings_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        
        self.settings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
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
        
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setMaximumHeight(300)
        layout.addWidget(self.logs_text)
        
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
    
    def add_row(self):
        """Add a new row to the settings table"""
        dialog = SettingsDialog(self)
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
        
        dialog = SettingsDialog(self, row_data)
        if dialog.exec_() == QDialog.Accepted:
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
            'preset_path': self.settings_table.item(row, 0).text() if self.settings_table.item(row, 0) else '',
            'workflow_path': self.settings_table.item(row, 1).text() if self.settings_table.item(row, 1) else '',
            'account': self.settings_table.item(row, 2).text() if self.settings_table.item(row, 2) else '',
            'status': self.settings_table.item(row, 3).text() if self.settings_table.item(row, 3) else 'Ready',
            'progress': self.settings_table.item(row, 4).text() if self.settings_table.item(row, 4) else '0%'
        }
    
    def add_table_row(self, data):
        """Add data to a new table row"""
        row = self.settings_table.rowCount()
        self.settings_table.insertRow(row)
        self.update_table_row(row, data)
    
    def update_table_row(self, row, data):
        """Update a table row with data"""
        self.settings_table.setItem(row, 0, QTableWidgetItem(data['preset_path']))
        self.settings_table.setItem(row, 1, QTableWidgetItem(data['workflow_path']))
        self.settings_table.setItem(row, 2, QTableWidgetItem(data['account']))
        
        # Set status and progress if not provided
        status = data.get('status', 'Ready')
        progress = data.get('progress', '0%')
        self.settings_table.setItem(row, 3, QTableWidgetItem(status))
        self.settings_table.setItem(row, 4, QTableWidgetItem(progress))
        
        # Make status and progress columns read-only
        if self.settings_table.item(row, 3):
            self.settings_table.item(row, 3).setFlags(self.settings_table.item(row, 3).flags() & ~Qt.ItemIsEditable)
        if self.settings_table.item(row, 4):
            self.settings_table.item(row, 4).setFlags(self.settings_table.item(row, 4).flags() & ~Qt.ItemIsEditable)
        
        # Color-code based on validation
        self.validate_and_color_row(row, data)
    
    def validate_and_color_row(self, row, data):
        """Validate row data and color-code accordingly"""
        is_valid = True
        
        # Validate preset file
        if not data['preset_path'] or not os.path.exists(data['preset_path']):
            self.settings_table.item(row, 0).setBackground(QColor(255, 200, 200))
            is_valid = False
        else:
            # Dummy content validation for preset
            if not self.validate_preset_content(data['preset_path']):
                self.settings_table.item(row, 0).setBackground(QColor(255, 255, 200))
                is_valid = False
            else:
                self.settings_table.item(row, 0).setBackground(QColor(200, 255, 200))
        
        # Validate workflow file
        if not data['workflow_path'] or not os.path.exists(data['workflow_path']):
            self.settings_table.item(row, 1).setBackground(QColor(255, 200, 200))
            is_valid = False
        else:
            # Dummy content validation for workflow
            if not self.validate_workflow_content(data['workflow_path']):
                self.settings_table.item(row, 1).setBackground(QColor(255, 255, 200))
                is_valid = False
            else:
                self.settings_table.item(row, 1).setBackground(QColor(200, 255, 200))
        
        # Validate account
        if not data['account']:
            self.settings_table.item(row, 2).setBackground(QColor(255, 200, 200))
            is_valid = False
        else:
            self.settings_table.item(row, 2).setBackground(QColor(200, 255, 200))
        
        return is_valid
    
    def update_row_status(self, row, status, progress=None):
        """Update the status and progress of a specific row"""
        if row < self.settings_table.rowCount():
            # Update status
            status_item = QTableWidgetItem(status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.settings_table.setItem(row, 3, status_item)
            
            # Update progress if provided
            if progress is not None:
                progress_text = f"{progress}%" if isinstance(progress, int) else str(progress)
                progress_item = QTableWidgetItem(progress_text)
                progress_item.setFlags(progress_item.flags() & ~Qt.ItemIsEditable)
                self.settings_table.setItem(row, 4, progress_item)
            
            # Color code based on status
            if status == "Completed":
                self.settings_table.item(row, 3).setBackground(QColor(200, 255, 200))
                self.settings_table.item(row, 4).setBackground(QColor(200, 255, 200))
            elif status == "Processing":
                self.settings_table.item(row, 3).setBackground(QColor(255, 255, 200))
                self.settings_table.item(row, 4).setBackground(QColor(255, 255, 200))
            elif status in ["Error", "Error (Validation)"]:
                self.settings_table.item(row, 3).setBackground(QColor(255, 200, 200))
                self.settings_table.item(row, 4).setBackground(QColor(255, 200, 200))
            elif status == "Validating":
                self.settings_table.item(row, 3).setBackground(QColor(200, 200, 255))
                self.settings_table.item(row, 4).setBackground(QColor(200, 200, 255))
    
    def validate_preset_content(self, file_path):
        """Dummy preset content validation - replace with actual logic"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            # TODO: Add your actual preset validation logic here
            # For now, just check if it's valid JSON
            return isinstance(data, dict)
        except:
            return False
    
    def validate_workflow_content(self, file_path):
        """Dummy workflow content validation - replace with actual logic"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            # TODO: Add your actual workflow validation logic here
            # For now, just check if it's valid JSON
            return isinstance(data, dict)
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
            
            # Clear existing data
            self.settings_table.setRowCount(0)
            
            # Load data into table
            for _, row in df.iterrows():
                data = {
                    'preset_path': str(row.get('preset_path', '')),
                    'workflow_path': str(row.get('workflow_path', '')),
                    'account': str(row.get('account', '')),
                    'status': 'Ready',
                    'progress': '0%'
                }
                self.add_table_row(data)
            
            self.log_message(f"Successfully loaded {len(df)} rows from {file_path}")
            
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
                    'preset_path': row_data['preset_path'],
                    'workflow_path': row_data['workflow_path'],
                    'account': row_data['account']
                })
            
            df = pd.DataFrame(data)
            
            if file_path.endswith('.xlsx'):
                df.to_excel(file_path, index=False)
            else:
                df.to_csv(file_path, index=False)
            
            self.log_message(f"Successfully saved {len(data)} rows to {file_path}")
            
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
        self.log_message(f"Started bulk generation for {len(generation_data)} items")
    
    def cancel_generation(self):
        """Cancel the ongoing generation"""
        if hasattr(self, 'bulk_generation_worker') and self.bulk_generation_worker and self.bulk_generation_worker.isRunning():
            self.bulk_generation_worker.cancel()
            self.log_message("Cancellation requested...")
    
    def update_progress(self, value):
        """Update the progress bar"""
        self.progress_bar.setValue(value)
    
    def update_status(self, message):
        """Update the status label and log"""
        self.status_label.setText(message)
        self.log_message(message)
    
    def generation_finished(self, message):
        """Handle generation completion"""
        self.log_message(f"Generation finished: {message}")
        self.status_label.setText("Generation completed")
        self.reset_generation_ui()
    
    def generation_error(self, error_message):
        """Handle generation error"""
        self.log_message(f"Error: {error_message}")
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
    
    def log_message(self, message):
        """Add message to logs"""
        timestamp = time.strftime("%H:%M:%S")
        self.logs_text.append(f"[{timestamp}] {message}")
        # Auto-scroll to bottom
        self.logs_text.moveCursor(self.logs_text.textCursor().End)


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
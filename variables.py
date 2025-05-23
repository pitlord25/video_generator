from PyQt5.QtWidgets import (QPushButton, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QTableWidget,
                           QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,QFrame)
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QFont, QColor

class VariableDialog(QDialog):
    """Dialog to manage variables with their multi-line text values"""
    
    # Signal to emit when variables are saved
    variables_saved = pyqtSignal(dict)
    
    def __init__(self, variables=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Variable Manager")
        self.resize(1280, 720)
        
        # Define default non-editable variables
        self.default_variables = {
            "title": "Title of the video",
            "intro": "Scripts generated by intro prompt"
        }
        
        self.setStyleSheet("""
            QPushButton {
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                background-color: #353535;
                color: white;
                border: 1px solid #2a82da;
            }
            QPushButton:hover {
                background-color: #2a82da;
                color: black;
            }

            QTableWidget {
                border: 1px solid #444444;
                border-radius: 4px;
                background-color: #191919;
                alternate-background-color: #353535;
                gridline-color: #555555;
                color: white;
            }
            
            QTableWidget::item:disabled {
                color: #777777;
                background-color: #2b2b2b;
            }

            QHeaderView::section {
                background-color: #353535;
                padding: 6px;
                font-weight: bold;
                border: none;
                border-right: 1px solid #444444;
                border-bottom: 1px solid #444444;
                color: white;
            }

            QTextEdit, QLineEdit {
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 4px;
                background-color: #191919;
                color: white;
            }

            QFrame#line {
                background-color: #444444;
            }
        """)

        
        # Initialize with existing variables if provided
        self.variables = variables if variables is not None else {}
        
        # Add default variables if they don't exist
        for key, value in self.default_variables.items():
            if key not in self.variables:
                self.variables[key] = value
        
        # Track if an item is currently selected
        self.item_selected = False
        
        # Create layout and widgets
        self.setup_ui()
        
        # Fill the table with existing variables
        self.populate_table()
    
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Table section
        table_label = QLabel("Variables")
        table_label.setFont(QFont("Arial", 12, QFont.Bold))
        main_layout.addWidget(table_label)
        
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.clicked.connect(self.load_variable)
        self.table.viewport().installEventFilter(self)

        main_layout.addWidget(self.table)
        
        # Edit section
        edit_label = QLabel("Edit Variable")
        edit_label.setFont(QFont("Arial", 12, QFont.Bold))
        main_layout.addWidget(edit_label)
        
        # Name input
        name_layout = QHBoxLayout()
        name_label = QLabel("Name:")
        name_label.setMinimumWidth(60)
        self.name_edit = QLineEdit()
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_edit)
        main_layout.addLayout(name_layout)
        
        # Value input
        value_layout = QVBoxLayout()
        value_label = QLabel("Value:")
        self.value_edit = QTextEdit()
        value_layout.addWidget(value_label)
        value_layout.addWidget(self.value_edit)
        main_layout.addLayout(value_layout)
        
        # Control buttons for editing
        edit_buttons = QHBoxLayout()
        self.add_update_button = QPushButton("Add")  # Default to "Add"
        self.add_update_button.clicked.connect(self.add_update_variable)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_variable)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_form)
        
        edit_buttons.addWidget(self.add_update_button)
        edit_buttons.addWidget(self.delete_button)
        edit_buttons.addWidget(self.clear_button)
        edit_buttons.addStretch()
        main_layout.addLayout(edit_buttons)
        
        # Separator line
        line = QFrame()
        line.setObjectName("line")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setMinimumHeight(2)
        main_layout.addWidget(line)
        
        # Dialog buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.clicked.connect(self.reject)
        
        buttons_layout.addWidget(self.save_button)
        buttons_layout.addWidget(self.cancel_button)
        main_layout.addLayout(buttons_layout)
    
    def eventFilter(self, source, event):
        """Event filter to handle clicks in empty areas of the table"""
        if (source is self.table.viewport() and event.type() == event.MouseButtonPress):
            index = self.table.indexAt(event.pos())
            if not index.isValid():
                # Clicked in an empty area - clear selection
                self.table.clearSelection()
                self.clear_form()
                return True
        return super().eventFilter(source, event)

    def populate_table(self):
        """Fill the table with the current variables"""
        self.table.setRowCount(0)
        
        # First add default variables (at the top)
        for name, value in self.default_variables.items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(name)
            self.table.setItem(row, 0, name_item)
            
            # Display a preview of the value (first line)
            preview = self.variables[name].split('\n')[0]
            if len(self.variables[name].split('\n')) > 1 or len(preview) > 30:
                preview += "..."
            
            value_item = QTableWidgetItem(preview)
            self.table.setItem(row, 1, value_item)
        
        # Then add custom variables
        for name, value in self.variables.items():
            if name not in self.default_variables:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(name))
                
                # Display a preview of the value (first line)
                preview = value.split('\n')[0]
                if len(value.split('\n')) > 1 or len(preview) > 30:
                    preview += "..."
                self.table.setItem(row, 1, QTableWidgetItem(preview))
    
    def load_variable(self):
        """Load the selected variable into the edit form"""
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            name = self.table.item(selected_row, 0).text()
            
            # Check if it's a default variable (which shouldn't be editable)
            if name in self.default_variables:
                self.name_edit.setText(name)
                self.value_edit.setText(self.variables.get(name, ""))
                
                # Disable editing for default variables
                self.name_edit.setReadOnly(True)
                self.value_edit.setReadOnly(True)
                self.add_update_button.setEnabled(False)
                self.delete_button.setEnabled(False)
                
                # Still consider this as an item selection
                self.item_selected = True
                self.add_update_button.setText("Update")
            else:
                self.name_edit.setText(name)
                self.value_edit.setText(self.variables.get(name, ""))
                
                # Enable editing for custom variables
                self.name_edit.setReadOnly(False)
                self.value_edit.setReadOnly(False)
                self.add_update_button.setEnabled(True)
                self.delete_button.setEnabled(True)
                
                # Set item as selected and update button text
                self.item_selected = True
                self.add_update_button.setText("Update")
    
    def add_update_variable(self):
        """Add a new variable or update an existing one"""
        name = self.name_edit.text().strip()
        value = self.value_edit.toPlainText()
        
        if not name:
            QMessageBox.warning(self, "Error", "Variable name cannot be empty")
            return
        
        # Prevent adding/updating default variables
        if name in self.default_variables:
            QMessageBox.warning(self, "Error", f"Cannot modify default variable '{name}'")
            return
        
        if self.item_selected:
            # Update mode
            original_name = self.table.item(self.table.currentRow(), 0).text()
            
            if name != original_name and name in self.variables:
                # If trying to rename to an existing variable name
                response = QMessageBox.question(
                    self, 
                    "Variable Exists", 
                    f"Variable '{name}' already exists. Do you want to overwrite it?",
                    QMessageBox.Yes | QMessageBox.No, 
                    QMessageBox.No
                )
                
                if response != QMessageBox.Yes:
                    return
            
            # If the name changed, remove the old key
            if name != original_name:
                if original_name in self.variables:
                    del self.variables[original_name]
        else:
            # Add mode - check if variable exists
            if name in self.variables:
                response = QMessageBox.question(
                    self, 
                    "Variable Exists", 
                    f"Variable '{name}' already exists. Do you want to overwrite it?",
                    QMessageBox.Yes | QMessageBox.No, 
                    QMessageBox.No
                )
                
                if response != QMessageBox.Yes:
                    return
        
        # Update/add the variable
        self.variables[name] = value
        self.populate_table()
        self.clear_form()
    
    def delete_variable(self):
        """Delete the current variable"""
        name = self.name_edit.text().strip()
        
        # Prevent deleting default variables
        if name in self.default_variables:
            QMessageBox.warning(self, "Error", f"Cannot delete default variable '{name}'")
            return
        
        if name in self.variables:
            # Show confirmation dialog before deleting
            confirm = QMessageBox.question(
                self,
                "Confirm Deletion",
                f"Are you sure you want to delete the variable '{name}'?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No  # Default button is No for safety
            )
            
            if confirm == QMessageBox.Yes:
                del self.variables[name]
                self.populate_table()
                self.clear_form()
    
    def clear_form(self):
        """Clear the edit form"""
        self.name_edit.clear()
        self.value_edit.clear()
        
        # Reset form state
        self.name_edit.setReadOnly(False)
        self.value_edit.setReadOnly(False)
        self.add_update_button.setEnabled(True)
        self.add_update_button.setText("Add")  # Reset to Add mode
        self.delete_button.setEnabled(True)
        
        # Reset item selection status
        self.item_selected = False
        self.table.clearSelection()
    
    def accept(self):
        """Override accept to emit the signal with variables data"""
        # Create a new dictionary excluding default variables
        custom_variables = {name: value for name, value in self.variables.items() 
                           if name not in self.default_variables}
        
        # Emit only the custom variables
        self.variables_saved.emit(custom_variables)
        super().accept()
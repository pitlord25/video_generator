from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QScrollArea, QSizePolicy, QFrame)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QFont


class CollapsibleSection(QWidget):
    """
    A collapsible section widget with a header button that toggles content visibility.
    Contents are placed in a scroll area for better handling of large content.
    """
    
    # Signal emitted when section is expanded or collapsed
    toggled = pyqtSignal(bool)
    
    def __init__(self, title, parent=None):
        super().__init__(parent)
        
        self.is_expanded = True
        self.toggle_animation_finished = True
        
        # Create main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Create header button
        self.header_button = QPushButton(title)
        self.header_button.setCheckable(True)
        self.header_button.setChecked(True)
        self.header_button.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 8px;
                font-weight: bold;
                background-color: #e0e0e0;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
            QPushButton:checked {
                background-color: #c0c0c0;
            }
        """)
        
        # Set a larger font for the header
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.header_button.setFont(font)
        
        # Add arrow indicator
        self.update_header_text()
        
        # Create content area with scroll support
        self.content_area = QScrollArea()
        self.content_area.setWidgetResizable(True)
        self.content_area.setFrameShape(QFrame.NoFrame)
        self.content_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Create widget to hold the actual content
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(8, 8, 8, 8)
        self.content_area.setWidget(self.content_widget)
        
        # Add widgets to main layout
        self.main_layout.addWidget(self.header_button)
        self.main_layout.addWidget(self.content_area)
        
        # Connect the header button to toggle
        self.header_button.clicked.connect(self.toggle_section)
        
    def update_header_text(self):
        """Update the header button text with the appropriate arrow indicator"""
        title = self.header_button.text().replace('▼ ', '').replace('► ', '')
        if self.is_expanded:
            self.header_button.setText(f"▼ {title}")
        else:
            self.header_button.setText(f"► {title}")
            
    def toggle_section(self, checked=None):
        """Toggle the visibility of the content area"""
        if checked is None:
            self.is_expanded = not self.is_expanded
        else:
            self.is_expanded = checked
            
        self.content_area.setVisible(self.is_expanded)
        self.update_header_text()
        self.toggled.emit(self.is_expanded)
        
    def add_widget(self, widget):
        """Add a widget to the content area"""
        self.content_layout.addWidget(widget)
        
    def add_layout(self, layout):
        """Add a layout to the content area"""
        self.content_layout.addLayout(layout)
        
    def set_expanded(self, expanded):
        """Programmatically expand or collapse the section"""
        if self.is_expanded != expanded:
            self.toggle_section(expanded)
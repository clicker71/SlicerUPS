# EXAMPLE - minimal Qt widget over the SlicerUPS core.
# This file may import qt/slicer and may print. It is an example, not the core.

import qt

from slicer_ups_client import UPSClient, DicomwebClient


class SlicerUPSWidget(qt.QWidget):
    """Minimal panel: root URL + a Search button + a result list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = qt.QVBoxLayout(self)
        self.root_edit = qt.QLineEdit("http://localhost:8042/dicomweb")
        self.search_button = qt.QPushButton("Search workitems")
        self.list = qt.QListWidget()
        layout.addWidget(qt.QLabel("DICOMweb root"))
        layout.addWidget(self.root_edit)
        layout.addWidget(self.search_button)
        layout.addWidget(self.list)
        self.search_button.clicked.connect(self._on_search)

    def _on_search(self):
        client = UPSClient(DicomwebClient(self.root_edit.text))
        self.list.clear()
        for item in client.search({}):
            self.list.addItem(f"{item.uid} - {item.state}")

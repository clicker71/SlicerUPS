# hooks/

The core (`slicer_ups_client/`) is UI-agnostic: no `qt`, `slicer`, `vtk`.
UI lives here. Each file is a self-contained EXAMPLE - Qt, shortcuts and
`print` are all allowed in this folder, and each file is marked as such.

- `context_menu_example.py` - a Subject Hierarchy context-menu item that runs
  a workitem for the selected study.
- `qt_widget_example.py` - a minimal Qt widget over the core API.

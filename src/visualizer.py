"""
PyVista-based 3D visualizer for proofreading spine head center candidates.
"""

import numpy as np
import pandas as pd
import pyvista as pv
from pathlib import Path
from pyvistaqt import QtInteractor
from qtpy import QtWidgets, QtCore
from datetime import datetime

from . import radius
from . import payload


class FocusLineEdit(QtWidgets.QLineEdit):
    """Custom QLineEdit that emits signals on focus in/out."""

    focus_in = QtCore.Signal()
    focus_out = QtCore.Signal()

    def focusInEvent(self, event):
        """Override focus in event."""
        self.focus_in.emit()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        """Override focus out event."""
        self.focus_out.emit()
        super().focusOutEvent(event)


class SpineProofreadVisualizer:
    """Interactive 3D visualizer for proofreading spine head center candidates."""

    def __init__(self, mesh, points, output_path, psds=None, annotation=None,
                 original_head_centers=None, dsb_filepath=None,
                 initial_labels=None, initial_spine_names=None, initial_radii=None):
        """
        Initialize the visualizer.

        :param mesh: A trimesh.Trimesh object representing the 3D mesh.
        :param points: A numpy array of shape (N, 3) with candidate point coordinates.
        :param output_path: Path object for saving results.
        :param psds: Optional trimesh.Trimesh object representing PSDs.
        :param annotation: Optional list of tuples (point_array, name_str) for annotations.
        :param original_head_centers: Original head center positions (for reset functionality).
        :param dsb_filepath: Path to the DSB file for saving results.
        :param initial_labels: Optional list of initial labels for each point.
        :param initial_spine_names: Optional list of initial spine names.
        :param initial_radii: Optional list of initial radii for each point.
        """
        self.trimesh_mesh = mesh
        self.pv_mesh = pv.wrap(mesh)
        self.psds = pv.wrap(psds) if psds is not None else None
        self.annotation = annotation
        self.points = points
        self.original_points = original_head_centers if original_head_centers is not None else points.copy()
        self.output_path = output_path
        self.dsb_filepath = dsb_filepath

        # State management
        self.current_index = 0
        self.num_points = len(self.points)
        self.labels = initial_labels if initial_labels is not None else ['unlabeled'] * self.num_points

        # Auto-generate spine names based on closest annotation or use provided names
        if initial_spine_names is not None:
            self.spine_names = initial_spine_names
        else:
            self.spine_names = self._generate_spine_names()

        # Visualization objects
        self.plotter = None
        self.head_center_actors = []
        self.radius_indicator_actor = None  # Placeholder
        self.head_radii: list[float | None] = initial_radii if initial_radii is not None else [None] * self.num_points
        self.annotation_actors = []  # Store annotation point actors
        self.annotation_label_actors = []  # Store annotation label actors

        # GUI components
        self.text_input = None
        self.text_input_active = False
        self.main_window = None
        self.close_labels_only = True  # Show only close labels by default
        self.last_saved_time = None  # Track last save time
        self.has_unsaved_changes = False  # Track unsaved changes
        self.last_saved_label = None  # Label to display last saved time
        self.spine_index_input = None  # Line edit for spine index navigation
        self.spine_index_go_button = None  # Go button for spine index navigation

        # Visual settings
        self.sphere_radius = 40

    def _generate_spine_names(self):
        """
        Generate spine names based on closest annotation within 5000 units.
        Falls back to "Spine number [idx]" if no annotation is close enough.

        :return: List of spine names
        """
        names = []

        for i, point in enumerate(self.points):
            name = f"Spine number {i}"  # Default name

            if self.annotation is not None and len(self.annotation) > 0:
                # Find the closest annotation
                min_distance = float('inf')
                closest_annotation_name = None

                for annotation_point, annotation_name in self.annotation:
                    distance = np.linalg.norm(point - annotation_point)
                    if distance < min_distance:
                        min_distance = distance
                        closest_annotation_name = annotation_name

                if min_distance < 3000:
                    name = closest_annotation_name

            names.append(name)

        return names

    def get_sphere_color(self, index):
        """Get color for sphere based on its label and if it's current."""
        label = self.labels[index]

        if label == "accepted":
            return "green"

        if label == "rejected":
            return "red"

        if index == self.current_index:
            return (188/255, 9/255, 188/255)

        return "gray"

    def update_sphere_color(self, index):
        """Update the color of a sphere based on its label."""
        if self.plotter is None:
            return

        color = self.get_sphere_color(index)
        self.plotter.remove_actor(self.head_center_actors[index])

        sphere = pv.Sphere(radius=self.sphere_radius, center=self.points[index])
        self.head_center_actors[index] = self.plotter.add_mesh(sphere, color=color, opacity=1.0)

        self._update_radius_indicator()

    def get_radius_for_point(self, index) -> float:
        if self.head_radii[index] is None:
            self.head_radii[index] = radius.get_radius_point(
                self.points[index], self.trimesh_mesh, n_rays=200
            )

        return self.head_radii[index]

    def _update_radius_indicator(self):
        """Update radius indicator to show for this point."""
        head_radius = self.get_radius_for_point(self.current_index)

        radius_sphere = pv.Sphere(
            radius=head_radius,
            center=self.points[self.current_index],
        )

        if self.radius_indicator_actor is not None:
            self.plotter.remove_actor(self.radius_indicator_actor)

        self.radius_indicator_actor = self.plotter.add_mesh(
            radius_sphere,
            color=(188/255, 9/255, 188/255),
            opacity=60/255,
        )

    def update_info_text(self):
        """Update the information text display."""
        label = self.labels[self.current_index]

        # Get current radius (compute if not available yet)
        current_radius = self.get_radius_for_point(self.current_index)

        radius_text = f"{current_radius:.2f} nm"

        info_text = (
            f""
        )

        self.plotter.add_text(
            info_text,
            position='upper_left',
            font_size=10,
            name='info_text'
        )

    def focus_on_current_sphere(self, move_camera=True):
        """Focus on the current sphere."""
        if self.plotter is None:
            return

        self.update_info_text()

        if move_camera:
            point = self.points[self.current_index]
            self.plotter.camera.focal_point = point

            distance = np.linalg.norm(self.pv_mesh.bounds[1] - self.pv_mesh.bounds[0]) * 0.5
            self.plotter.camera.position = point + np.array([0, -distance, distance * 0.5])
            self.plotter.camera.view_up = [0, 0, 1]

        self.plotter.render()

    def go_to_sphere(self, index):
        """
        Navigate to a specific sphere by index.

        :param index: The index of the sphere to navigate to. If out of bounds, it will wrap around using modulo.
        """

        self.current_index = index
        self.update_sphere_color(self.current_index)
        self.text_input.setText(self.spine_names[self.current_index])
        self.update_spine_index_input()
        self.update_annotation_label_visibility()
        self.focus_on_current_sphere()

    def mark_accepted(self):
        """Mark current point as accepted."""
        self.labels[self.current_index] = 'accepted'
        self.has_unsaved_changes = True
        self.update_sphere_color(self.current_index)
        self.focus_on_current_sphere(move_camera=False)

    def mark_rejected(self):
        """Mark current point as rejected."""
        self.labels[self.current_index] = 'rejected'
        self.has_unsaved_changes = True
        self.update_sphere_color(self.current_index)
        self.focus_on_current_sphere(move_camera=False)

    def reset_to_original(self):
        """Reset current point to its original position."""
        self.points[self.current_index] = self.original_points[self.current_index].copy()

        # Update visualization
        self.has_unsaved_changes = True
        self.update_sphere_color(self.current_index)
        self._update_radius_indicator()

        self.focus_on_current_sphere(move_camera=False)

    def save_results(self):
        """Save labeled points to CSV file and to DSB file with timestamp."""
        # Compute any missing head radii
        for i in range(self.num_points):
            self.get_radius_for_point(i)  # Getting radius also computes and stores it if not already done

        output_data = {
            'Index': np.arange(self.num_points),
            'Name': self.spine_names,
            'Radius': self.head_radii,
            'PosX': self.points[:, 0],
            'PosY': self.points[:, 1],
            'PosZ': self.points[:, 2],
            'status': self.labels
        }
        output_df = pd.DataFrame(output_data)

        # Save to regular CSV file (legacy behavior)
        output_df.to_csv(self.output_path, index=False)
        print(f"\nResults saved to: {self.output_path}")

        # Save to DSB file with timestamp
        if self.dsb_filepath is not None:
            base_filename = Path(self.dsb_filepath).stem + "_proofread"
            csv_filename = payload.save_csv_to_dsb(self.dsb_filepath, output_df, base_filename)
            print(f"Results also saved to DSB file as: {csv_filename}")
        else:
            print("Warning: DSB filepath not provided, skipping DSB save.")

        # Update save tracking
        self.last_saved_time = datetime.now()
        self.has_unsaved_changes = False
        self.update_last_saved_label()

    def bump(self, offset):
        """
        Move the current point based on camera orientation.

        :param offset: A 3D vector indicating where to move along. Where +z = forward, +y = up
        """
        camera_pos = np.array(self.plotter.camera.position)
        camera_fp = np.array(self.plotter.camera.focal_point)
        direction = camera_fp - camera_pos

        # Calculate the step based on camera orientation
        direction = direction / np.linalg.norm(direction)
        up = np.array(self.plotter.camera.GetViewUp())
        right = np.cross(direction, up)
        right = right / np.linalg.norm(right)
        up = np.cross(right, direction)
        up = up / np.linalg.norm(up)

        step = offset[0] * right + offset[1] * up + offset[2] * direction
        self.points[self.current_index] += step

        # Update visualization
        self.has_unsaved_changes = True
        self.update_sphere_color(self.current_index)
        self._update_radius_indicator()

        self.focus_on_current_sphere(move_camera=False)

    def update_last_saved_label(self):
        """Update the last saved time label."""
        if self.last_saved_label is not None and self.last_saved_time is not None:
            time_str = self.last_saved_time.strftime("%Y-%m-%d %H:%M:%S")
            self.last_saved_label.setText(f"Last saved: {time_str}")

    def update_spine_index_input(self):
        """Update the spine index input to show the current index."""
        if self.spine_index_input is not None:
            # Block signals to prevent triggering validation during programmatic update
            self.spine_index_input.blockSignals(True)
            self.spine_index_input.setText(str(self.current_index + 1))  # Display 1-indexed
            self.spine_index_input.blockSignals(False)
            self.validate_spine_index_input()

    def validate_spine_index_input(self):
        """Validate spine index input and enable/disable go button accordingly."""
        if self.spine_index_input is None or self.spine_index_go_button is None:
            return

        text = self.spine_index_input.text()

        # Check if text is a valid number
        try:
            index = int(text)
            # Check if index is in valid range (1-indexed for user)
            if 1 <= index <= self.num_points:
                # Enable button only if it's different from current index
                if index - 1 != self.current_index:
                    self.spine_index_go_button.setEnabled(True)
                else:
                    self.spine_index_go_button.setEnabled(False)
            else:
                # Out of range
                self.spine_index_go_button.setEnabled(False)
        except ValueError:
            # Not a valid number
            self.spine_index_go_button.setEnabled(False)

    def on_spine_index_go_clicked(self):
        """Handle clicking the Go button to navigate to a specific spine index."""
        # Only proceed if the button is enabled
        if not self.spine_index_go_button.isEnabled():
            return

        try:
            index = int(self.spine_index_input.text()) - 1  # Convert to 0-indexed
            if 0 <= index < self.num_points:
                self.go_to_sphere(index)
        except ValueError:
            pass  # Should not happen due to validation, but just in case

    def closeEvent(self, event):
        """Handle window close event - prompt to save if there are unsaved changes."""
        if self.has_unsaved_changes:
            reply = QtWidgets.QMessageBox.question(
                self.main_window,
                'Unsaved Changes',
                'You have unsaved changes. Do you want to save before closing?',
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Save
            )

            if reply == QtWidgets.QMessageBox.Save:
                self.save_results()
                event.accept()
            elif reply == QtWidgets.QMessageBox.Discard:
                event.accept()
            else:  # Cancel
                event.ignore()
        else:
            event.accept()

    def setup_key_callbacks(self):
        """Setup keyboard event handlers for movement controls only."""
        # Clear default wireframe toggle
        self.plotter.clear_events_for_key("w")
        self.plotter.clear_events_for_key("W")

        # Wrapper function to check if text input is active
        def create_callback(func):
            def wrapper():
                if not self.text_input_active:
                    func()
            return wrapper


        # Reset to original position
        self.plotter.iren.add_key_event('h', create_callback(self.reset_to_original))
        self.plotter.iren.add_key_event('H', create_callback(self.reset_to_original))

        # Movement controls
        self.plotter.iren.add_key_event('i', create_callback(lambda: self.bump(np.array([0, 0, 15]))))
        self.plotter.iren.add_key_event('I', create_callback(lambda: self.bump(np.array([0, 0, 65]))))
        self.plotter.iren.add_key_event('k', create_callback(lambda: self.bump(np.array([0, 0, -15]))))
        self.plotter.iren.add_key_event('K', create_callback(lambda: self.bump(np.array([0, 0, -65]))))
        self.plotter.iren.add_key_event('j', create_callback(lambda: self.bump(np.array([-15, 0, 0]))))
        self.plotter.iren.add_key_event('J', create_callback(lambda: self.bump(np.array([-65, 0, 0]))))
        self.plotter.iren.add_key_event('l', create_callback(lambda: self.bump(np.array([15, 0, 0]))))
        self.plotter.iren.add_key_event('L', create_callback(lambda: self.bump(np.array([65, 0, 0]))))
        self.plotter.iren.add_key_event('u', create_callback(lambda: self.bump(np.array([0, -15, 0]))))
        self.plotter.iren.add_key_event('U', create_callback(lambda: self.bump(np.array([0, -65, 0]))))
        self.plotter.iren.add_key_event('o', create_callback(lambda: self.bump(np.array([0, 15, 0]))))
        self.plotter.iren.add_key_event('O', create_callback(lambda: self.bump(np.array([0, 65, 0]))))

    def initialize_scene(self):
        """Initialize the 3D scene with mesh and points."""
        # Add mesh
        self.plotter.add_mesh(self.pv_mesh, opacity=0.5, color='white')

        # Add PSDs mesh if available (desaturated orange with 80% opacity)
        if self.psds is not None:
            self.plotter.add_mesh(self.psds, opacity=0.8, color='#D4A574')

        # Add all points as spheres
        for i, point in enumerate(self.points):
            color = self.get_sphere_color(i)
            sphere = pv.Sphere(radius=self.sphere_radius, center=point)
            actor = self.plotter.add_mesh(sphere, color=color, opacity=1.0)
            self.head_center_actors.append(actor)

        # Show radius indicator for the first point
        self.update_sphere_color(self.current_index)

        # Add annotation points and labels if available
        if self.annotation is not None:
            for annotation_point, annotation_name in self.annotation:
                # Add small sphere for annotation point (yellow/gold color)
                annotation_sphere = pv.Sphere(radius=self.sphere_radius * 0.5, center=annotation_point)
                annotation_actor = self.plotter.add_mesh(
                    annotation_sphere,
                    color='gold',
                    opacity=0.9
                )
                self.annotation_actors.append(annotation_actor)

                # Add billboarded text label that always faces the camera
                label_actor = self.plotter.add_point_labels(
                    [annotation_point],
                    [annotation_name],
                    font_size=14,
                    text_color='white',
                    point_color='gold',
                    point_size=0,  # Don't show the point itself (we have the sphere)
                    render_points_as_spheres=False,
                    always_visible=True,
                    shape_opacity=0.7,
                    fill_shape=True,
                    shape_color='black'
                )
                self.annotation_label_actors.append(label_actor)

        self.update_annotation_label_visibility()

    def on_text_focus_in(self):
        """Called when text input gains focus."""
        self.text_input_active = True

    def on_text_focus_out(self):
        """Called when text input loses focus."""
        self.text_input_active = False

    def on_text_changed(self, text):
        """Called when text input changes."""
        self.spine_names[self.current_index] = text
        self.has_unsaved_changes = True

    def update_annotation_label_visibility(self):
        """Update visibility of annotation labels based on distance to current point."""
        if self.annotation is None or not self.annotation_label_actors:
            return

        current_point = self.points[self.current_index]

        for i, (annotation_point, annotation_name) in enumerate(self.annotation):
            distance = np.linalg.norm(current_point - annotation_point)

            if self.close_labels_only:
                if distance < 6000:
                    self.annotation_label_actors[i].SetVisibility(True)
                else:
                    self.annotation_label_actors[i].SetVisibility(False)
            else:
                # Show all labels
                self.annotation_label_actors[i].SetVisibility(True)

        self.plotter.render()

    def toggle_close_labels_only(self, checked):
        """Toggle between showing all labels or only close labels."""
        self.close_labels_only = checked
        self.update_annotation_label_visibility()

    def create_toolbar(self):
        """Create toolbar with main action buttons."""
        toolbar = QtWidgets.QToolBar("Main Toolbar")
        toolbar.setMovable(False)

        # Save button
        save_action = QtWidgets.QAction("💾 Save", self.main_window)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_results)
        toolbar.addAction(save_action)

        toolbar.addSeparator()

        # Previous button
        prev_action = QtWidgets.QAction("⬅ Previous", self.main_window)
        prev_action.setShortcut("Left")
        prev_action.triggered.connect(lambda: self.go_to_sphere(self.current_index - 1))
        toolbar.addAction(prev_action)

        # Next button
        next_action = QtWidgets.QAction("➡ Next", self.main_window)
        next_action.setShortcut("Right")
        next_action.triggered.connect(lambda: self.go_to_sphere(self.current_index + 1))
        toolbar.addAction(next_action)

        toolbar.addSeparator()

        # Accept button
        accept_action = QtWidgets.QAction("✓ Accept", self.main_window)
        accept_action.setShortcut("M")
        accept_action.triggered.connect(self.mark_accepted)
        toolbar.addAction(accept_action)

        # Reject button
        reject_action = QtWidgets.QAction("✗ Reject", self.main_window)
        reject_action.setShortcut("N")
        reject_action.triggered.connect(self.mark_rejected)
        toolbar.addAction(reject_action)

        toolbar.addSeparator()

        # Close labels only toggle button
        close_labels_action = QtWidgets.QAction("🏷️ Close labels only", self.main_window)
        close_labels_action.setCheckable(True)
        close_labels_action.setChecked(True)  # Checked by default
        close_labels_action.toggled.connect(self.toggle_close_labels_only)
        toolbar.addAction(close_labels_action)

        return toolbar

    def setup_qt_shortcuts(self):
        """Setup Qt keyboard shortcuts for main window."""
        # Create shortcuts that work even when text input has focus
        # Note: shortcuts on toolbar actions handle most cases
        # These are additional shortcuts that need special handling
        pass

    def run(self):
        """Run the interactive visualization."""
        # Create Qt application
        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([])

        # Create main window
        self.main_window = QtWidgets.QMainWindow()
        self.main_window.setWindowTitle("Spine Proofreading Tool")

        # Override close event to prompt for unsaved changes
        self.main_window.closeEvent = self.closeEvent

        # Add toolbar
        toolbar = self.create_toolbar()
        self.main_window.addToolBar(toolbar)

        # Create central widget and layout
        central_widget = QtWidgets.QWidget()
        self.main_window.setCentralWidget(central_widget)
        layout = QtWidgets.QVBoxLayout()
        central_widget.setLayout(layout)

        # Create PyVista plotter using QtInteractor
        self.plotter = QtInteractor(central_widget)
        layout.addWidget(self.plotter.interactor)

        # Create text input at the bottom
        text_layout = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel("Spine Name:")
        self.text_input = FocusLineEdit()
        self.text_input.setPlaceholderText("Enter spine name here...")

        # Connect focus events using signals
        self.text_input.focus_in.connect(self.on_text_focus_in)
        self.text_input.focus_out.connect(self.on_text_focus_out)

        # Connect text changed event
        self.text_input.textChanged.connect(self.on_text_changed)

        text_layout.addWidget(label)
        text_layout.addWidget(self.text_input)
        layout.addLayout(text_layout)

        # Create spine index navigation layout
        spine_nav_layout = QtWidgets.QHBoxLayout()
        spine_nav_label = QtWidgets.QLabel("Spine Index:")
        self.spine_index_input = QtWidgets.QLineEdit()
        self.spine_index_input.setMaximumWidth(80)
        self.spine_index_input.setText("1")
        self.spine_index_input.setPlaceholderText("Index")

        # Connect text changed event for validation
        self.spine_index_input.textChanged.connect(lambda: self.validate_spine_index_input())

        # Connect Enter key to trigger Go button (only when enabled)
        self.spine_index_input.returnPressed.connect(self.on_spine_index_go_clicked)

        spine_total_label = QtWidgets.QLabel(f"/ {self.num_points}")

        self.spine_index_go_button = QtWidgets.QPushButton("Go")
        self.spine_index_go_button.setEnabled(False)  # Initially disabled
        self.spine_index_go_button.clicked.connect(self.on_spine_index_go_clicked)

        spine_nav_layout.addWidget(spine_nav_label)
        spine_nav_layout.addWidget(self.spine_index_input)
        spine_nav_layout.addWidget(spine_total_label)
        spine_nav_layout.addWidget(self.spine_index_go_button)

        # Add stretch to push everything to the left
        spine_nav_layout.addStretch()

        # Add last saved label on the right
        self.last_saved_label = QtWidgets.QLabel("Not saved yet")
        spine_nav_layout.addWidget(self.last_saved_label)

        layout.addLayout(spine_nav_layout)

        # Add loading text
        self.plotter.add_text("Loading...", position='upper_left', font_size=10, name='info_text')

        # Initialize scene and callbacks
        self.initialize_scene()
        self.setup_key_callbacks()
        self.setup_qt_shortcuts()

        # Set initial spine name in text input
        self.text_input.setText(self.spine_names[self.current_index])

        self.plotter.reset_camera()
        self.focus_on_current_sphere()

        # Show the window
        self.main_window.resize(1024, 768)
        self.main_window.show()

        # Start the Qt event loop
        app.exec_()

import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QSpinBox, QDoubleSpinBox, 
                           QTextEdit, QPushButton, QFileDialog, QScrollArea,
                           QFrame, QCheckBox, QComboBox, QColorDialog, QGroupBox,
                           QGridLayout)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from datetime import datetime
import json

class SignalPresets:
    """Predefined signal presets"""
    PRESETS = {
        "Low Frequency": {"amplitude": 5.0, "delay": 0, "frequency": 100, "damping": 0.1},
        "High Frequency": {"amplitude": 2.0, "delay": 0, "frequency": 5000, "damping": 0.05},
        "Long Decay": {"amplitude": 10.0, "delay": 0, "frequency": 1000, "damping": 0.01},
        "Quick Decay": {"amplitude": 8.0, "delay": 0, "frequency": 2000, "damping": 0.5},
    }

class ResistanceCalculator(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Resistance Calculator", parent)
        layout = QVBoxLayout(self)

        # Input widgets
        input_widget = QWidget()
        input_layout = QGridLayout(input_widget)

        # Rx input
        input_layout.addWidget(QLabel("Rx (Ω):"), 0, 0)
        self.rx_input = QDoubleSpinBox()
        self.rx_input.setRange(0.1, 1000000)
        self.rx_input.setValue(1000)
        self.rx_input.setSingleStep(100)
        input_layout.addWidget(self.rx_input, 0, 1)

        # Vcc input
        input_layout.addWidget(QLabel("Vcc (V):"), 1, 0)
        self.vcc_input = QDoubleSpinBox()
        self.vcc_input.setRange(0.1, 100)
        self.vcc_input.setValue(5)
        self.vcc_input.setSingleStep(0.1)
        input_layout.addWidget(self.vcc_input, 1, 1)

        # Voltage inputs
        input_layout.addWidget(QLabel("Vh (V):"), 2, 0)
        self.vh_input = QDoubleSpinBox()
        self.vh_input.setRange(0, 100)
        self.vh_input.setValue(3.3)
        self.vh_input.setSingleStep(0.1)
        input_layout.addWidget(self.vh_input, 2, 1)

        input_layout.addWidget(QLabel("Vl (V):"), 3, 0)
        self.vl_input = QDoubleSpinBox()
        self.vl_input.setRange(0, 100)
        self.vl_input.setValue(1.7)
        self.vl_input.setSingleStep(0.1)
        input_layout.addWidget(self.vl_input, 3, 1)

        layout.addWidget(input_widget)

        # Results display
        results_group = QGroupBox("Calculated Values")
        results_layout = QVBoxLayout(results_group)
        
        self.rh_label = QLabel("Rh: -- Ω")
        self.ry_label = QLabel("Ry: -- Ω")
        results_layout.addWidget(self.rh_label)
        results_layout.addWidget(self.ry_label)
        
        layout.addWidget(results_group)

        # Calculate button
        calc_button = QPushButton("Calculate")
        calc_button.clicked.connect(self.calculate)
        layout.addWidget(calc_button)

        # Connect value changed signals
        for input_widget in [self.rx_input, self.vcc_input, self.vh_input, self.vl_input]:
            input_widget.valueChanged.connect(self.calculate)

    def calculate(self):
        try:
            rx = self.rx_input.value()
            vcc = self.vcc_input.value()
            vh = self.vh_input.value()
            vl = self.vl_input.value()

            # Calculate ratios
            rh_ratio = vl / (vh - vl)
            ry_ratio = vl / (vcc - vh)

            # Calculate actual values
            rh = rx * rh_ratio
            ry = rx * ry_ratio

            # Update labels
            self.rh_label.setText(f"Rh: {rh:.2f} Ω")
            self.ry_label.setText(f"Ry: {ry:.2f} Ω")
        except ZeroDivisionError:
            self.rh_label.setText("Rh: Invalid input")
            self.ry_label.setText("Ry: Invalid input")

class SignalControls(QFrame):
    def __init__(self, parent=None, index=0):
        super().__init__(parent)
        self.parent = parent
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.layout = QVBoxLayout(self)
        
        # Header with signal number, visibility, and remove button
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.visible_check = QCheckBox()
        self.visible_check.setChecked(True)
        self.visible_check.stateChanged.connect(parent.update_plot)
        header_layout.addWidget(self.visible_check)
        
        self.signal_label = QLabel(f"Signal {index + 1}")
        header_layout.addWidget(self.signal_label)
        
        # Color picker button
        self.color_button = QPushButton()
        self.color_button.setFixedSize(20, 20)
        self.signal_color = self.get_default_color(index)
        self.update_color_button()
        self.color_button.clicked.connect(self.choose_color)
        header_layout.addWidget(self.color_button)
        
        # Preset selector
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Custom"] + list(SignalPresets.PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self.apply_preset)
        header_layout.addWidget(self.preset_combo)
        
        preview_button = QPushButton("Preview")
        preview_button.clicked.connect(self.preview_signal)
        header_layout.addWidget(preview_button)
        
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(lambda: parent.remove_signal(self))
        header_layout.addWidget(remove_button)
        
        self.layout.addWidget(header)

        # Controls
        params = [
            ("Amplitude (V)", 0, 250, index * 5, 0.1),
            ("Delay (ms)", 0, 1000, index * 30, 0.1),
            ("Frequency (Hz)", 1, 10000, 1000, 1),
            ("Damping ratio", 0.01, 0.99, 0.1, 0.01)
        ]

        self.controls = {}
        for label, min_val, max_val, default, step in params:
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            
            label_widget = QLabel(f"{label}:")
            spin = QDoubleSpinBox()
            spin.setRange(min_val, max_val)
            spin.setValue(default)
            spin.setSingleStep(step)
            
            layout.addWidget(label_widget)
            layout.addWidget(spin)
            
            self.layout.addWidget(widget)
            self.controls[label.split()[0].lower()] = spin
            
            spin.valueChanged.connect(self.on_value_changed)

    def get_default_color(self, index):
        """Generate a default color based on index"""
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', 
                 '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']
        return QColor(colors[index % len(colors)])

    def update_color_button(self):
        """Update color button appearance"""
        self.color_button.setStyleSheet(
            f"background-color: {self.signal_color.name()}; border: 1px solid black;")

    def choose_color(self):
        """Open color picker dialog"""
        color = QColorDialog.getColor(self.signal_color, self)
        if color.isValid():
            self.signal_color = color
            self.update_color_button()
            self.parent.update_plot()

    def on_value_changed(self):
        """Handle value changes and update preset selector"""
        self.preset_combo.setCurrentText("Custom")
        self.parent.update_plot()

    def apply_preset(self, preset_name):
        """Apply selected preset values"""
        if preset_name != "Custom":
            values = SignalPresets.PRESETS[preset_name]
            for key, value in values.items():
                self.controls[key].setValue(value)

    def preview_signal(self):
        """Show preview of individual signal"""
        self.parent.preview_signal(self)

    def get_values(self):
        """Get current values of all controls"""
        return {key: spin.value() for key, spin in self.controls.items()}

    def is_visible(self):
        """Check if signal is visible"""
        return self.visible_check.isChecked()

class PiezoGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Piezoelectric Signal Generator")
        self.setGeometry(100, 100, 1600, 800)
        self.manual_zoom = False
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Create left panel for controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # Add scroll area for signals
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.signals_widget = QWidget()
        self.signals_layout = QVBoxLayout(self.signals_widget)
        scroll.setWidget(self.signals_widget)
        
        left_layout.addWidget(scroll)

        # Add Resistance Calculator
        self.resistance_calc = ResistanceCalculator()
        left_layout.addWidget(self.resistance_calc)

        # Buttons panel
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        
        add_button = QPushButton("Add Signal")
        add_button.clicked.connect(self.add_signal)
        buttons_layout.addWidget(add_button)
        
        save_button = QPushButton("Save SPICE")
        save_button.clicked.connect(self.save_spice_model)
        buttons_layout.addWidget(save_button)
        
        export_button = QPushButton("Export Data")
        export_button.clicked.connect(self.export_data)
        buttons_layout.addWidget(export_button)
        
        left_layout.addWidget(buttons_widget)

        # Plot controls
        plot_controls = QWidget()
        plot_controls_layout = QHBoxLayout(plot_controls)
        
        self.auto_scale_check = QCheckBox("Auto-scale plot")
        self.auto_scale_check.setChecked(True)
        plot_controls_layout.addWidget(self.auto_scale_check)
        
        self.show_individual_check = QCheckBox("Show individual signals")
        self.show_individual_check.setChecked(True)
        self.show_individual_check.stateChanged.connect(self.update_plot)
        plot_controls_layout.addWidget(self.show_individual_check)
        
        left_layout.addWidget(plot_controls)

        layout.addWidget(left_panel)

        # Create right panel for plot and SPICE model
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        layout.addWidget(right_panel)

        # Create plot widget with navigation
        plot_widget = QWidget()
        plot_layout = QVBoxLayout(plot_widget)
        
        # Add matplotlib figure
        self.figure, self.ax = plt.subplots(figsize=(8, 4))
        self.canvas = FigureCanvas(self.figure)
        
        # Add navigation toolbar
        self.toolbar = NavigationToolbar(self.canvas, plot_widget)
        self.canvas.mpl_connect('button_press_event', self.on_mouse_press)
        
        plot_layout.addWidget(self.toolbar)
        plot_layout.addWidget(self.canvas)
        
        right_layout.addWidget(plot_widget)

        # Add SPICE model text view
        self.spice_text = QTextEdit()
        self.spice_text.setReadOnly(True)
        right_layout.addWidget(self.spice_text)

        # Initialize with two signals
        self.signal_controls = []
        self.add_signal()
        self.add_signal()

        self.figure.tight_layout()

    def add_signal(self):
        """Add a new signal control panel"""
        control = SignalControls(self, len(self.signal_controls))
        self.signals_layout.addWidget(control)
        self.signal_controls.append(control)
        self.update_plot()
        return control

    def remove_signal(self, control):
        """Remove a signal control panel"""
        self.signals_layout.removeWidget(control)
        self.signal_controls.remove(control)
        control.deleteLater()
        self.update_plot()

    def calculate_signal(self, control, t):
        """Calculate signal for given control and time array"""
        values = control.get_values()
        amplitude = values['amplitude']
        delay = values['delay'] / 1000
        freq = values['frequency']
        zeta = values['damping']
        
        omega = 2 * np.pi * freq
        alpha = zeta * omega
        phase_factor = np.sqrt(1 - zeta**2)
        
        response = np.zeros_like(t)
        mask = t >= delay
        t_shifted = t[mask] - delay
        response[mask] = amplitude * np.exp(-alpha * t_shifted) * \
                        np.sin(omega * phase_factor * t_shifted)
        return response

    def preview_signal(self, control):
        """Show preview of individual signal"""
        preview_window = QMainWindow(self)
        preview_window.setWindowTitle(f"Preview {control.signal_label.text()}")
        preview_window.setGeometry(200, 200, 600, 400)
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        fig, ax = plt.subplots(figsize=(6, 4))
        canvas = FigureCanvas(fig)
        layout.addWidget(canvas)
        
        # Calculate and plot signal
        max_delay = control.get_values()['delay']
        t = np.linspace(0, (max_delay + 50) / 1000, 10000)
        response = self.calculate_signal(control, t)
        
        ax.plot(t*1000, response, color=control.signal_color.name())
        ax.grid(True)
        ax.set_xlabel('Time (ms)')
        ax.set_ylabel('Voltage (V)')
        
        fig.tight_layout()
        canvas.draw()
        
        preview_window.setCentralWidget(widget)
        preview_window.show()

    def export_data(self):
        """Export plot data to CSV"""
        filename, _ = QFileDialog.getSaveFileName(self, 
                                                "Export Data",
                                                "piezo_data.csv",
                                                "CSV Files (*.csv)")
        if filename:
            # Calculate data
            max_delay = max(control.get_values()['delay'] 
                          for control in self.signal_controls 
                          if control.is_visible())
            t = np.linspace(0, (max_delay + 50) / 1000, 10000)
            
            # Create header
            header = "Time(ms)"
            data = [t*1000]  # Convert to ms
            
            # Calculate individual signals
            for control in self.signal_controls:
                if control.is_visible():
                    header += f",{control.signal_label.text()}(V)"
                    response = self.calculate_signal(control, t)
                    data.append(response)
            
            # Calculate combined signal
            header += ",Combined(V)"
            combined = np.zeros_like(t)
            for control in self.signal_controls:
                if control.is_visible():
                    combined += self.calculate_signal(control, t)
            data.append(combined)
            
            # Save to CSV
            np.savetxt(filename, np.column_stack(data), delimiter=',',
                      header=header, comments='')

    def update_plot(self):
        """Update plot and SPICE model text"""
        if self.manual_zoom and not self.auto_scale_check.isChecked():
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()

        self.ax.clear()

        # Find maximum delay
        max_delay = max(control.get_values()['delay'] 
                       for control in self.signal_controls 
                       if control.is_visible())
        
        # Time array
        t = np.linspace(0, (max_delay + 50) / 1000, 10000)
        combined = np.zeros_like(t)

        # Plot individual and combined signals
        for control in self.signal_controls:
            if control.is_visible():
                response = self.calculate_signal(control, t)
                combined += response
                
                if self.show_individual_check.isChecked():
                    self.ax.plot(t*1000, response, '--', 
                               color=control.signal_color.name(), 
                               alpha=0.5)

        # Plot combined signal
        self.ax.plot(t*1000, combined, 'b-', linewidth=2)

        self.ax.grid(True)
        self.ax.set_xlabel('Time (ms)')
        self.ax.set_ylabel('Voltage (V)')

        # Set plot range
        if self.auto_scale_check.isChecked():
            plot_range = self.calculate_plot_range(t, combined)
            self.ax.set_xlim(plot_range['x'])
            self.ax.set_ylim(plot_range['y'])
        elif self.manual_zoom:
            self.ax.set_xlim(xlim)
            self.ax.set_ylim(ylim)

        self.figure.tight_layout()
        self.canvas.draw()

        # Update SPICE model text
        self.spice_text.setText(self.generate_spice_model())

    def calculate_plot_range(self, t, response):
        """Calculate appropriate plot range based on signal data"""
        margin_factor = 0.1  # 10% margin
        
        # Time range
        t_min = 0
        t_max = np.max(t) * 1000  # Convert to ms
        t_range = t_max - t_min
        t_margin = t_range * margin_factor
        
        # Voltage range
        v_min = np.min(response)
        v_max = np.max(response)
        v_range = max(abs(v_max - v_min), 1e-6)  # Prevent zero range
        v_margin = v_range * margin_factor

        return {
            'x': (t_min - t_margin, t_max + t_margin),
            'y': (v_min - v_margin, v_max + v_margin)
        }

    def generate_spice_model(self):
        """Generate SPICE model text"""
        model = f"""* Multiple Piezoelectric Sensor Response Library
* Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
* Dynamic multi-signal configuration

.SUBCKT MULTI_PIEZO out gnd

* Combined response of multiple events
E1 out gnd VALUE={{"""

        first = True
        for control in self.signal_controls:
            if not control.is_visible():
                continue
                
            values = control.get_values()
            amp = values['amplitude']
            delay = values['delay'] / 1000  # Convert to seconds
            freq = values['frequency']
            zeta = values['damping']
            
            omega = 2 * np.pi * freq
            alpha = zeta * omega
            phase_factor = np.sqrt(1 - zeta**2)
            
            if not first:
                model += "+"
            first = False
            
            model += f"""
+ {amp:.1f} * exp(-{alpha:.8f} * (time - {delay:.6f})) * sin({omega:.8f} * {phase_factor:.8f} * (time - {delay:.6f})) * ((time - {delay:.6f}) > 0)"""

        model += "\n+ }\n\n.ENDS MULTI_PIEZO"
        return model

    def save_spice_model(self):
        """Save SPICE model to file"""
        filename, _ = QFileDialog.getSaveFileName(
            self, 
            "Save SPICE Model",
            "multi_piezo.lib",
            "SPICE Library (*.lib);;All Files (*.*)"
        )
        if filename:
            with open(filename, 'w') as f:
                f.write(self.generate_spice_model())

    def on_mouse_press(self, event):
        """Track when user interacts with the plot"""
        if self.toolbar.mode in ['zoom rect', 'pan/zoom']:
            self.manual_zoom = True
        elif event.dblclick:  # Double click to reset view
            self.manual_zoom = False
            self.auto_scale_check.setChecked(True)
            self.update_plot()

def main():
    app = QApplication(sys.argv)
    window = PiezoGui()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
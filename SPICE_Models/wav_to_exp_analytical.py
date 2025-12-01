import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, Button
from scipy.io import wavfile
from scipy.optimize import curve_fit
from scipy.signal import find_peaks
import tkinter as tk
from tkinter import filedialog
import os

class PiezoAutoFitter:
    def __init__(self):
        self.sample_rate = 0
        self.data = None
        self.time = None
        self.filepath = ""
        
        # We model 2 components: Primary (Body) and Secondary (Attack/Overtone)
        self.params = {
            'amp1': 1.0, 'decay1': 10.0, 'freq1': 100.0, 'phase1': 0.0,
            'amp2': 0.5, 'decay2': 50.0, 'freq2': 400.0, 'phase2': 0.0,
            'scale': 1.0
        }
        
        self.sliders = {}
        self.setup_gui()

    def dual_damped_sine(self, t, a1, d1, f1, p1, a2, d2, f2, p2):
        """
        Sum of two damped sine waves.
        """
        c1 = a1 * np.exp(-d1 * t) * np.sin(2 * np.pi * f1 * t + p1)
        c2 = a2 * np.exp(-d2 * t) * np.sin(2 * np.pi * f2 * t + p2)
        return c1 + c2

    def load_wav(self):
        # Hidden Tk root for file dialog
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(filetypes=[("WAV files", "*.wav")])
        root.destroy()

        if not file_path:
            return

        self.filepath = file_path
        self.sample_rate, data = wavfile.read(file_path)

        # Normalize to float -1.0 to 1.0
        if data.dtype == np.int16:
            data = data / 32768.0
        elif data.dtype == np.int32:
            data = data / 2147483648.0
        
        # Mix to Mono
        if len(data.shape) > 1:
            data = data.mean(axis=1)

        # --- Smart Trimming ---
        # Find absolute max peak
        peak_idx = np.argmax(np.abs(data))
        
        # Start shortly before peak
        start_idx = max(0, peak_idx - int(0.002 * self.sample_rate)) # 2ms pre-roll
        
        # Determine end: when signal stays below noise floor for a while
        # For simplicity, we take 100ms or until 0.2s
        window_len = int(0.15 * self.sample_rate)
        end_idx = min(len(data), start_idx + window_len)
        
        self.data = data[start_idx:end_idx]
        self.time = np.linspace(0, len(self.data) / self.sample_rate, len(self.data))

        # Run the automated math fitting
        self.perform_auto_fit()
        
        self.update_sliders_from_params()
        self.update_plot()

    def perform_auto_fit(self):
        print("Analyzing signal spectrum...")
        
        # 1. FFT to find dominant frequencies
        N = len(self.data)
        yf = np.fft.fft(self.data)
        xf = np.fft.fftfreq(N, 1 / self.sample_rate)
        
        # Get magnitude spectrum (positive side only)
        mag = np.abs(yf[:N//2])
        freqs = xf[:N//2]
        
        # Find peaks in spectrum
        peaks, _ = find_peaks(mag, height=np.max(mag)*0.1, distance=50)
        sorted_peak_indices = peaks[np.argsort(mag[peaks])[::-1]] # Sort by height
        
        # Guess Frequency 1 (Dominant)
        guess_f1 = freqs[sorted_peak_indices[0]] if len(sorted_peak_indices) > 0 else 100.0
        
        # Guess Frequency 2 (Secondary)
        guess_f2 = guess_f1 * 2 # Fallback
        if len(sorted_peak_indices) > 1:
            guess_f2 = freqs[sorted_peak_indices[1]]

        # Guess Amplitudes (Roughly based on time domain peak)
        max_amp = np.max(np.abs(self.data))
        guess_a1 = max_amp * 0.7
        guess_a2 = max_amp * 0.3
        
        # Guess Decays (High freq usually decays faster)
        guess_d1 = 20.0
        guess_d2 = 50.0

        # Initial Guesses
        p0 = [guess_a1, guess_d1, guess_f1, 0.0, 
              guess_a2, guess_d2, guess_f2, 0.0]

        # Bounds: Amp (+/-), Decay (0 to 1000), Freq (1 to 20k), Phase (-pi to pi)
        lower_bounds = [-np.inf, 0, 1, -np.pi, -np.inf, 0, 1, -np.pi]
        upper_bounds = [np.inf, 1000, 20000, np.pi, np.inf, 1000, 20000, np.pi]

        print("Running Least Squares Optimization...")
        try:
            popt, _ = curve_fit(self.dual_damped_sine, self.time, self.data, p0=p0, 
                                bounds=(lower_bounds, upper_bounds), maxfev=20000)
            
            self.params['amp1'], self.params['decay1'], self.params['freq1'], self.params['phase1'] = popt[0:4]
            self.params['amp2'], self.params['decay2'], self.params['freq2'], self.params['phase2'] = popt[4:8]
            print("Fit successful.")
        except Exception as e:
            print(f"Fit failed, using guesses: {e}")
            self.params['freq1'] = guess_f1
            self.params['freq2'] = guess_f2

    def setup_gui(self):
        self.fig, self.ax = plt.subplots(figsize=(12, 8))
        # Leave room at bottom for controls
        plt.subplots_adjust(left=0.1, bottom=0.45, right=0.95, top=0.95)
        
        self.line_raw, = self.ax.plot([], [], 'k-', alpha=0.3, label='Original WAV')
        self.line_fit, = self.ax.plot([], [], 'r--', linewidth=2, label='Dual-Sine Approx')
        self.line_c1, = self.ax.plot([], [], 'g:', alpha=0.5, linewidth=1, label='Component 1')
        self.line_c2, = self.ax.plot([], [], 'b:', alpha=0.5, linewidth=1, label='Component 2')
        
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Amplitude")
        self.ax.grid(True)
        self.ax.legend(loc='upper right')

        # --- Controls Layout ---
        # We need 9 sliders. We'll organize them in 2 columns.
        axcolor = 'lightgoldenrodyellow'
        
        # Helper to make slider
        def make_slider(label, key, min_val, max_val, y_pos, x_col=0):
            # x_col 0 = left, x_col 1 = right
            x_start = 0.1 if x_col == 0 else 0.55
            width = 0.35
            ax_s = plt.axes([x_start, y_pos, width, 0.03], facecolor=axcolor)
            s = Slider(ax_s, label, min_val, max_val, valinit=self.params[key])
            s.on_changed(lambda v: self.on_slider_change(key, v))
            self.sliders[key] = s
            return s

        # Column 1: Primary Wave
        plt.text(0.1, 0.40, "Component 1 (Main)", transform=self.fig.transFigure, weight='bold')
        make_slider('Amp 1', 'amp1', -2.0, 2.0, 0.35, 0)
        make_slider('Decay 1', 'decay1', 1.0, 200.0, 0.30, 0)
        make_slider('Freq 1', 'freq1', 10.0, 1000.0, 0.25, 0)
        make_slider('Phase 1', 'phase1', -3.14, 3.14, 0.20, 0)

        # Column 2: Secondary Wave
        plt.text(0.55, 0.40, "Component 2 (Detail)", transform=self.fig.transFigure, weight='bold')
        make_slider('Amp 2', 'amp2', -2.0, 2.0, 0.35, 1)
        make_slider('Decay 2', 'decay2', 1.0, 400.0, 0.30, 1)
        make_slider('Freq 2', 'freq2', 10.0, 2000.0, 0.25, 1)
        make_slider('Phase 2', 'phase2', -3.14, 3.14, 0.20, 1)

        # Bottom: Scale
        make_slider('Global Scale', 'scale', 0.1, 100.0, 0.10, 0)

        # Buttons
        btn_load_ax = plt.axes([0.55, 0.10, 0.15, 0.05])
        self.btn_load = Button(btn_load_ax, 'Load WAV', hovercolor='0.975')
        self.btn_load.on_clicked(lambda x: self.load_wav())

        btn_exp_ax = plt.axes([0.75, 0.10, 0.15, 0.05])
        self.btn_export = Button(btn_exp_ax, 'Export SPICE', hovercolor='0.975')
        self.btn_export.on_clicked(lambda x: self.export_spice())

        plt.show()

    def update_sliders_from_params(self):
        # Update slider positions without triggering callbacks (if possible)
        # Note: matplotlib sliders trigger callbacks on set_val, 
        # but our callback just updates params which is fine.
        for key, slider in self.sliders.items():
            if key in self.params:
                slider.set_val(self.params[key])

    def on_slider_change(self, key, val):
        self.params[key] = val
        self.update_plot()

    def update_plot(self):
        if self.data is None:
            return
            
        p = self.params
        
        # Calculate components based on current slider values
        # Note: We visualize the "fit" directly. The 'scale' parameter
        # is usually for the voltage output scaling, but we will apply it 
        # to the red line so user sees the final output magnitude.
        
        t = self.time
        c1 = p['amp1'] * np.exp(-p['decay1'] * t) * np.sin(2 * np.pi * p['freq1'] * t + p['phase1'])
        c2 = p['amp2'] * np.exp(-p['decay2'] * t) * np.sin(2 * np.pi * p['freq2'] * t + p['phase2'])
        
        total_signal = (c1 + c2) * p['scale']
        
        self.line_raw.set_data(self.time, self.data) # Raw is usually normalized -1 to 1
        self.line_fit.set_data(self.time, total_signal)
        
        # Optional: Show individual components for debugging
        self.line_c1.set_data(self.time, c1 * p['scale'])
        self.line_c2.set_data(self.time, c2 * p['scale'])

        self.ax.relim()
        self.ax.autoscale_view()
        self.fig.canvas.draw_idle()

    def export_spice(self):
        if self.data is None:
            return

        p = self.params
        
        # We need to distribute the Scale factor into the Amplitudes
        # because the SPICE equation is just math.
        a1_final = p['amp1'] * p['scale']
        a2_final = p['amp2'] * p['scale']
        
        # Component 1 String
        # E.g.  1.5 * exp(-20 * time) * sin(6.28 * 100 * time + 0)
        comp1 = f"{a1_final:.5f} * exp(-{p['decay1']:.5f} * time) * sin(6.283185 * {p['freq1']:.5f} * time + {p['phase1']:.5f})"
        
        # Component 2 String
        comp2 = f"{a2_final:.5f} * exp(-{p['decay2']:.5f} * time) * sin(6.283185 * {p['freq2']:.5f} * time + {p['phase2']:.5f})"
        
        model_name = "CUSTOM_PIEZO"
        filename = "piezo_auto_model.sub"
        
        content = f"""
.SUBCKT {model_name} out gnd

* Generated Automated Model
* Dual-Component Damped Sine Approximation
* Component 1: F={p['freq1']:.1f}Hz, Decay={p['decay1']:.1f}
* Component 2: F={p['freq2']:.1f}Hz, Decay={p['decay2']:.1f}

E1 out gnd VALUE={{
+ {comp1} 
+ + 
+ {comp2}
+ }}

.ENDS {model_name}
"""
        with open(filename, "w") as f:
            f.write(content)
            
        print(f"Exported to {filename}")
        
        # Simple popup
        tk.messagebox = tk.Tk()
        tk.messagebox.withdraw()
        from tkinter import messagebox
        messagebox.showinfo("Export", f"SPICE model saved to:\n{os.path.abspath(filename)}")
        tk.messagebox.destroy()

if __name__ == "__main__":
    app = PiezoAutoFitter()
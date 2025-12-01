#!/usr/bin/env python3
"""
WAV to SPICE Converter
A GUI application to convert WAV audio files to SPICE PWL voltage sources
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import wave
import struct
import os
from pathlib import Path


class WavToSpiceConverter:
    def __init__(self, root):
        self.root = root
        self.root.title("WAV to SPICE Converter")
        self.root.geometry("800x700")
        
        # Variables
        self.wav_file = tk.StringVar()
        self.output_file = tk.StringVar()
        self.max_points = tk.IntVar(value=10000)
        self.voltage_min = tk.DoubleVar(value=-1.0)
        self.voltage_max = tk.DoubleVar(value=1.0)
        self.source_name = tk.StringVar(value="Vaudio")
        self.node_pos = tk.StringVar(value="input")
        self.node_neg = tk.StringVar(value="0")
        self.output_format = tk.StringVar(value="external")
        self.model_type = tk.StringVar(value="subckt")
        self.subckt_name = tk.StringVar(value="AUDIO_SOURCE")
        
        # WAV file info
        self.wav_info = {}
        
        self.create_widgets()
        
    def create_widgets(self):
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Title
        title = ttk.Label(main_frame, text="WAV to SPICE PWL Converter", 
                         font=('Helvetica', 16, 'bold'))
        title.grid(row=0, column=0, columnspan=3, pady=10)
        
        # Input WAV file section
        ttk.Label(main_frame, text="Input WAV File:", font=('Helvetica', 10, 'bold')).grid(
            row=1, column=0, sticky=tk.W, pady=5)
        
        ttk.Entry(main_frame, textvariable=self.wav_file, width=50).grid(
            row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), padx=(0, 5))
        
        ttk.Button(main_frame, text="Browse...", command=self.browse_wav).grid(
            row=2, column=2, sticky=tk.W)
        
        # WAV Info display
        self.info_text = tk.Text(main_frame, height=4, width=50, bg="#f0f0f0", 
                                 state='disabled', font=('Courier', 9))
        self.info_text.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # Conversion options
        options_frame = ttk.LabelFrame(main_frame, text="Conversion Options", padding="10")
        options_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        options_frame.columnconfigure(1, weight=1)
        
        # Max points
        ttk.Label(options_frame, text="Max Data Points:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(options_frame, textvariable=self.max_points, width=15).grid(
            row=0, column=1, sticky=tk.W, padx=5)
        ttk.Label(options_frame, text="(reduces file size)").grid(
            row=0, column=2, sticky=tk.W)
        
        # Voltage range
        ttk.Label(options_frame, text="Voltage Range:").grid(row=1, column=0, sticky=tk.W, pady=5)
        voltage_frame = ttk.Frame(options_frame)
        voltage_frame.grid(row=1, column=1, columnspan=2, sticky=tk.W)
        ttk.Entry(voltage_frame, textvariable=self.voltage_min, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(voltage_frame, text="to").pack(side=tk.LEFT, padx=5)
        ttk.Entry(voltage_frame, textvariable=self.voltage_max, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Label(voltage_frame, text="Volts").pack(side=tk.LEFT, padx=5)
        
        # SPICE source options
        spice_frame = ttk.LabelFrame(main_frame, text="SPICE Source Options", padding="10")
        spice_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        spice_frame.columnconfigure(1, weight=1)
        
        # Source name
        ttk.Label(spice_frame, text="Source Name:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(spice_frame, textvariable=self.source_name, width=15).grid(
            row=0, column=1, sticky=tk.W, padx=5)
        
        # Node names
        ttk.Label(spice_frame, text="Positive Node:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(spice_frame, textvariable=self.node_pos, width=15).grid(
            row=1, column=1, sticky=tk.W, padx=5)
        
        ttk.Label(spice_frame, text="Negative Node:").grid(row=2, column=0, sticky=tk.W)
        ttk.Entry(spice_frame, textvariable=self.node_neg, width=15).grid(
            row=2, column=1, sticky=tk.W, padx=5)
        
        # Model type
        ttk.Label(spice_frame, text="Model Type:").grid(row=3, column=0, sticky=tk.W, pady=5)
        model_frame = ttk.Frame(spice_frame)
        model_frame.grid(row=3, column=1, columnspan=2, sticky=tk.W)
        ttk.Radiobutton(model_frame, text="Subcircuit (KiCAD)", variable=self.model_type, 
                       value="subckt").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(model_frame, text="Direct Source", variable=self.model_type, 
                       value="direct").pack(side=tk.LEFT, padx=5)
        
        # Subcircuit name (only for subckt mode)
        ttk.Label(spice_frame, text="Subcircuit Name:").grid(row=4, column=0, sticky=tk.W, pady=5)
        ttk.Entry(spice_frame, textvariable=self.subckt_name, width=20).grid(
            row=4, column=1, sticky=tk.W, padx=5)
        ttk.Label(spice_frame, text="(for KiCAD symbol)").grid(
            row=4, column=2, sticky=tk.W)
        
        # Output format
        ttk.Label(spice_frame, text="Output Format:").grid(row=5, column=0, sticky=tk.W, pady=5)
        format_frame = ttk.Frame(spice_frame)
        format_frame.grid(row=5, column=1, columnspan=2, sticky=tk.W)
        ttk.Radiobutton(format_frame, text="External PWL File", variable=self.output_format, 
                       value="external").pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(format_frame, text="Inline PWL", variable=self.output_format, 
                       value="inline").pack(side=tk.LEFT, padx=5)
        
        # Convert button
        ttk.Button(main_frame, text="Convert to SPICE", command=self.convert,
                  style='Accent.TButton').grid(row=6, column=0, columnspan=3, pady=10)
        
        # Preview
        ttk.Label(main_frame, text="SPICE Code Preview:", font=('Helvetica', 10, 'bold')).grid(
            row=7, column=0, sticky=tk.W, pady=5)
        
        self.preview_text = scrolledtext.ScrolledText(main_frame, height=12, width=70,
                                                      font=('Courier', 9))
        self.preview_text.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.rowconfigure(8, weight=1)
        
        # Save button
        ttk.Button(main_frame, text="Save SPICE File", command=self.save_output).grid(
            row=9, column=0, columnspan=3, pady=10)
        
    def browse_wav(self):
        filename = filedialog.askopenfilename(
            title="Select WAV File",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")]
        )
        if filename:
            self.wav_file.set(filename)
            self.load_wav_info(filename)
            
    def load_wav_info(self, filename):
        try:
            with wave.open(filename, 'rb') as wav:
                self.wav_info = {
                    'channels': wav.getnchannels(),
                    'sample_width': wav.getsampwidth(),
                    'framerate': wav.getframerate(),
                    'n_frames': wav.getnframes(),
                    'duration': wav.getnframes() / wav.getframerate()
                }
                
                # Update info display
                self.info_text.config(state='normal')
                self.info_text.delete(1.0, tk.END)
                info = (
                    f"Channels: {self.wav_info['channels']} | "
                    f"Sample Rate: {self.wav_info['framerate']} Hz | "
                    f"Bit Depth: {self.wav_info['sample_width']*8}-bit\n"
                    f"Duration: {self.wav_info['duration']:.2f} seconds | "
                    f"Total Samples: {self.wav_info['n_frames']:,}\n"
                    f"Estimated PWL Points: {min(self.wav_info['n_frames'], self.max_points.get()):,}"
                )
                self.info_text.insert(1.0, info)
                self.info_text.config(state='disabled')
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read WAV file:\n{e}")
            
    def convert(self):
        if not self.wav_file.get():
            messagebox.showwarning("Warning", "Please select a WAV file first")
            return
            
        try:
            pwl_data = self.wav_to_pwl(self.wav_file.get())
            spice_code = self.generate_spice_code(pwl_data)
            
            # Update preview
            self.preview_text.delete(1.0, tk.END)
            self.preview_text.insert(1.0, spice_code)
            
            messagebox.showinfo("Success", 
                              f"Conversion complete!\n"
                              f"Generated {len(pwl_data)} data points")
        except Exception as e:
            messagebox.showerror("Error", f"Conversion failed:\n{e}")
            
    def wav_to_pwl(self, wav_file):
        with wave.open(wav_file, 'rb') as wav:
            n_channels = wav.getnchannels()
            sampwidth = wav.getsampwidth()
            framerate = wav.getframerate()
            n_frames = wav.getnframes()
            
            # Read all frames
            frames = wav.readframes(n_frames)
            
            # Unpack based on sample width
            if sampwidth == 1:  # 8-bit
                samples = struct.unpack(f'{n_frames * n_channels}B', frames)
                samples = [(s - 128) for s in samples]  # Convert unsigned to signed
                max_val = 128
            elif sampwidth == 2:  # 16-bit
                samples = struct.unpack(f'{n_frames * n_channels}h', frames)
                max_val = 32768
            elif sampwidth == 3:  # 24-bit (less common)
                samples = []
                for i in range(0, len(frames), 3 * n_channels):
                    for ch in range(n_channels):
                        idx = i + ch * 3
                        s = int.from_bytes(frames[idx:idx+3], byteorder='little', signed=True)
                        samples.append(s)
                max_val = 8388608
            else:
                raise ValueError(f"Unsupported sample width: {sampwidth}")
            
            # Use only first channel if stereo
            if n_channels == 2:
                samples = samples[::2]
            elif n_channels > 2:
                samples = samples[::n_channels]
                
            # Downsample if needed
            max_pts = self.max_points.get()
            step = max(1, len(samples) // max_pts)
            
            # Convert to time-voltage pairs
            pwl_data = []
            v_min = self.voltage_min.get()
            v_max = self.voltage_max.get()
            v_range = v_max - v_min
            
            for i in range(0, len(samples), step):
                time = i / framerate
                # Normalize to 0-1, then scale to voltage range
                normalized = (samples[i] / max_val + 1) / 2  # 0 to 1
                voltage = v_min + normalized * v_range
                pwl_data.append((time, voltage))
                
        return pwl_data
        
    def generate_spice_code(self, pwl_data):
        source_name = self.source_name.get()
        node_pos = self.node_pos.get()
        node_neg = self.node_neg.get()
        model_type = self.model_type.get()
        subckt_name = self.subckt_name.get()
        
        # Get current date/time for header
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if model_type == "subckt":
            # Generate subcircuit model for KiCAD - matching user's format
            code = f"* WAV Audio Source Library\n"
            code += f"* Source file: {Path(self.wav_file.get()).name}\n"
            code += f"* Generated: {timestamp}\n"
            code += f"* Duration: {pwl_data[-1][0]:.6f} seconds\n"
            code += f"* Sample points: {len(pwl_data)}\n"
            code += f"* Voltage range: {self.voltage_min.get():.3f}V to {self.voltage_max.get():.3f}V\n"
            code += f"*\n"
            code += f".SUBCKT {subckt_name} out gnd\n"
            code += f"* Audio voltage source from WAV file\n"
            
            if self.output_format.get() == "external":
                code += f'V1 out gnd PWL(FILE "audio_pwl.dat")\n'
            else:
                # Inline PWL for subcircuit
                code += f"V1 out gnd PWL(\n"
                max_inline = min(len(pwl_data), 1000)
                for i, (t, v) in enumerate(pwl_data[:max_inline]):
                    if i == 0:
                        code += f"+ {t:.6e} {v:.6e}\n"
                    else:
                        code += f"+ {t:.6e} {v:.6e}\n"
                if len(pwl_data) > max_inline:
                    code += f"+ )\n* Note: Truncated to {max_inline} points for display\n"
                else:
                    code += f"+ )\n"
            
            code += f".ENDS {subckt_name}\n"
            code += f"\n"
            
            # Add usage example
            code += f"* Usage in KiCAD:\n"
            code += f"* 1. Add this file as a SPICE model library\n"
            code += f"* 2. In your symbol, set:\n"
            code += f"*    Spice_Primitive: X\n"
            code += f"*    Spice_Model: {subckt_name}\n"
            code += f"*    Spice_Lib_File: ${{KIPRJMOD}}/audio_source.lib\n"
            code += f"* 3. Pin 1 (out) -> your circuit signal node\n"
            code += f"* 4. Pin 2 (gnd) -> ground (0)\n"
            code += f"*\n"
            code += f"* IMPORTANT: The file audio_pwl.dat must be in the same\n"
            code += f"* directory as this .lib file for ngspice to find it.\n"
            code += f"*\n"
            code += f"* Netlist instantiation example:\n"
            code += f"* X1 signal_node 0 {subckt_name}\n"
            
        else:
            # Direct voltage source (original format)
            code = f"* Audio source from WAV file: {Path(self.wav_file.get()).name}\n"
            code += f"* Generated: {timestamp}\n"
            code += f"* Duration: {pwl_data[-1][0]:.4f} seconds\n"
            code += f"* Data points: {len(pwl_data)}\n\n"
            
            if self.output_format.get() == "external":
                code += f'{source_name} {node_pos} {node_neg} PWL(FILE "audio_pwl.dat")\n\n'
                code += "* Example usage in your circuit:\n"
                code += "*.include audio_source.cir\n"
                code += "*R1 input output 10k\n"
                code += "*C1 output 0 1u\n"
                code += f"*.tran 1u {pwl_data[-1][0]}\n"
            else:
                # Inline PWL
                code += f"{source_name} {node_pos} {node_neg} PWL(\n"
                max_inline = min(len(pwl_data), 1000)
                for i, (t, v) in enumerate(pwl_data[:max_inline]):
                    code += f"+ {t:.6e} {v:.6e}\n"
                
                if len(pwl_data) > max_inline:
                    code += f"* ... {len(pwl_data) - max_inline} more points (truncated for display)\n"
                code += "+ )\n"
            
        return code
        
    def save_output(self):
        if not self.preview_text.get(1.0, tk.END).strip():
            messagebox.showwarning("Warning", "No data to save. Convert a file first.")
            return
            
        # Suggest filename based on model type
        if self.wav_file.get():
            base_name = Path(self.wav_file.get()).stem
            if self.model_type.get() == "subckt":
                default_name = base_name + "_source.lib"
                file_types = [("SPICE Library", "*.lib"), 
                            ("SPICE Model", "*.mod"),
                            ("SPICE files", "*.cir *.sp *.spi"), 
                            ("All files", "*.*")]
            else:
                default_name = base_name + "_spice.cir"
                file_types = [("SPICE files", "*.cir *.sp *.spi"), 
                            ("All files", "*.*")]
        else:
            default_name = "audio_source.lib" if self.model_type.get() == "subckt" else "audio_source.cir"
            file_types = [("SPICE files", "*.lib *.cir *.sp *.spi"), 
                        ("All files", "*.*")]
            
        filename = filedialog.asksaveasfilename(
            defaultextension=".lib" if self.model_type.get() == "subckt" else ".cir",
            initialfile=default_name,
            filetypes=file_types
        )
        
        if filename:
            try:
                # Save main SPICE file
                with open(filename, 'w') as f:
                    f.write(self.preview_text.get(1.0, tk.END))
                
                # If external format, also save PWL data file
                if self.output_format.get() == "external":
                    pwl_data = self.wav_to_pwl(self.wav_file.get())
                    pwl_filename = Path(filename).parent / "audio_pwl.dat"
                    
                    with open(pwl_filename, 'w') as f:
                        for t, v in pwl_data:
                            f.write(f"{t:.6e} {v:.6e}\n")
                    
                    messagebox.showinfo("Success", 
                                      f"Files saved:\n{filename}\n{pwl_filename}")
                else:
                    messagebox.showinfo("Success", f"File saved:\n{filename}")
                    
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save file:\n{e}")


def main():
    root = tk.Tk()
    app = WavToSpiceConverter(root)
    root.mainloop()


if __name__ == "__main__":
    main()
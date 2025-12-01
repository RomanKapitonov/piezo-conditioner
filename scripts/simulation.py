import numpy as np
from scipy import signal
import matplotlib.pyplot as plt

class PiezoCircuitModel:
    def __init__(self):
        # Circuit parameters
        self.Vcc = 5.0  # Supply voltage
        
        # Component values
        self.C14 = 0.22e-6  # Input coupling capacitor
        self.R26 = self.R28 = 100e3  # Input voltage divider
        self.R33 = self.R36 = 10e3  # Op-amp feedback
        self.R34 = self.R35 = 68e3  # Op-amp feedback
        self.C19 = self.C20 = 22e-12  # Op-amp compensation
        self.R39 = self.R40 = 1e3  # Diode bias resistors
        self.R43 = self.R44 = self.R46 = self.R48 = 22e3  # Second stage feedback
        self.C22 = 22e-12  # Second stage compensation
        self.C24 = 0.22e-6  # Output coupling
        
        # Diode parameters
        self.Is = 1e-12  # Diode saturation current
        self.Vt = 0.026  # Thermal voltage
        
        # Op-amp parameters
        self.gain = 1e5  # Open loop gain
        self.GBW = 1e6  # Gain bandwidth product
        
    def diode_current(self, voltage):
        """Model diode current using exponential characteristic"""
        return self.Is * (np.exp(voltage / self.Vt) - 1)
    
    def diode_clipper(self, voltage):
        """Model back-to-back diode clipper"""
        return np.clip(voltage, -0.7, 0.7)
    
    def opamp_stage(self, input_signal, gain, fc=1e6):
        """Model op-amp stage with finite gain and bandwidth"""
        # Create transfer function for op-amp
        s = signal.lti([gain * 2 * np.pi * fc], [1, 2 * np.pi * fc])
        t = np.linspace(0, len(input_signal) / self.sample_rate, len(input_signal))
        _, output = signal.impulse(s, T=t)
        return signal.convolve(input_signal, output, mode='same')
    
    def simulate(self, input_signal, duration=0.1, sample_rate=44100):
        """
        Simulate circuit response to input signal
        
        Parameters:
        input_signal: Array of input voltages from piezo
        duration: Simulation duration in seconds
        sample_rate: Sampling rate in Hz
        
        Returns:
        Dictionary containing signals at various circuit nodes
        """
        self.sample_rate = sample_rate
        t = np.linspace(0, duration, int(duration * sample_rate))
        
        # Input stage
        v_in = input_signal
        v_biased = v_in * self.R28 / (self.R26 + self.R28)
        
        # First protection stage
        v_protected = self.diode_clipper(v_biased)
        
        # First op-amp stage
        gain1 = 1 + (self.R34 / self.R33)
        v_amp1 = self.opamp_stage(v_protected, gain1)
        
        # Diode network
        v_rect = self.diode_clipper(v_amp1)
        
        # Second op-amp stage
        gain2 = 1 + (self.R48 / self.R46)
        v_amp2 = self.opamp_stage(v_rect, gain2)
        
        # Output stage with DC blocking
        v_out = signal.lfilter([1, 0], [1, 1/(self.R48*self.C24)], v_amp2)
        
        return {
            'input': v_in,
            'biased': v_biased,
            'protected': v_protected,
            'amp1': v_amp1,
            'rectified': v_rect,
            'output': v_out,
            'time': t
        }
    
    def plot_results(self, results):
        """Plot simulation results"""
        fig, axs = plt.subplots(3, 2, figsize=(12, 8))
        fig.suptitle('Piezo Circuit Simulation Results')
        
        axs[0, 0].plot(results['time'] * 1000, results['input'])
        axs[0, 0].set_title('Input Signal')
        axs[0, 0].set_xlabel('Time (ms)')
        axs[0, 0].set_ylabel('Voltage (V)')
        
        axs[0, 1].plot(results['time'] * 1000, results['biased'])
        axs[0, 1].set_title('Biased Signal')
        axs[0, 1].set_xlabel('Time (ms)')
        axs[0, 1].set_ylabel('Voltage (V)')
        
        axs[1, 0].plot(results['time'] * 1000, results['protected'])
        axs[1, 0].set_title('Protected Signal')
        axs[1, 0].set_xlabel('Time (ms)')
        axs[1, 0].set_ylabel('Voltage (V)')
        
        axs[1, 1].plot(results['time'] * 1000, results['amp1'])
        axs[1, 1].set_title('First Amplifier Output')
        axs[1, 1].set_xlabel('Time (ms)')
        axs[1, 1].set_ylabel('Voltage (V)')
        
        axs[2, 0].plot(results['time'] * 1000, results['rectified'])
        axs[2, 0].set_title('Rectified Signal')
        axs[2, 0].set_xlabel('Time (ms)')
        axs[2, 0].set_ylabel('Voltage (V)')
        
        axs[2, 1].plot(results['time'] * 1000, results['output'])
        axs[2, 1].set_title('Output Signal')
        axs[2, 1].set_xlabel('Time (ms)')
        axs[2, 1].set_ylabel('Voltage (V)')
        
        plt.tight_layout()
        return fig

# Example usage
if __name__ == "__main__":
    # Create circuit model
    circuit = PiezoCircuitModel()
    
    # Generate example piezo input (damped sine wave)
    duration = 0.01  # 10ms
    sample_rate = 44100
    t = np.linspace(0, duration, int(duration * sample_rate))
    input_signal = 2.0 * np.exp(-t*1000) * np.sin(2 * np.pi * 1000 * t)
    
    # Run simulation
    results = circuit.simulate(input_signal, duration, sample_rate)
    
    # Plot results
    circuit.plot_results(results)
    plt.show()
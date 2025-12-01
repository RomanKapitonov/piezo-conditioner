def create_spice_lib(filename="multi_piezo.lib"):
    """
    Generate KiCad-compatible SPICE library with multiple piezo responses
    Pre-calculated values:
    - 2*pi = 6.28318530718
    - omega = 2*pi*f = 6283.18530718 (for f=1000Hz)
    - sqrt(1-zeta^2) = 0.9950 (for zeta=0.1)
    """
    
    lib_content = """* Multiple Piezoelectric Sensor Response Library
* KiCad Compatible Version
* Features six events with different amplitudes
* Events are spaced 10ms apart
* Base frequency: 1kHz
* Damping ratio: 0.1
* Pre-calculated values used to avoid pi constant

.SUBCKT MULTI_PIEZO out gnd

* Fixed parameters (pre-calculated for f=1000Hz, zeta=0.1):
* omega = 2*pi*f = 6283.18530718
* alpha = zeta*omega = 628.318530718
* sqrt(1-zeta^2) = 0.9950

* Combined response of multiple events
E1 out gnd VALUE={
+ 5 * exp(-628.318530718 * (time - 0.000)) * sin(6283.18530718 * 0.9950 * (time - 0.000)) * ((time - 0.000) > 0) 
+ + 10 * exp(-628.318530718 * (time - 0.010)) * sin(6283.18530718 * 0.9950 * (time - 0.010)) * ((time - 0.010) > 0)
+ + 20 * exp(-628.318530718 * (time - 0.020)) * sin(6283.18530718 * 0.9950 * (time - 0.020)) * ((time - 0.020) > 0)
+ + 30 * exp(-628.318530718 * (time - 0.030)) * sin(6283.18530718 * 0.9950 * (time - 0.030)) * ((time - 0.030) > 0)
+ + 50 * exp(-628.318530718 * (time - 0.040)) * sin(6283.18530718 * 0.9950 * (time - 0.040)) * ((time - 0.040) > 0)
+ + 70 * exp(-628.318530718 * (time - 0.050)) * sin(6283.18530718 * 0.9950 * (time - 0.050)) * ((time - 0.050) > 0)
+ }

.ENDS MULTI_PIEZO
"""
    
    # Write library file
    with open(filename, 'w') as f:
        f.write(lib_content)
    
    # Create example netlist
    netlist_content = f"""* Example netlist for multiple piezo responses
.include {filename}

* Instance the piezo source
X1 output 0 MULTI_PIEZO

* Load resistor
Rload output 0 10k

* Analysis commands
.tran 0.01m 60m
.save v(output)
.end
"""
    
    with open("multi_piezo_test.sp", 'w') as f:
        f.write(netlist_content)

# Generate the library
create_spice_lib()

print("Generated files:")
print("1. multi_piezo.lib     - KiCad-compatible SPICE library")
print("2. multi_piezo_test.sp - Example netlist")
print("\nTo use in KiCad:")
print("1. Add the library to your project")
print("2. Add a voltage source using the MULTI_PIEZO subcircuit")
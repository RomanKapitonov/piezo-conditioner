* Example netlist for multiple piezo responses
.include multi_piezo.lib

* Instance the piezo source
X1 output 0 MULTI_PIEZO

* Load resistor
Rload output 0 10k

* Analysis commands
.tran 0.01m 60m
.save v(output)
.end

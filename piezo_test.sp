* Example netlist using piezoelectric sensor model
.include piezo_custom.lib

* Instance the piezo sensor
X1 output 0 PIEZOSENSOR

* Load resistor
Rload output 0 10k

* Analysis commands
.tran 1u 0.005
.probe v(output)
.end

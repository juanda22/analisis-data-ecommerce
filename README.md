Análisis de ventas - E-commerce de tecnología

Análisis de un dataset de ventas de un e-commerce de tecnología (celulares, gaming, audio, accesorios, electrodomésticos). Trabajé con 4 tablas: órdenes, ítems de cada orden, productos y clientes, con el objetivo de entender qué tan rentable es el negocio por categoría y por canal de venta, y cómo se comportan los clientes nuevos vs. los recurrentes.

Antes tenía este mismo análisis armado en Google Sheets con Apps Script (podés verlo en analisis-datos-bidcom), pero lo pasé a Python porque quería practicar pandas con un caso más real, más allá de los ejercicios de la facultad.

El dataset no venía limpio

Como pasa siempre con datos reales, había varios problemas:

Canales de venta y métodos de pago cargados de formas distintas ("Mktplace", "MKTPLACE", "marketplace" todos referían a lo mismo)
Órdenes con estados que no coincidían con la cantidad vendida (ej. una orden "devuelta" con cantidad positiva)
Clientes, productos u órdenes referenciados que en realidad no existían en su tabla
La fecha de primera compra de los clientes (first_order_date) estaba mal calculada en el ~99% de los casos

Para lo del estado vs. cantidad definí estas reglas:

Estado de la orden	Cantidad esperada
Entregado / En tránsito	Positiva
Devuelto	Negativa
Cancelado	Cero

Y cuando una orden entregada/en tránsito tenía cantidad 0 (algo que no tiene una corrección obvia), en vez de inventar un número la marco como REVISION para que se audite a mano.

Qué hace el script

analisis_ventas_ecommerce.py corre todo el pipeline:

Carga los CSV (o genera datos de prueba si no encuentra los reales, así se puede probar sin tener el dataset a mano)
Normaliza canales, métodos de pago y canal de adquisición
Valida que los IDs referenciados existan en su tabla correspondiente
Corrige las cantidades según las reglas de arriba
Recalcula first_order_date a partir de las órdenes reales de cada cliente
Arma una comparación entre un escenario "ideal" (todo lo que se cargó) y uno "real" (solo lo que efectivamente se vendió), para ver cuánto se pierde por cancelaciones/devoluciones
Calcula margen por categoría y por canal, y clientes nuevos vs. recurrentes por mes

Los resultados (gráficos y un par de CSV) quedan guardados en output/.

Cómo correrlo
bash
pip install pandas numpy matplotlib
python analisis_ventas_ecommerce.py

Necesita customers.csv, orders.csv, order_items.csv y products.csv adentro de data/. Si no están, genera un dataset de prueba con el mismo formato para que el script se pueda correr igual.

También dejé en sql/queries.sql las mismas consultas pero escritas en SQL (pensadas para correr sobre BigQuery), por si alguien quiere ver el mismo análisis resuelto directamente en la base sin pasar por Python.

Algunos resultados
Las categorías más rentables no son las que más venden: Accesorios, Gaming y Audio tienen mejor margen que Celulares, aunque facturan menos.
El canal Web es el que más vende pero el de menor margen. El canal Mayorista, con muchos menos pedidos, deja bastante más plata por venta.
Un buen porcentaje de los "clientes nuevos" del análisis en realidad eran recurrentes mal etiquetados, por el problema de first_order_date que mencioné arriba — corregirlo cambió bastante la lectura mes a mes.

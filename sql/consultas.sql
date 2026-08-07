-- ============================================================
-- Queries SQL — Análisis de ventas (BigQuery)
-- ============================================================
-- Todas las queries excluyen órdenes CANCELLED, REVISION y RETURNED,
-- para trabajar siempre sobre el escenario de ventas efectivamente
-- concretadas (ver criterio de limpieza en README.md).


-- 1. Ventas mensuales por categoría
SELECT
  EXTRACT(MONTH FROM o.order_date) AS mes_numero,
  p.category,
  SUM(i.quantity) AS cantidad_vendida
FROM orders AS o
JOIN order_items AS i ON o.order_id = i.order_id
JOIN products AS p ON i.product_id = p.product_id
WHERE o.order_status NOT IN ('CANCELLED', 'REVISION', 'RETURNED')
GROUP BY 1, 2
ORDER BY 1, 2;


-- 2A. Top 10 productos por revenue
SELECT
  p.product_name,
  a.revenue
FROM products AS p
JOIN analisis AS a ON p.product_id = a.product_id
ORDER BY a.revenue DESC
LIMIT 10;


-- 2B. Top 10 productos por margen total
SELECT
  p.product_name,
  a.margen_total
FROM products AS p
JOIN analisis AS a ON p.product_id = a.product_id
ORDER BY a.margen_total DESC
LIMIT 10;


-- 3. Margen promedio por canal de venta
WITH margen_por_orden AS (
  SELECT
    o.channel,
    o.order_id,
    SUM(i.quantity * (i.unit_price - i.cost)) AS margen_total_de_la_orden
  FROM orders AS o
  JOIN order_items AS i ON o.order_id = i.order_id
  WHERE o.order_status NOT IN ('CANCELLED', 'REVISION', 'RETURNED')
  GROUP BY o.channel, o.order_id
)
SELECT
  channel,
  ROUND(AVG(margen_total_de_la_orden), 2) AS margen_promedio_por_venta
FROM margen_por_orden
GROUP BY channel
ORDER BY margen_promedio_por_venta DESC;


-- 4. Clientes nuevos vs. recurrentes por mes
-- Un cliente es "Nuevo" el mes de su primera orden (first_order_date,
-- ya corregida — ver corregirFirstOrderDate() en verificaciones.gs),
-- y "Recurrente" en cualquier orden posterior a esa fecha.
SELECT
  DATE_TRUNC(o.order_date, MONTH) AS mes,
  CASE
    WHEN DATE(o.order_date) > DATE(c.first_order_date) THEN 'Recurrente'
    ELSE 'Nuevo'
  END AS tipo_cliente,
  COUNT(DISTINCT o.customer_id) AS cantidad_clientes
FROM orders AS o
JOIN customers AS c ON o.customer_id = c.customer_id
WHERE o.order_status NOT IN ('CANCELLED', 'REVISION', 'RETURNED')
GROUP BY 1, 2
ORDER BY mes DESC, tipo_cliente;

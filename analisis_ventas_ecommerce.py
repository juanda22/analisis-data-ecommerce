"""
Análisis de Ventas y Calidad de Datos — E-commerce de Tecnología
==================================================================

Pipeline en Python/pandas que limpia, valida y analiza un dataset de
ventas de e-commerce (órdenes, ítems de venta, catálogo de productos
y clientes), para responder preguntas de negocio: rentabilidad por
categoría, eficiencia por canal de venta, y comportamiento de
clientes nuevos vs. recurrentes.

Uso:
    python analisis_ventas_ecommerce.py

Datos esperados en ./data/: customers.csv, orders.csv, order_items.csv,
products.csv. Si no están presentes, se genera automáticamente un
dataset sintético con el mismo esquema para poder correr el pipeline
de punta a punta igual.

Los gráficos se guardan como archivos .png en ./output/.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # generar imágenes sin necesidad de entorno gráfico
import matplotlib.pyplot as plt

RANDOM_SEED = 42
rng = np.random.default_rng(RANDOM_SEED)

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")

ALIAS_CHANNEL = {"MKTPLACE": "MARKETPLACE"}
ALIAS_PAYMENT = {"MP_PAYMENT": "MERCADOPAGO"}
ESTADOS_EXCLUIDOS_REAL = {"CANCELED", "CANCELLED", "REVISION", "RETURNED"}


# --------------------------------------------------------------------------
# 0. Datos de referencia (solo si no hay CSV reales en data/)
# --------------------------------------------------------------------------

def generar_datos_sample(data_dir: Path) -> None:
    """
    Genera un dataset sintético con el mismo esquema del dataset real,
    para que el pipeline corra de punta a punta sin depender de
    archivos externos. Reemplazar por los CSV reales en data/ para el
    análisis definitivo.
    """
    data_dir.mkdir(exist_ok=True)

    n_customers, n_products, n_orders = 200, 60, 800
    categorias = ["Celulares", "Accesorios", "Gaming", "Audio", "Electrodomesticos"]
    marcas = ["Sony", "HP", "Logitech", "Samsung", "LG"]

    customers = pd.DataFrame({
        "customer_id": [f"C{i}" for i in range(1, n_customers + 1)],
        "acquisition_channel": rng.choice(["  organico ", "PAGO", "referido ", "Organico"], n_customers),
        "first_order_date": pd.NaT,
    })

    products = pd.DataFrame({
        "product_id": [f"P{i}" for i in range(1, n_products + 1)],
        "product_name": [f"Producto {i}" for i in range(1, n_products + 1)],
        "category": rng.choice(categorias, n_products),
        "brand": rng.choice(marcas, n_products),
    })

    fechas = pd.date_range("2024-01-01", "2024-06-30", freq="D")
    estados = ["DELIVERED", "IN_TRANSIT", "RETURNED", "CANCELED"]
    canales = [" web", "MKTPLACE", "Mayorista", "marketplace "]
    pagos = [" MP_PAYMENT", "TARJETA", "transferencia"]

    orders = pd.DataFrame({
        "order_id": [f"O{i}" for i in range(1, n_orders + 1)],
        "customer_id": rng.choice(customers["customer_id"], n_orders),
        "order_date": rng.choice(fechas, n_orders),
        "order_status": rng.choice(estados, n_orders, p=[0.55, 0.15, 0.1, 0.2]),
        "channel": rng.choice(canales, n_orders),
        "payment_method": rng.choice(pagos, n_orders),
    })

    filas_items = []
    for _, orden in orders.iterrows():
        for _ in range(rng.integers(1, 4)):
            prod = products.sample(1).iloc[0]
            qty = int(rng.integers(1, 5))
            if orden["order_status"] in ("DELIVERED", "IN_TRANSIT") and rng.random() < 0.05:
                qty = 0
            filas_items.append({
                "order_id": orden["order_id"],
                "product_id": prod["product_id"],
                "quantity": qty,
                "unit_price": round(rng.uniform(10, 500), 2),
                "cost": round(rng.uniform(5, 400), 2),
            })
    order_items = pd.DataFrame(filas_items)

    customers.to_csv(data_dir / "customers.csv", index=False)
    orders.to_csv(data_dir / "orders.csv", index=False)
    order_items.to_csv(data_dir / "order_items.csv", index=False)
    products.to_csv(data_dir / "products.csv", index=False)


# --------------------------------------------------------------------------
# 1. Carga de datos
# --------------------------------------------------------------------------

def cargar_datos(data_dir: Path = DATA_DIR):
    customers = pd.read_csv(data_dir / "customers.csv")
    orders = pd.read_csv(data_dir / "orders.csv", parse_dates=["order_date"])
    order_items = pd.read_csv(data_dir / "order_items.csv")
    products = pd.read_csv(data_dir / "products.csv")
    return customers, orders, order_items, products


# --------------------------------------------------------------------------
# 2. Normalización de dimensiones
# --------------------------------------------------------------------------

def normalizar_columna(serie: pd.Series, alias: dict | None = None) -> pd.Series:
    """Recorta espacios, pasa a mayúsculas y unifica variantes conocidas."""
    limpio = serie.astype(str).str.strip().str.upper()
    if alias:
        limpio = limpio.replace(alias)
    return limpio


def normalizar_dimensiones(customers: pd.DataFrame, orders: pd.DataFrame):
    customers = customers.copy()
    orders = orders.copy()
    customers["acquisition_channel"] = normalizar_columna(customers["acquisition_channel"])
    orders["channel"] = normalizar_columna(orders["channel"], ALIAS_CHANNEL)
    orders["payment_method"] = normalizar_columna(orders["payment_method"], ALIAS_PAYMENT)
    return customers, orders


# --------------------------------------------------------------------------
# 3. Integridad referencial
# --------------------------------------------------------------------------

def validar_integridad_referencial(orders, order_items, customers, products):
    """Devuelve un dict con las filas que referencian un ID inexistente
    en su tabla maestra correspondiente."""
    return {
        "clientes_invalidos_en_orders": orders[~orders["customer_id"].isin(customers["customer_id"])],
        "ordenes_invalidas_en_items": order_items[~order_items["order_id"].isin(orders["order_id"])],
        "productos_invalidos_en_items": order_items[~order_items["product_id"].isin(products["product_id"])],
    }


# --------------------------------------------------------------------------
# 4. Consistencia estado/cantidad
# --------------------------------------------------------------------------

def corregir_cantidades(orders: pd.DataFrame, order_items: pd.DataFrame):
    """
    Aplica las reglas de negocio sobre `quantity` según el estado de la
    orden, y marca como REVISION las órdenes con una combinación
    estado/cantidad sin corrección obvia.

    A diferencia del enfoque original en Apps Script (que cruzaba por
    posición de fila asumiendo IDs secuenciales), acá se hace un merge
    real por order_id, así que funciona sin importar el orden de las
    filas.
    """
    items = order_items.merge(orders[["order_id", "order_status"]], on="order_id", how="left")

    estado = items["order_status"]
    cantidad = items["quantity"]

    mask_entregado_negativo = estado.isin(["DELIVERED", "IN_TRANSIT"]) & (cantidad < 0)
    items.loc[mask_entregado_negativo, "quantity"] = items.loc[mask_entregado_negativo, "quantity"].abs()

    mask_cancelado = estado == "CANCELED"
    items.loc[mask_cancelado, "quantity"] = 0

    mask_devuelto_positivo = (estado == "RETURNED") & (cantidad > 0)
    items.loc[mask_devuelto_positivo, "quantity"] = -items.loc[mask_devuelto_positivo, "quantity"]

    mask_revision = estado.isin(["DELIVERED", "IN_TRANSIT", "RETURNED"]) & (cantidad == 0)
    ordenes_a_revision = items.loc[mask_revision, "order_id"].unique()

    orders_corregido = orders.copy()
    orders_corregido.loc[orders_corregido["order_id"].isin(ordenes_a_revision), "order_status"] = "REVISION"

    order_items_corregido = items.drop(columns=["order_status"])
    return orders_corregido, order_items_corregido, len(ordenes_a_revision)


# --------------------------------------------------------------------------
# 5. Corrección de first_order_date
# --------------------------------------------------------------------------

def corregir_first_order_date(customers: pd.DataFrame, orders: pd.DataFrame):
    """Recalcula first_order_date como la fecha mínima real de órdenes
    de cada cliente."""
    fecha_minima = orders.groupby("customer_id")["order_date"].min()
    customers_corregido = customers.copy()
    customers_corregido["first_order_date"] = customers_corregido["customer_id"].map(fecha_minima)
    actualizados = int(customers_corregido["first_order_date"].notna().sum())
    return customers_corregido, actualizados


# --------------------------------------------------------------------------
# 6. Tabla analítica: Ideal vs. Real
# --------------------------------------------------------------------------

def construir_tabla_analitica(orders: pd.DataFrame, order_items: pd.DataFrame, products: pd.DataFrame):
    """Devuelve (resumen_comparativo, detalle_por_producto)."""
    items = order_items.merge(orders[["order_id", "order_status"]], on="order_id", how="left")
    items["revenue"] = items["quantity"].abs() * items["unit_price"]
    items["costo"] = items["quantity"].abs() * items["cost"]

    ideal = items[items["quantity"] > 0]
    real = items[(items["quantity"] > 0) & (~items["order_status"].isin(ESTADOS_EXCLUIDOS_REAL))]

    resumen = pd.DataFrame({
        "métrica": ["Unidades Vendidas", "Revenue Total", "Costo Total", "Margen Bruto ($)"],
        "ideal": [
            ideal["quantity"].sum(), ideal["revenue"].sum(),
            ideal["costo"].sum(), ideal["revenue"].sum() - ideal["costo"].sum(),
        ],
        "real": [
            real["quantity"].sum(), real["revenue"].sum(),
            real["costo"].sum(), real["revenue"].sum() - real["costo"].sum(),
        ],
    })
    resumen["diferencia (fuga)"] = resumen["ideal"] - resumen["real"]

    detalle = (
        real.merge(products[["product_id", "product_name", "category"]], on="product_id", how="left")
        .groupby(["product_id", "product_name", "category"], as_index=False)
        .agg(unidades=("quantity", "sum"), revenue=("revenue", "sum"), costo=("costo", "sum"))
    )
    detalle["margen_$"] = detalle["revenue"] - detalle["costo"]
    detalle["margen_%"] = np.where(detalle["revenue"] > 0, detalle["margen_$"] / detalle["revenue"], 0)

    return resumen, detalle


# --------------------------------------------------------------------------
# 7. Margen por canal de venta
# --------------------------------------------------------------------------

def margen_promedio_por_canal(orders: pd.DataFrame, order_items: pd.DataFrame) -> pd.Series:
    items = order_items.merge(orders[["order_id", "order_status", "channel"]], on="order_id", how="left")
    items = items[(items["quantity"] > 0) & (~items["order_status"].isin(ESTADOS_EXCLUIDOS_REAL))]
    items["margen_orden"] = items["quantity"] * (items["unit_price"] - items["cost"])

    return (
        items.groupby(["channel", "order_id"])["margen_orden"].sum()
        .groupby("channel").mean()
        .sort_values(ascending=False)
    )


# --------------------------------------------------------------------------
# 8. Clientes nuevos vs. recurrentes por mes
# --------------------------------------------------------------------------

def clientes_nuevos_vs_recurrentes(orders: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    ordenes_reales = orders[~orders["order_status"].isin(ESTADOS_EXCLUIDOS_REAL)].merge(
        customers[["customer_id", "first_order_date"]], on="customer_id", how="left"
    )
    ordenes_reales["mes"] = ordenes_reales["order_date"].dt.to_period("M")
    ordenes_reales["tipo_cliente"] = np.where(
        ordenes_reales["order_date"].dt.date > ordenes_reales["first_order_date"].dt.date,
        "Recurrente", "Nuevo"
    )
    return (
        ordenes_reales.groupby(["mes", "tipo_cliente"])["customer_id"]
        .nunique()
        .unstack(fill_value=0)
    )


# --------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------

def graficar_estados(orders: pd.DataFrame, output_dir: Path) -> None:
    plt.figure(figsize=(7, 4))
    orders["order_status"].value_counts().plot(kind="bar", color="steelblue")
    plt.title("Distribución de estados de orden (post-corrección)")
    plt.xlabel("Estado")
    plt.ylabel("Cantidad de órdenes")
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(output_dir / "distribucion_estados.png", dpi=120)
    plt.close()


def graficar_margen_por_categoria(detalle_productos: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    margen_por_categoria = (
        detalle_productos.groupby("category")
        .agg(revenue=("revenue", "sum"), costo=("costo", "sum"))
        .assign(margen_pct=lambda d: (d["revenue"] - d["costo"]) / d["revenue"])
        .sort_values("margen_pct", ascending=False)
    )

    plt.figure(figsize=(8, 4))
    plt.bar(margen_por_categoria.index, margen_por_categoria["margen_pct"] * 100, color="seagreen")
    plt.ylabel("Margen neto (%)")
    plt.title("Margen neto por categoría")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(output_dir / "margen_por_categoria.png", dpi=120)
    plt.close()

    return margen_por_categoria


def graficar_clientes_nuevos_vs_recurrentes(clientes_por_mes: pd.DataFrame, output_dir: Path) -> None:
    clientes_por_mes.plot(kind="bar", figsize=(9, 4), color=["steelblue", "darkorange"])
    plt.title("Clientes nuevos vs. recurrentes por mes")
    plt.ylabel("Cantidad de clientes")
    plt.xlabel("Mes")
    plt.tight_layout()
    plt.savefig(output_dir / "clientes_nuevos_vs_recurrentes.png", dpi=120)
    plt.close()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    if not (DATA_DIR / "orders.csv").exists():
        print("No se encontraron CSV en data/: generando dataset sintético de referencia.")
        generar_datos_sample(DATA_DIR)
    else:
        print("Usando los CSV encontrados en data/.")

    customers, orders, order_items, products = cargar_datos()
    print(f"customers: {len(customers)} | orders: {len(orders)} | "
          f"order_items: {len(order_items)} | products: {len(products)}")

    customers, orders = normalizar_dimensiones(customers, orders)
    print("Canales de venta:", sorted(orders["channel"].unique()))
    print("Métodos de pago:", sorted(orders["payment_method"].unique()))

    reporte_integridad = validar_integridad_referencial(orders, order_items, customers, products)
    for nombre, df in reporte_integridad.items():
        print(f"{nombre}: {len(df)} filas con referencia inválida")

    orders, order_items, n_revision = corregir_cantidades(orders, order_items)
    print(f"Órdenes marcadas como REVISION: {n_revision}")

    customers, actualizados = corregir_first_order_date(customers, orders)
    print(f"Clientes con first_order_date actualizado: {actualizados} de {len(customers)}")

    resumen, detalle_productos = construir_tabla_analitica(orders, order_items, products)
    print("\nResumen comparativo Ideal vs. Real:")
    print(resumen.to_string(index=False))

    print("\nTop 10 productos por revenue:")
    print(detalle_productos.sort_values("revenue", ascending=False).head(10)[
        ["product_id", "product_name", "category", "revenue"]
    ].to_string(index=False))

    margen_canal = margen_promedio_por_canal(orders, order_items)
    print("\nMargen promedio por orden, según canal:")
    print(margen_canal.round(2))

    clientes_por_mes = clientes_nuevos_vs_recurrentes(orders, customers)
    print("\nClientes nuevos vs. recurrentes por mes:")
    print(clientes_por_mes)

    graficar_estados(orders, OUTPUT_DIR)
    margen_por_categoria = graficar_margen_por_categoria(detalle_productos, OUTPUT_DIR)
    graficar_clientes_nuevos_vs_recurrentes(clientes_por_mes, OUTPUT_DIR)

    print("\nMargen neto por categoría:")
    print(margen_por_categoria)

    resumen.to_csv(OUTPUT_DIR / "resumen_ideal_vs_real.csv", index=False)
    detalle_productos.to_csv(OUTPUT_DIR / "detalle_por_producto.csv", index=False)

    print(f"\nGráficos y tablas de resultados guardados en {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()

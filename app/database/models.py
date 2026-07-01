from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, Text, Date, Enum as SAEnum, Index
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
from datetime import datetime as _dt
import enum

Base = declarative_base()


class RolUsuario(str, enum.Enum):
    admin = "admin"
    cajero = "cajero"
    farmaceutico = "farmaceutico"
    cajero_prueba = "cajero_prueba"


class MetodoPago(str, enum.Enum):
    efectivo = "efectivo"
    tarjeta = "tarjeta"
    transferencia = "transferencia"
    mixto = "mixto"


class EstadoVenta(str, enum.Enum):
    completada = "completada"
    cancelada = "cancelada"
    devolucion = "devolucion"


class TipoMovimiento(str, enum.Enum):
    entrada = "entrada"
    salida = "salida"
    ajuste = "ajuste"
    devolucion = "devolucion"


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nombre = Column(String(100), nullable=False)
    rol = Column(SAEnum(RolUsuario), default=RolUsuario.cajero)
    telefono = Column(String(20))
    email = Column(String(100))
    activo = Column(Boolean, default=True)
    foto_url = Column(String(500), nullable=True)
    creado_en = Column(DateTime, default=_dt.now)

    ventas = relationship("Venta", back_populates="usuario")
    movimientos = relationship("MovimientoStock", back_populates="usuario")
    cortes = relationship("CortesCaja", back_populates="usuario")
    auditoria = relationship("AuditoriaLog", back_populates="usuario")


class Categoria(Base):
    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False, unique=True)
    descripcion = Column(Text)

    productos = relationship("Producto", back_populates="categoria")


class Proveedor(Base):
    __tablename__ = "proveedores"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    contacto = Column(String(100))
    telefono = Column(String(20))
    email = Column(String(100))
    direccion = Column(Text)
    rfc = Column(String(20))
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=_dt.now)

    productos = relationship("Producto", back_populates="proveedor")
    compras = relationship("Compra", back_populates="proveedor")


class Producto(Base):
    __tablename__ = "productos"

    id = Column(Integer, primary_key=True)
    codigo_barras = Column(String(50), unique=True, index=True)
    nombre = Column(String(200), nullable=False)
    nombre_generico = Column(String(200))
    marca = Column(String(100))
    categoria_id = Column(Integer, ForeignKey("categorias.id"))
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"))
    precio_compra = Column(Float, default=0.0)
    precio_venta = Column(Float, nullable=False)
    aplica_iva = Column(Boolean, default=False)
    stock = Column(Integer, default=0)
    stock_minimo = Column(Integer, default=10)
    requiere_receta = Column(Boolean, default=False)
    sustancia_controlada = Column(Boolean, default=False)
    presentacion = Column(String(50))   # tableta, jarabe, cápsula, inyectable…
    concentracion = Column(String(50))  # 500mg, 250mg/5ml, 10mg/ml…
    contenido = Column(String(50))      # 30 tab, 120ml, 10 amp…
    descripcion = Column(Text)
    imagen_url = Column(String(500))
    venta_fraccionada = Column(Boolean, default=False)
    unidades_por_caja = Column(Integer, default=1)
    precio_pieza = Column(Float, default=0.0)
    unidad_pieza = Column(String(30), default="pieza")
    unidad_caja = Column(String(30), default="caja")
    piezas_sueltas = Column(Integer, default=0)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=_dt.now)
    actualizado_en = Column(DateTime, default=_dt.now, onupdate=_dt.now)

    categoria = relationship("Categoria", back_populates="productos")
    proveedor = relationship("Proveedor", back_populates="productos")
    lotes = relationship("Lote", back_populates="producto", cascade="all, delete-orphan")
    items_venta = relationship("ItemVenta", back_populates="producto")
    movimientos = relationship("MovimientoStock", back_populates="producto")


class Lote(Base):
    """Lotes de medicamentos con fecha de vencimiento"""
    __tablename__ = "lotes"

    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    numero_lote = Column(String(50))
    fecha_vencimiento = Column(Date)
    cantidad = Column(Integer, default=0)
    precio_compra = Column(Float, default=0.0)
    creado_en = Column(DateTime, default=_dt.now)

    producto = relationship("Producto", back_populates="lotes")
    items_compra = relationship("ItemCompra", back_populates="lote")


class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    telefono = Column(String(20))
    email = Column(String(100))
    rfc = Column(String(20))
    direccion = Column(Text)
    limite_credito = Column(Float, default=0.0)
    saldo_deuda = Column(Float, default=0.0)
    puntos_acumulados = Column(Float, default=0.0)
    puntos_canjeados = Column(Float, default=0.0)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=_dt.now)

    ventas = relationship("Venta", back_populates="cliente")


class Venta(Base):
    __tablename__ = "ventas"

    id = Column(Integer, primary_key=True)
    folio = Column(String(20), unique=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    subtotal = Column(Float, default=0.0)
    descuento = Column(Float, default=0.0)
    iva = Column(Float, default=0.0)
    total = Column(Float, nullable=False)
    metodo_pago = Column(SAEnum(MetodoPago), default=MetodoPago.efectivo)
    monto_pagado = Column(Float, default=0.0)
    cambio = Column(Float, default=0.0)
    estado = Column(SAEnum(EstadoVenta), default=EstadoVenta.completada)
    notas = Column(Text)
    creado_en = Column(DateTime, default=_dt.now)
    eliminado = Column(Boolean, default=False)
    eliminado_en = Column(DateTime, nullable=True)
    facturada = Column(Boolean, default=False)
    cfdi_global_id = Column(Integer, ForeignKey("cfdi_facturas_globales.id"), nullable=True)

    usuario = relationship("Usuario", back_populates="ventas")
    cliente = relationship("Cliente", back_populates="ventas")
    items = relationship("ItemVenta", back_populates="venta", cascade="all, delete-orphan")
    cfdi_global = relationship("CfdiFacturaGlobal", back_populates="ventas")

    __table_args__ = (
        Index("ix_ventas_creado_en",  "creado_en"),
        Index("ix_ventas_usuario_id", "usuario_id"),
        Index("ix_ventas_estado",     "estado"),
        Index("ix_ventas_eliminado",  "eliminado"),
        Index("ix_ventas_facturada",  "facturada"),
    )


class ItemVenta(Base):
    __tablename__ = "items_venta"

    id = Column(Integer, primary_key=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)
    descuento = Column(Float, default=0.0)
    subtotal = Column(Float, nullable=False)

    venta = relationship("Venta", back_populates="items")
    producto = relationship("Producto", back_populates="items_venta")


class CfdiFacturaGlobal(Base):
    """Factura global mensual (CFDI 4.0) timbrada vía Facturama, concentra ventas del periodo"""
    __tablename__ = "cfdi_facturas_globales"

    id = Column(Integer, primary_key=True)
    mes = Column(Integer, nullable=False)
    anio = Column(Integer, nullable=False)
    subtotal = Column(Float, default=0.0)
    iva = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    num_ventas = Column(Integer, default=0)
    estado = Column(String(20), default="timbrada")  # timbrada | cancelada | error
    facturama_id = Column(String(50))
    uuid_fiscal = Column(String(50))
    serie = Column(String(10))
    folio = Column(String(20))
    xml_path = Column(String(300))
    pdf_path = Column(String(300))
    error_mensaje = Column(Text)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    creado_en = Column(DateTime, default=_dt.now)
    cancelado_en = Column(DateTime, nullable=True)

    usuario = relationship("Usuario")
    ventas = relationship("Venta", back_populates="cfdi_global")

    __table_args__ = (
        Index("ix_cfdi_global_periodo", "anio", "mes"),
    )


class FacturaCompra(Base):
    """Control de facturas (CFDI) recibidas de proveedores por compra de medicamentos"""
    __tablename__ = "facturas_compra"

    id = Column(Integer, primary_key=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    proveedor_nombre = Column(String(150), nullable=False)
    proveedor_rfc = Column(String(20))
    folio_fiscal = Column(String(50))  # UUID del CFDI emitido por el proveedor
    fecha_factura = Column(Date, nullable=False)
    subtotal = Column(Float, default=0.0)
    iva = Column(Float, default=0.0)
    total = Column(Float, nullable=False)
    concepto = Column(Text)
    xml_path = Column(String(300))
    pdf_path = Column(String(300))
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    creado_en = Column(DateTime, default=_dt.now)

    proveedor = relationship("Proveedor")
    usuario = relationship("Usuario")

    __table_args__ = (
        Index("ix_facturas_compra_fecha", "fecha_factura"),
    )


class Compra(Base):
    """Entrada de mercancía de proveedores"""
    __tablename__ = "compras"

    id = Column(Integer, primary_key=True)
    folio = Column(String(20), unique=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"))
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    total = Column(Float, default=0.0)
    notas = Column(Text)
    creado_en = Column(DateTime, default=_dt.now)

    proveedor = relationship("Proveedor", back_populates="compras")
    items = relationship("ItemCompra", back_populates="compra", cascade="all, delete-orphan")


class ItemCompra(Base):
    __tablename__ = "items_compra"

    id = Column(Integer, primary_key=True)
    compra_id = Column(Integer, ForeignKey("compras.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    lote_id = Column(Integer, ForeignKey("lotes.id"), nullable=True)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)
    subtotal = Column(Float, nullable=False)

    compra = relationship("Compra", back_populates="items")
    lote = relationship("Lote", back_populates="items_compra")


class CortesCaja(Base):
    """Corte de caja - apertura y cierre de turno"""
    __tablename__ = "cortes_caja"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    monto_apertura = Column(Float, default=0.0)
    monto_cierre = Column(Float, nullable=True)
    total_ventas = Column(Float, default=0.0)
    total_efectivo = Column(Float, default=0.0)
    total_tarjeta = Column(Float, default=0.0)
    total_transferencia = Column(Float, default=0.0)
    total_costo = Column(Float, default=0.0)
    num_ventas = Column(Integer, default=0)
    abierto_en = Column(DateTime, default=_dt.now)
    cerrado_en = Column(DateTime, nullable=True)
    notas = Column(Text)

    usuario = relationship("Usuario", back_populates="cortes")
    retiros = relationship("RetiroCaja", back_populates="corte", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_cortes_usuario_id",  "usuario_id"),
        Index("ix_cortes_cerrado_en",  "cerrado_en"),
        Index("ix_cortes_abierto_en",  "abierto_en"),
    )


class RetiroCaja(Base):
    """Retiro de efectivo de caja durante un turno (solo admin)"""
    __tablename__ = "retiros_caja"

    id = Column(Integer, primary_key=True)
    corte_id = Column(Integer, ForeignKey("cortes_caja.id"), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    monto = Column(Float, nullable=False)
    concepto = Column(Text)
    tipo = Column(SAEnum("personal", "inversion", name="tipo_retiro"), default="personal")
    creado_en = Column(DateTime, default=_dt.now)

    corte = relationship("CortesCaja", back_populates="retiros")
    usuario = relationship("Usuario")


class MovimientoStock(Base):
    """Historial de todos los movimientos de inventario"""
    __tablename__ = "movimientos_stock"

    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    tipo = Column(SAEnum(TipoMovimiento), nullable=False)
    cantidad = Column(Integer, nullable=False)
    stock_anterior = Column(Integer)
    stock_nuevo = Column(Integer)
    referencia_id = Column(Integer)
    referencia_tipo = Column(String(50))
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    notas = Column(Text)
    creado_en = Column(DateTime, default=_dt.now)

    producto = relationship("Producto", back_populates="movimientos")
    usuario = relationship("Usuario", back_populates="movimientos")


class AuditoriaLog(Base):
    """Log de todas las acciones importantes"""
    __tablename__ = "auditoria_log"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    accion = Column(String(100), nullable=False)
    tabla = Column(String(50))
    registro_id = Column(Integer)
    detalles = Column(Text)
    creado_en = Column(DateTime, default=_dt.now)

    usuario = relationship("Usuario", back_populates="auditoria")


class Configuracion(Base):
    """Configuraciones del sistema key-value"""
    __tablename__ = "configuracion"

    id = Column(Integer, primary_key=True)
    clave = Column(String(100), unique=True, nullable=False)
    valor = Column(Text)
    actualizado_en = Column(DateTime, default=_dt.now, onupdate=_dt.now)


class CategoriaWeb(Base):
    """Categorías del catálogo web/app — independientes del POS."""
    __tablename__ = "categorias_web"

    id        = Column(Integer, primary_key=True)
    nombre    = Column(String(100), nullable=False, unique=True)
    descripcion = Column(Text, nullable=True)
    imagen_url  = Column(String(500), nullable=True)
    orden       = Column(Integer, default=0)
    activo      = Column(Boolean, default=True)

    productos = relationship("ProductoWeb", back_populates="categoria")


class ProductoWeb(Base):
    """Catálogo web/app — independiente del inventario POS."""
    __tablename__ = "productos_web"

    id               = Column(Integer, primary_key=True)
    nombre           = Column(String(200), nullable=False)
    nombre_generico  = Column(String(200), nullable=True)
    marca            = Column(String(100), nullable=True)
    descripcion      = Column(Text, nullable=True)
    categoria_id     = Column(Integer, ForeignKey("categorias_web.id"), nullable=True)
    precio           = Column(Float, nullable=False)
    precio_tachado   = Column(Float, nullable=True)
    imagen_url       = Column(String(500), nullable=True)
    presentacion     = Column(String(100), nullable=True)
    concentracion    = Column(String(100), nullable=True)
    contenido        = Column(String(100), nullable=True)
    requiere_receta  = Column(Boolean, default=False)
    disponible       = Column(Boolean, default=True)
    destacado        = Column(Boolean, default=False)
    orden            = Column(Integer, default=0)
    creado_en        = Column(DateTime, default=_dt.now)
    actualizado_en   = Column(DateTime, default=_dt.now, onupdate=_dt.now)

    categoria = relationship("CategoriaWeb", back_populates="productos")


class EstadoPedidoWeb(str, enum.Enum):
    pendiente   = "pendiente"
    confirmado  = "confirmado"
    preparando  = "preparando"
    listo       = "listo"
    en_camino   = "en_camino"
    entregado   = "entregado"
    cancelado   = "cancelado"


class ClienteApp(Base):
    """Usuarios de la app móvil/web — distintos de los clientes del POS."""
    __tablename__ = "clientes_app"

    id            = Column(Integer, primary_key=True)
    nombre        = Column(String(150), nullable=False)
    email         = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    google_id     = Column(String(100), unique=True, nullable=True, index=True)
    telefono      = Column(String(20), nullable=True)
    foto_url      = Column(String(500), nullable=True)
    # "cliente_app" (default) | "admin_web" (gestiona catálogo web)
    rol           = Column(String(20), default="cliente_app", nullable=False)
    activo        = Column(Boolean, default=True)
    creado_en     = Column(DateTime, default=_dt.now)

    pedidos = relationship("PedidoWeb", back_populates="cliente_app")


class PedidoWeb(Base):
    """Orden creada desde la app móvil/web."""
    __tablename__ = "pedidos_web"

    id                 = Column(Integer, primary_key=True)
    cliente_app_id     = Column(Integer, ForeignKey("clientes_app.id"), nullable=False)
    estado             = Column(SAEnum(EstadoPedidoWeb), default=EstadoPedidoWeb.pendiente)
    total              = Column(Float, nullable=False)
    direccion_entrega  = Column(Text, nullable=True)
    notas              = Column(Text, nullable=True)
    referencia_venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=True)
    creado_en          = Column(DateTime, default=_dt.now)
    actualizado_en     = Column(DateTime, default=_dt.now, onupdate=_dt.now)

    cliente_app = relationship("ClienteApp", back_populates="pedidos")
    items       = relationship("PedidoWebItem", back_populates="pedido", cascade="all, delete-orphan")


class PedidoWebItem(Base):
    __tablename__ = "pedidos_web_items"

    id              = Column(Integer, primary_key=True)
    pedido_id       = Column(Integer, ForeignKey("pedidos_web.id"), nullable=False)
    producto_id     = Column(Integer, ForeignKey("productos_web.id"), nullable=False)
    cantidad        = Column(Integer, nullable=False)
    precio_unitario = Column(Float, nullable=False)
    subtotal        = Column(Float, nullable=False)

    pedido   = relationship("PedidoWeb", back_populates="items")
    producto = relationship("ProductoWeb")


class SexoPaciente(str, enum.Enum):
    masculino = "masculino"
    femenino = "femenino"
    otro = "otro"


class Paciente(Base):
    __tablename__ = "pacientes"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(200), nullable=False, index=True)
    fecha_nacimiento = Column(Date, nullable=True)
    sexo = Column(SAEnum(SexoPaciente), nullable=True)
    telefono = Column(String(20))
    email = Column(String(100))
    direccion = Column(Text)
    alergias = Column(Text)
    antecedentes = Column(Text)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=_dt.now)

    registros = relationship("RegistroClinico", back_populates="paciente", cascade="all, delete-orphan")
    cliente = relationship("Cliente")


class RegistroClinico(Base):
    __tablename__ = "registros_clinicos"

    id = Column(Integer, primary_key=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    fecha = Column(DateTime, default=_dt.now)
    presion_sistolica = Column(Integer)
    presion_diastolica = Column(Integer)
    pulso = Column(Integer)
    temperatura = Column(Float)
    peso = Column(Float)
    talla = Column(Float)
    glucosa = Column(Float)
    saturacion_o2 = Column(Float)
    motivo = Column(Text)
    diagnostico = Column(Text)
    tratamiento = Column(Text)
    notas = Column(Text)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, default=_dt.now)

    paciente = relationship("Paciente", back_populates="registros")
    usuario = relationship("Usuario")


# ─── Cuentas por cobrar ────────────────────────────────────────────────────────
class PagoCredito(Base):
    __tablename__ = "pagos_credito"
    id = Column(Integer, primary_key=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    monto = Column(Float, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    notas = Column(Text)
    creado_en = Column(DateTime, default=_dt.now)
    cliente = relationship("Cliente")
    usuario = relationship("Usuario")


# ─── Recetas médicas ───────────────────────────────────────────────────────────
class Receta(Base):
    __tablename__ = "recetas"
    id = Column(Integer, primary_key=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=True)
    medico_nombre = Column(String(200))
    cedula = Column(String(50))
    num_receta = Column(String(100))
    fecha_receta = Column(Date)
    notas = Column(Text)
    creado_en = Column(DateTime, default=_dt.now)
    venta = relationship("Venta")


# ─── Promociones ───────────────────────────────────────────────────────────────
class TipoPromocion(str, enum.Enum):
    porcentaje = "porcentaje"
    monto_fijo = "monto_fijo"
    dos_x_uno = "dos_x_uno"
    tres_x_dos = "tres_x_dos"


class Promocion(Base):
    __tablename__ = "promociones"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(200), nullable=False)
    tipo = Column(SAEnum(TipoPromocion), nullable=False)
    valor = Column(Float, default=0.0)
    aplica_a = Column(String(50), default="todos")
    aplica_id = Column(Integer, nullable=True)
    fecha_inicio = Column(Date, nullable=True)
    fecha_fin = Column(Date, nullable=True)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=_dt.now)


# ─── Órdenes de compra ─────────────────────────────────────────────────────────
class EstadoOrdenCompra(str, enum.Enum):
    borrador = "borrador"
    enviada = "enviada"
    recibida = "recibida"
    cancelada = "cancelada"


class OrdenCompra(Base):
    __tablename__ = "ordenes_compra"
    id = Column(Integer, primary_key=True)
    folio = Column(String(20), unique=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    proveedor_texto = Column(String(200), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    estado = Column(SAEnum(EstadoOrdenCompra), default=EstadoOrdenCompra.borrador)
    notas = Column(Text)
    total_estimado = Column(Float, default=0.0)
    creado_en = Column(DateTime, default=_dt.now)
    enviada_en = Column(DateTime, nullable=True)
    recibida_en = Column(DateTime, nullable=True)
    proveedor = relationship("Proveedor")
    usuario = relationship("Usuario")
    items = relationship("ItemOrdenCompra", back_populates="orden", cascade="all, delete-orphan")


class ItemOrdenCompra(Base):
    __tablename__ = "items_orden_compra"
    id = Column(Integer, primary_key=True)
    orden_id = Column(Integer, ForeignKey("ordenes_compra.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Float, default=0.0)
    subtotal = Column(Float, default=0.0)
    orden = relationship("OrdenCompra", back_populates="items")
    producto = relationship("Producto")


# ─── Agenda de citas ───────────────────────────────────────────────────────────
class EstadoCita(str, enum.Enum):
    programada = "programada"
    completada = "completada"
    cancelada = "cancelada"
    no_asistio = "no_asistio"


class Cita(Base):
    __tablename__ = "citas"
    id = Column(Integer, primary_key=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha_hora = Column(DateTime, nullable=False)
    tipo_servicio = Column(String(100))
    estado = Column(SAEnum(EstadoCita), default=EstadoCita.programada)
    nombre_paciente = Column(String(200))
    telefono = Column(String(20))
    notas = Column(Text)
    creado_en = Column(DateTime, default=_dt.now)
    paciente = relationship("Paciente")
    usuario = relationship("Usuario")


# ─── Inventario cíclico ────────────────────────────────────────────────────────
class EstadoSesionInventario(str, enum.Enum):
    en_progreso = "en_progreso"
    finalizada = "finalizada"
    cancelada = "cancelada"


class SesionInventario(Base):
    __tablename__ = "sesiones_inventario"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    estado = Column(SAEnum(EstadoSesionInventario), default=EstadoSesionInventario.en_progreso)
    notas = Column(Text)
    creado_en = Column(DateTime, default=_dt.now)
    finalizada_en = Column(DateTime, nullable=True)
    usuario = relationship("Usuario")
    conteos = relationship("ConteoInventario", back_populates="sesion", cascade="all, delete-orphan")


class ConteoInventario(Base):
    __tablename__ = "conteos_inventario"
    id = Column(Integer, primary_key=True)
    sesion_id = Column(Integer, ForeignKey("sesiones_inventario.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad_sistema = Column(Integer, default=0)
    cantidad_contada = Column(Integer, nullable=True)
    diferencia = Column(Integer, default=0)
    ajustado = Column(Boolean, default=False)
    sesion = relationship("SesionInventario", back_populates="conteos")
    producto = relationship("Producto")


# ─── Gastos / Egresos ──────────────────────────────────────────────────────────
class CategoriaGasto(str, enum.Enum):
    renta = "renta"
    servicios = "servicios"
    personal = "personal"
    compras = "compras"
    mantenimiento = "mantenimiento"
    otros = "otros"


class Gasto(Base):
    __tablename__ = "gastos"
    id = Column(Integer, primary_key=True)
    concepto = Column(String(200), nullable=False)
    monto = Column(Float, nullable=False)
    categoria = Column(SAEnum(CategoriaGasto), default=CategoriaGasto.otros)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    fecha = Column(Date, nullable=False)
    notas = Column(Text)
    comprobante_url = Column(String(500))
    creado_en = Column(DateTime, default=_dt.now)
    usuario = relationship("Usuario")


# ─── Historial de precios ──────────────────────────────────────────────────────
class HistorialPrecio(Base):
    __tablename__ = "historial_precios"
    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    precio_compra_anterior = Column(Float, nullable=True)
    precio_compra_nuevo = Column(Float, nullable=True)
    precio_venta_anterior = Column(Float, nullable=True)
    precio_venta_nuevo = Column(Float, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    notas = Column(Text)
    creado_en = Column(DateTime, default=_dt.now)
    producto = relationship("Producto")
    usuario = relationship("Usuario")

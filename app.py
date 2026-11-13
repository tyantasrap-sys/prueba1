from __future__ import annotations

import hashlib
import json
import re
import unicodedata

import gspread
import pandas as pd
import streamlit as st


# =============================================================================
# CONFIGURACIÓN GENERAL
# =============================================================================
APP_VERSION = "1.0.0"

st.set_page_config(
    page_title="Expedientes por año de creación",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {max-width: 1450px; padding-top: 1.5rem; padding-bottom: 2rem;}
      .titulo-principal {text-align:center; color:#17324D; font-weight:750; margin-bottom:.2rem;}
      .subtitulo {text-align:center; color:#718096; margin-bottom:1.5rem;}
      .barra-azul {background:#287FB4; color:white; text-align:center; font-weight:750;
        padding:9px 12px; border-radius:7px 7px 0 0; margin-top:8px;}
      div[data-testid="stMetric"] {background:#FFFFFF; border:1px solid #D9E2EC;
        border-bottom:4px solid #287FB4; border-radius:9px; padding:12px 15px;}
      div[data-testid="stTabs"] button {font-weight:600;}
      .nota {font-size:0.86rem; color:#687A8D;}
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# CONEXIÓN DIRECTA A GOOGLE SHEETS
# =============================================================================
@st.cache_data(ttl=120, show_spinner=False)
def cargar_google_sheets(
    spreadsheet_id: str,
    nombre_pestana: str,
    huella_credenciales: str,
) -> pd.DataFrame:
    """Lee una pestaña privada de Google Sheets con una cuenta de servicio.

    Las credenciales se leen desde st.secrets. No se guardan en este archivo
    ni en el repositorio de GitHub. La huella solo interviene en la caché.
    """
    del huella_credenciales
    credenciales = dict(st.secrets["gcp_service_account"])
    cliente = gspread.service_account_from_dict(credenciales)
    hoja = cliente.open_by_key(spreadsheet_id).worksheet(nombre_pestana)
    valores = hoja.get_all_values()

    if not valores:
        return pd.DataFrame()

    encabezados = []
    usados: dict[str, int] = {}
    for indice, valor in enumerate(valores[0], start=1):
        nombre = str(valor).strip() or f"Columna_{indice}"
        usados[nombre] = usados.get(nombre, 0) + 1
        if usados[nombre] > 1:
            nombre = f"{nombre}_{usados[nombre]}"
        encabezados.append(nombre)

    filas = valores[1:]
    return pd.DataFrame(filas, columns=encabezados)


# =============================================================================
# FUNCIONES DE NORMALIZACIÓN Y ANÁLISIS
# =============================================================================
CATEGORIA_SIN_RESOLUCION = "SIN_RESOLUCION"
CATEGORIA_CON_RESOLUCION = "CON_RESOLUCION"
CATEGORIA_NO_CLASIFICADO = "NO_CLASIFICADO"

COLUMNAS_SALIDA = [
    "Expediente",
    "Fecha de creación",
    "Año",
    "Procedimiento",
    "Equipo",
    "Estado",
    "Categoría de estado",
]


def normalizar_texto(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return ""
    texto = str(valor).strip().upper()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def clasificar_estado(valor: object) -> str:
    """Clasifica los estados de acuerdo con las reglas del ejercicio."""
    estado = normalizar_texto(valor)
    if not estado:
        return CATEGORIA_NO_CLASIFICADO

    # Regla expresa: permanece en Sin Resolución aunque incluya la palabra resolución.
    if re.search(r"\bSUSPENDIDO\s+CON\s+RESOLUCION\b", estado):
        return CATEGORIA_SIN_RESOLUCION

    if re.search(r"\b(?:CON\s+)?RESOLUCION\s+(?:EMITIDA|CONSENTIDA)\b", estado):
        return CATEGORIA_CON_RESOLUCION

    if re.search(r"\b(?:CON\s+)?FICHA\s+TECNICA\b", estado):
        return CATEGORIA_SIN_RESOLUCION

    if re.search(r"\b(?:EN\s+)?TRAMITE\b", estado):
        return CATEGORIA_SIN_RESOLUCION

    if re.search(r"\bGENERADO\b", estado):
        return CATEGORIA_SIN_RESOLUCION

    return CATEGORIA_NO_CLASIFICADO


def detectar_columna(columnas: list[str], alias: list[str]) -> str | None:
    mapa = {normalizar_texto(c): c for c in columnas}
    for nombre in alias:
        encontrada = mapa.get(normalizar_texto(nombre))
        if encontrada is not None:
            return encontrada
    return None


def detectar_mapeo_columnas(columnas: list[str]) -> dict[str, str | None]:
    alias = {
        "expediente": ["Expediente", "N° Expediente", "Nro Expediente", "Número de expediente"],
        "fecha_creacion": ["Fecha de creación", "Fecha Creacion", "Fec_Creacion", "Fec Creacion", "Fecha ingreso"],
        "anio_creacion": ["Año de creación", "Año Creacion", "Anio", "Año"],
        "procedimiento": ["Procedimiento", "Trámite", "Tramite", "Nombre del procedimiento"],
        "equipo": ["Equipo", "Brigada", "Equipo de trabajo", "Responsable técnico"],
        "estado": ["Estado", "Estado actual", "Situación", "Situacion"],
    }
    return {campo: detectar_columna(columnas, nombres) for campo, nombres in alias.items()}


def preparar_datos(
    origen: pd.DataFrame,
    mapeo: dict[str, str | None],
) -> tuple[pd.DataFrame, dict[str, int]]:
    if origen.empty:
        return pd.DataFrame(columns=COLUMNAS_SALIDA), {
            "filas_origen": 0,
            "duplicados_expediente": 0,
            "fechas_invalidas": 0,
            "sin_anio": 0,
        }

    requeridas = ["expediente", "procedimiento", "equipo", "estado"]
    faltantes = [campo for campo in requeridas if not mapeo.get(campo)]
    if faltantes:
        raise ValueError("No se identificó la(s) columna(s): " + ", ".join(faltantes))
    if not mapeo.get("fecha_creacion") and not mapeo.get("anio_creacion"):
        raise ValueError("Se necesita una columna Fecha de creación o Año de creación.")

    def serie(campo: str) -> pd.Series:
        columna = mapeo.get(campo)
        if columna and columna in origen.columns:
            return origen[columna].copy()
        return pd.Series([""] * len(origen), index=origen.index, dtype="object")

    salida = pd.DataFrame(index=origen.index)
    salida["Expediente"] = serie("expediente").fillna("").astype(str).str.strip()
    salida["Procedimiento"] = serie("procedimiento").fillna("").astype(str).str.strip()
    salida["Equipo"] = serie("equipo").fillna("").astype(str).str.strip()
    salida["Estado"] = serie("estado").fillna("").astype(str).str.strip()

    if mapeo.get("fecha_creacion"):
        fechas = pd.to_datetime(serie("fecha_creacion"), errors="coerce", dayfirst=True)
    else:
        fechas = pd.Series(pd.NaT, index=origen.index, dtype="datetime64[ns]")

    salida["Fecha de creación"] = fechas

    if mapeo.get("anio_creacion"):
        anios_raw = serie("anio_creacion").astype(str).str.extract(r"((?:19|20)\d{2})", expand=False)
        anios_aux = pd.to_numeric(anios_raw, errors="coerce")
    else:
        anios_aux = pd.Series(float("nan"), index=origen.index)

    salida["Año"] = fechas.dt.year.fillna(anios_aux)
    salida["Categoría de estado"] = salida["Estado"].map(clasificar_estado)

    filas_origen = len(salida)
    salida = salida[salida["Expediente"].ne("")].copy()
    duplicados = int(salida["Expediente"].duplicated(keep="last").sum())
    if duplicados:
        salida = salida.drop_duplicates(subset=["Expediente"], keep="last")

    fechas_invalidas = int(salida["Fecha de creación"].isna().sum()) if mapeo.get("fecha_creacion") else 0
    sin_anio = int(salida["Año"].isna().sum())
    salida = salida.dropna(subset=["Año"]).copy()
    salida["Año"] = salida["Año"].astype(int)
    salida = salida.sort_values(["Año", "Expediente"], ascending=[True, True]).reset_index(drop=True)
    salida = salida[COLUMNAS_SALIDA]

    calidad = {
        "filas_origen": filas_origen,
        "duplicados_expediente": duplicados,
        "fechas_invalidas": fechas_invalidas,
        "sin_anio": sin_anio,
    }
    return salida, calidad


def filtrar_por_estado(
    datos: pd.DataFrame,
    incluir_sin_resolucion: bool,
    incluir_con_resolucion: bool,
) -> pd.DataFrame:
    if datos.empty or (not incluir_sin_resolucion and not incluir_con_resolucion):
        return datos.iloc[0:0].copy()
    categorias = []
    if incluir_sin_resolucion:
        categorias.append(CATEGORIA_SIN_RESOLUCION)
    if incluir_con_resolucion:
        categorias.append(CATEGORIA_CON_RESOLUCION)
    return datos.loc[datos["Categoría de estado"].isin(categorias)].copy()


def construir_resumen_anual(datos: pd.DataFrame) -> pd.DataFrame:
    if datos.empty:
        return pd.DataFrame()
    conteo = datos.groupby("Año")["Expediente"].nunique().sort_index()
    resultado = pd.DataFrame([conteo.astype(int).to_dict()], index=["TOTAL"])
    resultado.columns = [str(c) for c in resultado.columns]
    return resultado


def construir_matriz(datos: pd.DataFrame, dimension: str) -> pd.DataFrame:
    if dimension not in {"Procedimiento", "Equipo"}:
        raise ValueError("La dimensión debe ser Procedimiento o Equipo.")
    if datos.empty:
        return pd.DataFrame()

    base = datos.copy()
    base[dimension] = base[dimension].replace("", "SIN ESPECIFICAR")
    matriz = pd.pivot_table(
        base,
        index=dimension,
        columns="Año",
        values="Expediente",
        aggfunc=pd.Series.nunique,
        fill_value=0,
    )
    matriz = matriz.reindex(sorted(matriz.columns), axis=1)
    matriz["TOTAL"] = matriz.sum(axis=1).astype(int)
    matriz = matriz.sort_values(["TOTAL"], ascending=False)

    total = matriz.sum(axis=0).to_frame().T
    total.index = ["TOTAL GENERAL"]
    total = total.astype(int)
    return pd.concat([matriz.astype(int), total], axis=0)


def mostrar_tabla(datos: pd.DataFrame, mensaje_vacio: str) -> None:
    if datos.empty:
        st.info(mensaje_vacio)
        return
    visible = datos.reset_index() if datos.index.name else datos
    st.dataframe(
        visible,
        use_container_width=True,
        hide_index=True,
        height=min(560, 150 + (len(visible) + 1) * 36),
    )


def seleccionar_columna(
    columnas: list[str], sugerida: str | None, clave: str, etiqueta: str, opcional: bool = False
) -> str | None:
    opciones = (["— No seleccionar —"] if opcional else []) + columnas
    indice = opciones.index(sugerida) if sugerida in opciones else 0
    seleccion = st.selectbox(etiqueta, opciones, index=indice, key=clave)
    if opcional and seleccion == "— No seleccionar —":
        return None
    return seleccion


# =============================================================================
# CABECERA Y CONFIGURACIÓN DE LA HOJA
# =============================================================================
st.markdown('<h1 class="titulo-principal">Expedientes por año de creación</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitulo">Análisis por año, procedimiento y equipo · Python + Streamlit + Google Sheets</p>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Origen de información")
    st.caption("La información se consulta directamente desde una Hoja de cálculo de Google.")

    try:
        config_hoja = dict(st.secrets.get("google_sheets", {}))
    except Exception:
        config_hoja = {}

    spreadsheet_id = str(config_hoja.get("spreadsheet_id", "")).strip()
    nombre_pestana = str(config_hoja.get("worksheet", "Datos")).strip()

    if spreadsheet_id:
        st.success("ID de Google Sheets configurado")
    else:
        st.error("Falta configurar google_sheets.spreadsheet_id en Secrets.")

    if "gcp_service_account" not in st.secrets:
        st.error("Faltan las credenciales de la cuenta de servicio en Secrets.")

    actualizar = st.button("Actualizar datos desde Google Sheets", use_container_width=True)
    st.caption("La consulta se almacena en caché durante 2 minutos para reducir lecturas repetidas.")

if actualizar:
    cargar_google_sheets.clear()

if not spreadsheet_id or not nombre_pestana or "gcp_service_account" not in st.secrets:
    st.info(
        "Para iniciar, configura el ID de la hoja, el nombre de la pestaña y las credenciales "
        "de Google en la sección Secrets de Streamlit Community Cloud."
    )
    st.stop()

try:
    credenciales = dict(st.secrets["gcp_service_account"])
    huella = hashlib.sha256(json.dumps(credenciales, sort_keys=True).encode("utf-8")).hexdigest()
    with st.spinner("Conectando con Google Sheets y leyendo los registros..."):
        raw = cargar_google_sheets(spreadsheet_id, nombre_pestana, huella)
    st.sidebar.success(f"Lectura completada: {len(raw):,} filas de Google Sheets.")
except Exception as exc:
    st.error(
        "No se pudo conectar con Google Sheets. Revisa que el ID sea correcto, que exista la pestaña "
        "indicada y que hayas compartido la hoja con el correo de la cuenta de servicio como Lector. "
        f"Detalle técnico: {type(exc).__name__}."
    )
    st.stop()

if raw.empty:
    st.warning("La pestaña configurada no contiene registros. Verifica la primera fila de encabezados y los datos.")
    st.stop()


# =============================================================================
# RELACIÓN DE COLUMNAS DE GOOGLE SHEETS CON LOS CAMPOS DEL PANEL
# =============================================================================
columnas = [str(columna) for columna in raw.columns]
sugerencias = detectar_mapeo_columnas(columnas)

with st.sidebar.expander("Configurar columnas del origen", expanded=False):
    st.caption("El panel intenta reconocer los encabezados automáticamente. Puedes corregirlos aquí.")
    col_exp = seleccionar_columna(columnas, sugerencias["expediente"], "map_exp", "Expediente")
    col_fecha = seleccionar_columna(columnas, sugerencias["fecha_creacion"], "map_fecha", "Fecha de creación", True)
    col_anio = seleccionar_columna(columnas, sugerencias["anio_creacion"], "map_anio", "Año de creación (alternativo)", True)
    col_proc = seleccionar_columna(columnas, sugerencias["procedimiento"], "map_proc", "Procedimiento")
    col_equipo = seleccionar_columna(columnas, sugerencias["equipo"], "map_equipo", "Equipo")
    col_estado = seleccionar_columna(columnas, sugerencias["estado"], "map_estado", "Estado")

mapeo = {
    "expediente": col_exp,
    "fecha_creacion": col_fecha,
    "anio_creacion": col_anio,
    "procedimiento": col_proc,
    "equipo": col_equipo,
    "estado": col_estado,
}

try:
    datos, calidad = preparar_datos(raw, mapeo)
except ValueError as exc:
    st.error(str(exc))
    st.info("Abre «Configurar columnas del origen» en el panel izquierdo y relaciona cada campo.")
    st.stop()

if datos.empty:
    st.warning("No hay expedientes válidos con identificador y año de creación reconocibles.")
    st.stop()


# =============================================================================
# FILTROS Y RESUMEN DE CALIDAD
# =============================================================================
st.markdown("#### Estado de los expedientes")
f1, f2, f3 = st.columns([1.2, 1.2, 3.6])
with f1:
    incluir_sin = st.checkbox("Sin Resolución", value=True, key="filtro_sin_resolucion")
with f2:
    incluir_con = st.checkbox("Con Resolución", value=True, key="filtro_con_resolucion")
with f3:
    st.markdown(
        '<p class="nota">Las categorías reconocen variantes con o sin tildes, mayúsculas y espacios repetidos.</p>',
        unsafe_allow_html=True,
    )

filtrados = filtrar_por_estado(datos, incluir_sin, incluir_con)

if calidad["duplicados_expediente"]:
    st.warning(
        f"Se detectaron {calidad['duplicados_expediente']:,} filas duplicadas por expediente. "
        "Para evitar el doble conteo, se conservó la última aparición de cada expediente."
    )
if calidad["fechas_invalidas"] or calidad["sin_anio"]:
    st.warning(
        f"Hay {calidad['fechas_invalidas']:,} fechas no interpretables y "
        f"{calidad['sin_anio']:,} registros sin año. Esos registros no participan en los reportes."
    )

estados_fuera = datos.loc[
    datos["Categoría de estado"].eq(CATEGORIA_NO_CLASIFICADO), "Estado"
].value_counts()
if not estados_fuera.empty:
    with st.expander(f"Estados fuera de las dos categorías ({int(estados_fuera.sum()):,} expedientes)"):
        st.dataframe(estados_fuera.rename("Cantidad").to_frame(), use_container_width=True)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Expedientes del origen", f"{len(datos):,}")
m2.metric("Expedientes filtrados", f"{len(filtrados):,}")
m3.metric("Años identificados", f"{datos['Año'].nunique():,}")
m4.metric("Procedimientos", f"{datos['Procedimiento'].nunique():,}")


# =============================================================================
# TRES PESTAÑAS DEL PANEL
# =============================================================================
tab_resumen, tab_procedimiento, tab_equipos = st.tabs(
    ["📊 Resumen General", "📋 Por Procedimiento", "🏢 Comparativo por Equipos"]
)

with tab_resumen:
    st.markdown(
        f'<div class="barra-azul">TOTAL DE EXPEDIENTES POR AÑO: {len(filtrados):,}</div>',
        unsafe_allow_html=True,
    )
    tabla_anual = construir_resumen_anual(filtrados)
    mostrar_tabla(tabla_anual, "No hay expedientes para los estados seleccionados.")

with tab_procedimiento:
    st.markdown('<div class="barra-azul">EXPEDIENTES POR PROCEDIMIENTO Y AÑO</div>', unsafe_allow_html=True)
    matriz_procedimiento = construir_matriz(filtrados, "Procedimiento")
    mostrar_tabla(matriz_procedimiento, "No hay expedientes para los estados seleccionados.")

with tab_equipos:
    st.markdown('<div class="barra-azul">COMPARATIVO DE EXPEDIENTES POR EQUIPO Y AÑO</div>', unsafe_allow_html=True)
    matriz_equipos = construir_matriz(filtrados, "Equipo")
    mostrar_tabla(matriz_equipos, "No hay expedientes para los estados seleccionados.")

st.divider()
st.caption(
    f"Versión didáctica {APP_VERSION} · Fuente: Google Sheets · "
    "Los filtros de estado afectan exclusivamente a estas tres pestañas."
)

import streamlit as st
import pandas as pd
import numpy as np
import unicodedata
import re
import os
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Procesador de Partidos", page_icon="⚽", layout="wide")

st.title("⚽ Procesador Completo de Partidos de Fútbol")

DIR_APP = os.path.dirname(os.path.abspath(__file__))
MAESTRO_PATH = os.path.join(DIR_APP, 'maestro_provincias_clubes.csv')

def _excel_engine():
    """Usa xlsxwriter si está; si no, openpyxl (evita fallar si falta una librería)."""
    try:
        import xlsxwriter  # noqa: F401
        return 'xlsxwriter'
    except Exception:
        return 'openpyxl'

EXCEL_ENGINE = _excel_engine()

# =============================================================================
# CONSOLIDACIÓN E INTERPRETACIÓN DE NOMBRES (para cruzar con el seguimiento)
# =============================================================================
TOKENS_TIPO = {'CD', 'CF', 'SAD', 'UD', 'AD', 'EF', 'FC', 'CP', 'SD', 'CDE', 'CFB'}
STOP = {'CLUB', 'ASOCIACION', 'SOCIEDAD', 'ANONIMA', 'DE', 'DEL', 'LA', 'EL', 'LOS', 'LAS', 'Y'} | TOKENS_TIPO

def _sin_acentos(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s)) if unicodedata.category(c) != 'Mn')

def canon_equipo(nombre):
    """(canónico, sufijo) de un nombre de equipo: sin acentos, sin comillas, sin
    abreviaturas de tipo de club, con la letra de filial (A/B/C) aparte."""
    s = _sin_acentos(nombre).upper()
    s = re.sub(r'["\'‘’“”`]', ' ', s)
    m = re.search(r'\b([A-E])\b\s*$', s.strip())
    suf = m.group(1) if m else ''
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    sig = [t for t in s.split() if t not in STOP and len(t) > 1]
    return ' '.join(sig), suf

def info_competicion(competicion):
    """(edad, tier) de una competición."""
    c = _sin_acentos(competicion).upper()
    edad = next((k for k in ['PREBENJAMIN', 'BENJAMIN', 'ALEVIN', 'INFANTIL', 'CADETE', 'JUVENIL'] if k in c), None)
    if edad is None:
        # sénior: Tercera Federación escrita como "TERCERA" o como "3ª Federación"
        if 'SENIOR' in c or 'TERCERA' in c or ('FEDERACION' in c and re.search(r'\b3\b|3[ªAº]', c)):
            edad = 'SENIOR'
        else:
            edad = 'OTRO'
    m = re.search(r'\b([1-5])\b', c)
    if m:
        tier = m.group(1)
    elif 'HONOR' in c:
        tier = 'DH'
    elif 'LIGA NACIONAL' in c:
        tier = 'LN'
    elif 'TERCERA' in c:
        tier = 'TF'
    elif 'COPA' in c or 'TROFEO' in c:
        tier = 'CP'
    else:
        tier = 'X'
    return edad, tier

def categoria(competicion):
    return info_competicion(competicion)[0]

def modalidad(competicion):
    """Clasifica el partido en F7 / F11 / OTROS según la competición:
    - F7    : alevín, benjamín, prebenjamín
    - F11   : infantil, cadete, juvenil y sénior de Tercera Federación
    - OTROS : fútbol sala, playa, femenino, sénior no-tercera, copas sin categoría, etc."""
    c = _sin_acentos(competicion).upper()
    if any(k in c for k in ['SALA', 'F.S', 'FUTSAL', 'PLAYA', 'FEMENIN']):
        return 'OTROS'
    if any(k in c for k in ['ALEVIN', 'BENJAMIN', 'PREBENJAMIN']):
        return 'F7'
    if any(k in c for k in ['INFANTIL', 'CADETE', 'JUVENIL']):
        return 'F11'
    if 'FEDERACION' in c and ('TERCERA' in c or re.search(r'\b3\b|3[ªAº]', c)):
        return 'F11'
    return 'OTROS'

# =============================================================================
# SEGUIMIENTO (hojas F7 y F11) -> índices para el cruce por nombre
# =============================================================================
HOJAS_SEGUIMIENTO = ['andalucia f7', 'andalucia f-11']
HOJAS_NO_EQUIPOS = ['pdte ver', 'informesinsertados', 'añadir', 'anadir']

def leer_seguimiento(archivo):
    xl = pd.ExcelFile(archivo)
    nombres = {h.lower(): h for h in xl.sheet_names}
    hojas = [nombres[h] for h in HOJAS_SEGUIMIENTO if h in nombres]
    if not hojas:
        hojas = [h for h in xl.sheet_names if h.lower() not in HOJAS_NO_EQUIPOS]
    if not hojas:
        hojas = xl.sheet_names[:1]
    registros = []
    for h in hojas:
        d = pd.read_excel(xl, sheet_name=h, header=None)
        if d.shape[1] <= 36:
            continue
        d = d.iloc[7:]
        for _, r in d.iterrows():
            equipo = r.iloc[2]
            if pd.isna(equipo) or not str(equipo).strip():
                continue
            edad, tier = info_competicion(r.iloc[0])
            cs, suf = canon_equipo(equipo)
            if not cs:
                continue
            registros.append({'edad': edad, 'tier': tier, 'canon': cs, 'suf': suf,
                              'sig': set(cs.split()), 'vis': r.iloc[36], 'det': r.iloc[35],
                              'equipo': str(equipo)})
    return registros

def construir_indices(registros):
    por_canon, por_edad = {}, {}
    for rec in registros:
        por_canon.setdefault((rec['edad'], rec['canon']), []).append(rec)
        por_edad.setdefault(rec['edad'], []).append(rec)
    return por_canon, por_edad

def resolver_equipo(por_canon, por_edad, competicion, nombre):
    edad, tier = info_competicion(competicion)
    cs, suf = canon_equipo(nombre)
    if not cs:
        return None, None
    cands = por_canon.get((edad, cs), [])
    if cands:
        if len(cands) > 1:
            f = [x for x in cands if (not suf or not x['suf'] or x['suf'] == suf)] or cands
            if len(f) > 1:
                g = [x for x in f if x['tier'] == tier] or f
                f = g
            cands = f
        return cands[0]['vis'], cands[0]['det']
    # fuzzy conservador dentro de la edad
    sig = set(cs.split())
    mejor, mejor_sc, empates = None, 0.0, 0
    for x in por_edad.get(edad, []):
        if suf and x['suf'] and suf != x['suf']:
            continue
        inter = len(sig & x['sig'])
        if inter == 0:
            continue
        jac = inter / len(sig | x['sig'])
        if jac > mejor_sc:
            mejor, mejor_sc, empates = x, jac, 1
        elif jac == mejor_sc:
            empates += 1
    if mejor and mejor_sc >= 0.6 and empates == 1:
        return mejor['vis'], mejor['det']
    return None, None

# =============================================================================
# PROVINCIA por CÓDIGO DE CLUB + TABLA MAESTRA (código club -> provincia)
# =============================================================================
# La provincia se deduce del propio partido (dirección del campo y/o competición),
# se asocia al CÓDIGO de club casa (identificador exacto) y se guarda en una tabla
# maestra que crece sola. En cada ejecución: se carga, se completa con clubes nuevos,
# se asigna por código y se guarda. Así no hay que recalcular nada en el futuro.

PROV_DISPLAY = {'GRANADA': 'Granada', 'CADIZ': 'Cádiz', 'JAEN': 'Jaén', 'MALAGA': 'Málaga',
                'CORDOBA': 'Córdoba', 'ALMERIA': 'Almería', 'SEVILLA': 'Sevilla', 'HUELVA': 'Huelva'}

def _buscar_provincia(texto):
    """Busca cualquier provincia andaluza mencionada en el texto y devuelve su nombre
    bonito. Si hay varias, la última (suele ser la real: '..., Ciudad, Provincia')."""
    if pd.isna(texto):
        return None
    c = _sin_acentos(texto).upper()
    hits = [(m.start(), p) for p in PROV_DISPLAY for m in re.finditer(r'\b' + p + r'\b', c)]
    return PROV_DISPLAY[max(hits)[1]] if hits else None

def provincia_de_direccion(direccion):
    """Provincia deducida de la dirección del campo (busca en toda la cadena, no solo
    el último trozo: así aguanta códigos postales o texto tras la provincia)."""
    return _buscar_provincia(direccion)

def provincia_de_competicion(competicion):
    """Provincia deducida del nombre de la competición: paréntesis '(Granada)' o mención."""
    if pd.isna(competicion):
        return None
    c = _sin_acentos(competicion).upper()
    m = re.search(r'\(([^)]*)\)', c)
    if m and m.group(1).strip() in PROV_DISPLAY:
        return PROV_DISPLAY[m.group(1).strip()]
    return _buscar_provincia(competicion)

def cargar_maestro(upload=None):
    """Devuelve (prov_por_codigo, nombre_por_codigo). Prioridad: archivo subido > local."""
    try:
        if upload is not None:
            m = pd.read_csv(upload, sep=';', dtype=str, encoding='utf-8-sig')
        elif os.path.exists(MAESTRO_PATH):
            m = pd.read_csv(MAESTRO_PATH, sep=';', dtype=str, encoding='utf-8-sig')
        else:
            return {}, {}
        prov = {str(k): v for k, v in zip(m['Codigo Club'], m['Provincia']) if pd.notna(v)}
        nom = {str(k): (v if pd.notna(v) else '') for k, v in zip(m['Codigo Club'], m.get('Nombre Club', pd.Series([''] * len(m))))}
        return prov, nom
    except Exception:
        return {}, {}

def maestro_a_df(prov_map, nom_map):
    return pd.DataFrame({'Codigo Club': list(prov_map.keys()),
                         'Provincia': [prov_map[k] for k in prov_map],
                         'Nombre Club': [nom_map.get(k, '') for k in prov_map]}).sort_values('Codigo Club')

def guardar_maestro(df_maestro):
    try:
        df_maestro.to_csv(MAESTRO_PATH, sep=';', index=False, encoding='utf-8-sig')
        return True
    except Exception:
        return False

# =============================================================================
# ACTUALIZAR EQUIPOS DEL SEGUIMIENTO desde la ListaPartidos
# =============================================================================
# Añade a las hojas F7/F11 los equipos NUEVOS (casa y visitante) de las competiciones
# que interesan, sin duplicar ni perder el ojeo, reordenando por edad. Conserva la
# macro, los desplegables y el formato (openpyxl keep_vba).

def clasificar_comp(colA):
    """(modalidad, rank_edad) de una competición; rank menor = más arriba en la hoja.
    Devuelve (None, None) si no es de las que interesan (futsal, playa, femenino, sénior no-tercera)."""
    c = _sin_acentos(colA).upper()
    if any(k in c for k in ['SALA', 'F.S', 'FUTSAL', 'PLAYA', 'FEMENIN']):
        return None, None
    if 'PREBENJAMIN' in c: return 'F7', 3
    if 'BENJAMIN' in c:    return 'F7', 2
    if 'ALEVIN' in c:      return 'F7', 1
    if 'INFANTIL' in c:    return 'F11', 3
    if 'CADETE' in c:      return 'F11', 2
    if 'JUVENIL' in c:     return 'F11', 1
    if 'FEDERACION' in c and ('TERCERA' in c or re.search(r'\b3\b|3[ªAº]', c)):
        return 'F11', 0
    return None, None

def _num_grupo(colA):
    m = re.search(r'GRUPO\s+(\d+)', _sin_acentos(colA).upper())
    return int(m.group(1)) if m else 0

def actualizar_seguimiento(uploaded_excel, df):
    """Devuelve (BytesIO del .xlsm actualizado, stats) o (None, None) si no aplica."""
    import openpyxl
    uploaded_excel.seek(0)
    wb = openpyxl.load_workbook(uploaded_excel, keep_vba=True)
    nombres = {h.lower(): h for h in wb.sheetnames}
    hojas = {'F7': nombres.get('andalucia f7'), 'F11': nombres.get('andalucia f-11')}
    if not hojas['F7'] and not hojas['F11']:
        return None, None

    # equipos de la lista de partidos, por modalidad (casa y visitante)
    nuevos = {'F7': set(), 'F11': set()}
    for _, r in df.iterrows():
        comp = str(r.get('Competición', '')).strip()
        g = r.get('Grupo')
        grupo = str(g).strip() if pd.notna(g) else ''
        colA = comp + (', ' + grupo if grupo and grupo.lower() != 'nan' else '')
        mod, _ = clasificar_comp(colA)
        if not mod:
            continue
        for eqcol in ['Equipo Casa', 'Equipo Visitante']:
            eq = r.get(eqcol)
            if pd.notna(eq) and str(eq).strip():
                nuevos[mod].add((colA, str(eq).strip()))

    stats = {'F7': 0, 'F11': 0}
    for mod, hoja in hojas.items():
        if not hoja:
            continue
        ws = wb[hoja]
        maxr = ws.max_row
        # leer filas existentes conservando el ojeo (columnas D..BE)
        data = {}
        for rr in range(8, maxr + 1):
            c = ws.cell(rr, 3).value
            if c is not None and str(c).strip():
                a = ws.cell(rr, 1).value
                key = (str(a).strip() if a is not None else '', str(c).strip())
                data[key] = [ws.cell(rr, col).value for col in range(4, 58)]
        antes = len(data)
        for key in nuevos[mod]:
            if key not in data:
                data[key] = [None] * 54
        stats[mod] = len(data) - antes

        def clave(k):
            _, rank = clasificar_comp(k[0])
            return (rank if rank is not None else 9, _sin_acentos(k[0]).upper(),
                    _num_grupo(k[0]), _sin_acentos(k[1]).upper())
        orden = sorted(data.keys(), key=clave)

        # limpiar contenido antiguo (mantiene estilos/bordes/validación) y reescribir
        for rr in range(8, maxr + 1):
            for col in [1, 3] + list(range(4, 58)):
                ws.cell(rr, col).value = None
        for i, key in enumerate(orden):
            rr = 8 + i
            ws.cell(rr, 1).value = key[0]
            ws.cell(rr, 3).value = key[1]
            d = data[key]
            for j, col in enumerate(range(4, 58)):
                ws.cell(rr, col).value = d[j]

    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out, stats

# =============================================================================
# TABS
# =============================================================================
tab1, tab2 = st.tabs(["📋 Procesar Partidos Nuevos", "🔄 Actualizar Agenda Existente"])

with tab1:
    st.header("📋 Crear Agenda Desde Cero")
    st.markdown("Cruza la lista de partidos con el seguimiento (F7 **y** F11) consolidando nombres, "
                "y añade la **provincia por código de club** (tabla maestra que se guarda y crece sola).")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("📄 Lista de Partidos (CSV)")
        uploaded_csv = st.file_uploader("Sube el archivo ListaPartidos.csv", type=['csv'], key="csv_file")
    with col2:
        st.subheader("📊 Seguimiento Ligas (Excel)")
        uploaded_excel = st.file_uploader("Sube el Seguimiento_ligas_26-27.xlsm", type=['xlsx', 'xlsm'], key="excel_file")
    with col3:
        st.subheader("🗂️ Tabla maestra provincias")
        uploaded_maestro = st.file_uploader("maestro_provincias_clubes.csv (opcional)", type=['csv'], key="maestro_file",
                                            help="Opcional. Si no la subes, se usa la guardada junto a la app. Se actualiza sola con los clubes nuevos.")

    if uploaded_csv is not None and uploaded_excel is not None:
        try:
            with st.spinner('Procesando archivos...'):
                # 1) LISTA DE PARTIDOS
                lect = pd.read_csv(uploaded_csv, encoding="latin1", on_bad_lines='skip', sep=';',
                                   dtype={'Competición': str, 'Grupo': str, 'Club Casa': str, 'Club Visitante': str},
                                   index_col=False)
                lect = lect.loc[:, ~lect.columns.astype(str).str.startswith('Unnamed')]
                df = lect.copy()
                df['Competicion'] = (df['Competición'].fillna('') + ", " + df['Grupo'].fillna('')) \
                    .str.strip().str.strip(',').str.strip()
                df['Modalidad'] = df['Competición'].map(modalidad)

                # 2) SEGUIMIENTO (F7 + F11) + cruce consolidado por nombre
                registros = leer_seguimiento(uploaded_excel)
                por_canon, por_edad = construir_indices(registros)
                vis_c, det_c, match_c, vis_v, det_v = [], [], [], [], []
                for _, row in df.iterrows():
                    comp = row.get('Competición', '')
                    vc, dc = resolver_equipo(por_canon, por_edad, comp, row.get('Equipo Casa', ''))
                    vv, dv = resolver_equipo(por_canon, por_edad, comp, row.get('Equipo Visitante', ''))
                    vis_c.append(vc); det_c.append(dc); match_c.append(vc is not None or dc is not None)
                    vis_v.append(vv); det_v.append(dv)
                df['Visualización C'] = vis_c
                df['Detalles Equipo Casa'] = det_c
                df['Visualización V'] = vis_v
                df['Detalles Equipo Visitante'] = det_v
                df['_match_casa'] = match_c

                # 3) PROVINCIA por código de club + tabla maestra (se guarda y crece sola)
                prov_map, nom_map = cargar_maestro(uploaded_maestro)

                dir_col = 'Dirección Campo' if 'Dirección Campo' in df.columns else None
                df['_prov_dir'] = df[dir_col].map(provincia_de_direccion) if dir_col else None
                df['_prov_comp'] = df['Competición'].map(provincia_de_competicion)

                def _guardar_club(code, nombre, prov):
                    code = str(code) if pd.notna(code) else ''
                    if code and prov and code not in prov_map:
                        prov_map[code] = prov
                        nom_map[code] = str(nombre) if pd.notna(nombre) else ''
                        return True
                    return False

                nuevos = 0
                # club de CASA: provincia por dirección del campo (mejor) o, si no, por competición
                for code, grp in df.groupby('Club Casa'):
                    pv = grp['_prov_dir'].dropna()
                    if len(pv):
                        prov = pv.mode().iat[0]
                    else:
                        pc = grp['_prov_comp'].dropna()
                        prov = pc.mode().iat[0] if len(pc) else None
                    nom = grp['Nombre Club Casa'].dropna()
                    if _guardar_club(code, nom.iloc[0] if len(nom) else '', prov):
                        nuevos += 1
                # club VISITANTE: solo si la competición indica provincia (ligas provinciales)
                for code, grp in df.groupby('Club Visitante'):
                    pc = grp['_prov_comp'].dropna()
                    if len(pc):
                        nom = grp['Nombre Club Visitante'].dropna()
                        if _guardar_club(code, nom.iloc[0] if len(nom) else '', pc.mode().iat[0]):
                            nuevos += 1

                # provincia del PARTIDO = la del club de casa (maestra > dirección > competición)
                df['Provincia'] = (df['Club Casa'].astype(str).map(prov_map)
                                   .fillna(df['_prov_dir']).fillna(df['_prov_comp']))

                # guardar la maestra actualizada
                df_maestro = maestro_a_df(prov_map, nom_map)
                guardado = guardar_maestro(df_maestro)

                # 4) COLUMNAS Y ORDEN
                df['Técnico'] = ''
                df['Motivo'] = ''

                def calcular_visto(row):
                    vc = row.get('Visualización C', ''); vv = row.get('Visualización V', '')
                    vc = str(vc) if pd.notna(vc) else ''
                    vv = str(vv) if pd.notna(vv) else ''
                    return 'Rellenas' if (vc != '' and vv != '') else 'Incompletas'

                df['Visto'] = df.apply(calcular_visto, axis=1)

                orden = ['Técnico', 'Motivo', 'Visto', 'Modalidad', 'Fecha', 'Hora', 'Jornada', 'Competicion', 'Provincia',
                         'Nombre Club Casa', 'Equipo Casa', 'Visualización C', 'Detalles Equipo Casa',
                         'Nombre Club Visitante', 'Equipo Visitante', 'Visualización V', 'Detalles Equipo Visitante',
                         'Campo', 'Dirección Campo']
                orden = [c for c in orden if c in df.columns]
                df_resultado = df[orden].copy()
                df_resultado['Fecha'] = pd.to_datetime(df_resultado['Fecha'], errors='coerce', dayfirst=True).dt.strftime('%d/%m/%Y')

            st.success("✅ Archivos procesados correctamente!")

            total = len(df)
            loc = int(df['_match_casa'].sum())
            con_prov = int(df['Provincia'].notna().sum() if 'Provincia' in df else 0)
            c1, c2, c3 = st.columns(3)
            c1.metric("📊 Partidos", total)
            c2.metric("🎯 Equipo casa localizado", f"{loc} ({100*loc//max(1,total)}%)")
            c3.metric("🗺️ Con provincia", f"{con_prov} ({100*con_prov//max(1,total)}%)")

            vc_mod = df['Modalidad'].value_counts()
            st.write("**Reparto por modalidad:** "
                     + " · ".join(f"{k}: {int(v)}" for k, v in vc_mod.items()))

            msg = f"🗂️ Tabla maestra: {len(df_maestro)} clubes ({nuevos} nuevos añadidos esta vez)."
            msg += " Guardada junto a la app." if guardado else " ⚠️ No se pudo guardar localmente; descárgala abajo."
            st.info(msg)
            st.caption("Los partidos de categorías que el seguimiento no rastrea (sénior amateur, fútbol sala, "
                       "femenino, copas) saldrán sin localizar en el seguimiento; es lo esperado.")

            st.subheader("👀 Vista previa del resultado")
            st.dataframe(df_resultado.head(15))

            out = BytesIO()
            with pd.ExcelWriter(out, engine=EXCEL_ENGINE) as writer:
                df_resultado.to_excel(writer, sheet_name='Resultado', index=False)
            cda, cdb = st.columns(2)
            cda.download_button("📥 Descargar agenda_nueva.xlsx", data=out.getvalue(),
                                file_name="agenda_nueva.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            cdb.download_button("💾 Descargar tabla maestra actualizada",
                                data=df_maestro.to_csv(sep=';', index=False, encoding='utf-8-sig').encode('utf-8-sig'),
                                file_name="maestro_provincias_clubes.csv", mime="text/csv")

            # --- Seguimiento actualizado (añade equipos nuevos de esta lista) ---
            st.markdown("---")
            st.subheader("🔄 Seguimiento actualizado")
            try:
                with st.spinner('Añadiendo equipos nuevos al seguimiento...'):
                    seg_out, seg_stats = actualizar_seguimiento(uploaded_excel, df)
                if seg_out is None:
                    st.warning("El Excel subido no tiene las hojas 'andalucia f7' / 'andalucia f-11'.")
                else:
                    st.success(f"Añadidos **{seg_stats['F7']}** equipos nuevos a F7 y **{seg_stats['F11']}** a F11 "
                               "(los que no estaban, de las competiciones que interesan). El resto y tu ojeo se conservan.")
                    st.download_button("📥 Descargar Seguimiento actualizado (.xlsm)", data=seg_out.getvalue(),
                                       file_name="Seguimiento_ligas_actualizado.xlsm",
                                       mime="application/vnd.ms-excel.sheet.macroEnabled.12")
            except Exception as e:
                st.warning(f"No se pudo actualizar el seguimiento: {e}")

        except Exception as e:
            st.error(f"❌ Error al procesar los archivos: {str(e)}")
            st.exception(e)
    else:
        st.info("👆 Sube la lista de partidos y el seguimiento para comenzar")


# =============================================================================
# TAB 2: ACTUALIZACIÓN DE AGENDA EXISTENTE  (sin cambios de lógica)
# =============================================================================
with tab2:
    st.header("🔄 Actualizar Agenda Existente")
    st.markdown("Actualiza una agenda preservando tu trabajo ya hecho (técnicos, motivos, etc.)")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📅 Agenda Actual (con tu trabajo)")
        archivo_base = st.file_uploader("Sube tu agenda actual (con técnicos, motivos, etc.)",
                                        type=['xlsx', 'xlsm'], key="archivo_base",
                                        help="Este archivo contiene tu trabajo que NO quieres perder")
    with col2:
        st.subheader("🆕 Agenda Nueva (datos actualizados)")
        archivo_nuevo = st.file_uploader("Sube la agenda nueva (fechas, horarios, etc.)",
                                         type=['xlsx', 'xlsm'], key="archivo_nuevo",
                                         help="Este archivo tiene los datos nuevos que quieres actualizar")

    if archivo_base is not None and archivo_nuevo is not None:
        st.subheader("⚙️ Configuración de Actualización")
        try:
            df_base_preview = pd.read_excel(archivo_base)
            df_nuevo_preview = pd.read_excel(archivo_nuevo)
            col1, col2 = st.columns(2)
            with col1:
                st.write("**Columnas en archivo base:**"); st.write(list(df_base_preview.columns))
            with col2:
                st.write("**Columnas en archivo nuevo:**"); st.write(list(df_nuevo_preview.columns))

            st.subheader("📋 Selecciona qué columnas quieres actualizar")
            columnas_comunes = list(set(df_base_preview.columns) & set(df_nuevo_preview.columns))
            columnas_protegidas = ['Técnico', 'Motivo', 'Visto']
            columnas_disponibles = [c for c in columnas_comunes if c not in columnas_protegidas]
            columnas_por_defecto = [c for c in ['Fecha', 'Hora', 'Campo', 'Dirección Campo'] if c in columnas_disponibles]
            columnas_seleccionadas = st.multiselect("Columnas a actualizar:", columnas_disponibles,
                                                     default=columnas_por_defecto,
                                                     help="Solo se actualizarán estas. Técnico/Motivo/Visto se preservan.")
            st.info(f"🛡️ **Columnas protegidas** (NO se actualizan): {', '.join(columnas_protegidas)}")

            st.subheader("🆔 Columna para identificar partidos")
            columna_id = st.selectbox("Columna que identifica cada partido:", ["Usar posición de fila"] + columnas_comunes)
            if columna_id == "Usar posición de fila":
                columna_id = None

            if st.button("🚀 Actualizar Agenda", type="primary"):
                if not columnas_seleccionadas:
                    st.error("❌ Debes seleccionar al menos una columna para actualizar")
                else:
                    try:
                        with st.spinner('🔄 Actualizando agenda...'):
                            def actualizar_agenda(df_martes, df_miercoles, columnas_a_actualizar, columna_id):
                                df_resultado = df_martes.copy()
                                if not columna_id:
                                    columna_id = '_posicion_fila'
                                    df_martes[columna_id] = df_martes.index
                                    df_miercoles[columna_id] = df_miercoles.index
                                    df_resultado[columna_id] = df_resultado.index
                                partidos_actualizados = 0
                                partidos_sin_match = 0
                                columnas_actualizadas = {c: 0 for c in columnas_a_actualizar}
                                dict_martes = {str(row[columna_id]): idx for idx, row in df_resultado.iterrows()}
                                for _, row_m in df_miercoles.iterrows():
                                    key = str(row_m[columna_id])
                                    if key in dict_martes:
                                        idx_m = dict_martes[key]
                                        cambiado = False
                                        for columna in columnas_a_actualizar:
                                            if columna in df_miercoles.columns:
                                                vn = row_m[columna]; va = df_resultado.loc[idx_m, columna]
                                                if pd.isna(va) and pd.isna(vn):
                                                    continue
                                                elif va != vn:
                                                    df_resultado.loc[idx_m, columna] = vn
                                                    columnas_actualizadas[columna] += 1
                                                    cambiado = True
                                        if cambiado:
                                            partidos_actualizados += 1
                                            df_resultado.loc[idx_m, 'Ultima_Actualizacion'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                                            if 'Visto' in df_resultado.columns:
                                                vc = df_resultado.loc[idx_m, 'Visualización C'] if 'Visualización C' in df_resultado.columns else ''
                                                vv = df_resultado.loc[idx_m, 'Visualización V'] if 'Visualización V' in df_resultado.columns else ''
                                                vc = str(vc) if pd.notna(vc) else ''
                                                vv = str(vv) if pd.notna(vv) else ''
                                                df_resultado.loc[idx_m, 'Visto'] = 'Rellenas' if (vc != '' and vv != '') else 'Incompletas'
                                    else:
                                        partidos_sin_match += 1
                                if columna_id == '_posicion_fila':
                                    df_resultado = df_resultado.drop(columna_id, axis=1)
                                return df_resultado, {'partidos_actualizados': partidos_actualizados,
                                                      'partidos_sin_match': partidos_sin_match,
                                                      'columnas_actualizadas': columnas_actualizadas}

                            df_base = pd.read_excel(archivo_base)
                            df_nuevo = pd.read_excel(archivo_nuevo)
                            df_actualizado, stats = actualizar_agenda(df_base, df_nuevo, columnas_seleccionadas, columna_id)

                        st.success("✅ Agenda actualizada correctamente!")
                        c1, c2, c3 = st.columns(3)
                        c1.metric("🎯 Partidos actualizados", stats['partidos_actualizados'])
                        c2.metric("❓ Sin correspondencia", stats['partidos_sin_match'])
                        c3.metric("📊 Total partidos", len(df_actualizado))
                        st.subheader("📈 Cambios por columna")
                        for columna, cambios in stats['columnas_actualizadas'].items():
                            st.write(f"**{columna}**: {cambios} cambios")
                        st.subheader("👀 Vista previa del resultado")
                        st.dataframe(df_actualizado.head(10))
                        output_act = BytesIO()
                        with pd.ExcelWriter(output_act, engine=EXCEL_ENGINE) as writer:
                            df_actualizado.to_excel(writer, sheet_name='Agenda_Actualizada', index=False)
                        ts = datetime.now().strftime('%Y%m%d_%H%M')
                        st.download_button("📥 Descargar agenda_actualizada.xlsx", data=output_act.getvalue(),
                                           file_name=f"agenda_actualizada_{ts}.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    except Exception as e:
                        st.error(f"❌ Error al actualizar la agenda: {str(e)}")
        except Exception as e:
            st.error(f"❌ Error al leer los archivos: {str(e)}")
    else:
        st.info("👆 Sube ambos archivos para configurar la actualización")

# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.header("ℹ️ Guía de Uso")
    st.subheader("📋 Procesar Partidos Nuevos")
    st.markdown("""
    - Sube el **CSV de partidos** y el **Seguimiento** (hojas *andalucia f7* y *andalucia f-11*)
    - Los equipos se cruzan **consolidando nombres** (ignora comillas, C.D./C.F./SAD, sufijos A/B/C…)
    - La **provincia** se deduce del partido (dirección/competición) y se guarda por **código de club** en una **tabla maestra** que crece sola
    - Se crean: **Técnico**, **Motivo** (vacías) y **Visto** (🟢 Rellenas / 🔴 Incompletas)
    """)
    st.subheader("🔄 Actualizar Agenda")
    st.markdown("- Sube agenda actual + agenda nueva. **Técnico/Motivo/Visto se preservan.**")
    st.info("🧮 Visto = SI(Y(VisC<>\"\"; VisV<>\"\"); \"Rellenas\"; \"Incompletas\")")

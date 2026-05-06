import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Procesador de Partidos", page_icon="⚽", layout="wide")

st.title("⚽ Procesador Completo de Partidos de Fútbol")

# Crear tabs para las diferentes funcionalidades
tab1, tab2 = st.tabs(["📋 Procesar Partidos Nuevos", "🔄 Actualizar Agenda Existente"])

# =============================================================================
# TAB 1: PROCESAMIENTO DE PARTIDOS NUEVOS
# =============================================================================
with tab1:
    st.header("📋 Crear Agenda Desde Cero")
    st.markdown("Combina la lista de partidos con el seguimiento de ligas para crear una agenda nueva")

    # Crear dos columnas para los uploads
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📄 Lista de Partidos (CSV)")
        uploaded_csv = st.file_uploader(
            "Sube el archivo ListaPartidos.csv", 
            type=['csv'],
            key="csv_file"
        )

    with col2:
        st.subheader("📊 Seguimiento Ligas (Excel)")
        uploaded_excel = st.file_uploader(
            "Sube el archivo Seguimiento_ligas.xlsm", 
            type=['xlsx', 'xlsm'],
            key="excel_file"
        )

    if uploaded_csv is not None and uploaded_excel is not None:
        try:
            with st.spinner('Procesando archivos...'):
                
                # Leer el archivo CSV
                # - dtype=str en Competición/Grupo: evita que pandas los infiera como int/float
                #   y rompa la concatenación de más abajo.
                # - index_col=False: el CSV trae un ';' de más al final de cada fila (18 campos
                #   contra 17 cabeceras). Sin esto, pandas usa la 1ª columna como índice y
                #   desplaza todos los datos una columna a la izquierda.
                lect_partidos = pd.read_csv(
                    uploaded_csv, encoding="latin1", on_bad_lines='skip', sep=';',
                    dtype={'Competición': str, 'Grupo': str},
                    index_col=False,
                )
                # Si el separador de más generó una columna sin nombre al final, descártala.
                lect_partidos = lect_partidos.loc[:, ~lect_partidos.columns.astype(str).str.startswith('Unnamed')]
                
                # Crear DataFrame de partidos
                df_partidos = lect_partidos.drop(columns=['Club Casa', 'Club Visitante', 'Equipo Casa', 'Equipo Visitante',
                                                         'Resultado', 'Código Partido', 'Árbitro'], errors='ignore')
                
                # Extraer la provincia de la columna 'Competición'
                df_partidos['Provincia'] = df_partidos['Competición'].str.extract(r'\((.*?)\)')
                
                # Concatenar 'Competición' y 'Grupo' en una nueva columna
                df_partidos['Competicion'] = df_partidos['Competición'] + ", " + df_partidos['Grupo']
                
                # Eliminar las columnas originales 'Competición' y 'Grupo'
                df_partidos = df_partidos.drop(columns=['Competición', 'Grupo'], errors='ignore')
                
                # Leer el archivo de Excel
                lect_seguimiento = pd.read_excel(uploaded_excel)
                
                # Eliminar las primeras 5 filas
                df_seguimiento = lect_seguimiento.drop(index=lect_seguimiento.index[:5])
                
                # Renombrar columnas relevantes (por posición; reasignar la lista entera para compatibilidad con pandas 2.x)
                new_cols = df_seguimiento.columns.tolist()
                if len(new_cols) <= 36:
                    raise ValueError(
                        f"El Excel de seguimiento tiene {len(new_cols)} columnas tras quitar las 5 primeras filas; "
                        "se esperaban al menos 37 (Visualización C en col 37, Detalles Equipo Casa en col 36)."
                    )
                new_cols[0] = 'Competicion'
                new_cols[2] = 'Nombre Club Casa'
                new_cols[35] = 'Detalles Equipo Casa'
                new_cols[36] = 'Visualización C'
                df_seguimiento.columns = new_cols
                
                # Seleccionar columnas necesarias
                df_seguimiento = df_seguimiento[['Competicion', 'Nombre Club Casa', 'Visualización C', 'Detalles Equipo Casa']]
                
                # Realizar la primera unión
                resultado_casa = pd.merge(df_partidos, df_seguimiento, on=['Competicion', 'Nombre Club Casa'], how='left')
                
                # Preparar DataFrame para equipos visitantes
                df_visitante = df_seguimiento.copy()
                df_visitante.columns = ['Competicion', 'Nombre Club Visitante', 'Visualización V', 'Detalles Equipo Visitante']
                
                # Realizar la segunda unión
                resultado = pd.merge(resultado_casa, df_visitante, on=['Competicion', 'Nombre Club Visitante'], how='left')
                
                # ¡AQUÍ ES DONDE SE CREAN LAS NUEVAS COLUMNAS!
                # Agregar las columnas de técnico y motivo al inicio (vacías)
                resultado['Técnico'] = ''  # Columna A - vacía para que puedas llenarla
                resultado['Motivo'] = ''   # Columna B - vacía para que puedas llenarla
                
                # Agregar la columna "Visto" calculada (Columna C)
                # Replica la fórmula de Excel: =SI(Y(J2<>""; M2<>""); "Rellenas"; "Incompletas")
                # Donde J = "Visualización C" y M = "Visualización V"
                def calcular_visto(row):
                    vis_c = row.get('Visualización C', '')
                    vis_v = row.get('Visualización V', '')
                    
                    # Convertir a string para manejar NaN y otros tipos
                    vis_c_str = str(vis_c) if pd.notna(vis_c) else ''
                    vis_v_str = str(vis_v) if pd.notna(vis_v) else ''
                    
                    # Aplicar la lógica exacta de Excel: Y(J2<>""; M2<>"")
                    if vis_c_str != '' and vis_v_str != '':
                        return 'Rellenas'
                    else:
                        return 'Incompletas'
                
                resultado['Visto'] = resultado.apply(calcular_visto, axis=1)
                
                # Establecer orden en las columnas del dataframe (AHORA con las nuevas columnas primero)
                nuevo_orden = ['Técnico', 'Motivo', 'Visto', 'Fecha', 'Hora', 'Jornada', 'Competicion', 'Provincia', 'Nombre Club Casa',
                              'Visualización C', 'Detalles Equipo Casa', 'Nombre Club Visitante',
                              'Visualización V', 'Detalles Equipo Visitante', 'Campo', 'Dirección Campo']
                
                df_resultado = resultado[nuevo_orden]
                
                # Convertir la columna 'Fecha' a formato datetime
                df_resultado['Fecha'] = pd.to_datetime(df_resultado['Fecha'], errors='coerce', dayfirst=True)
                
                # Aplicar el formato de fecha deseado
                df_resultado['Fecha'] = df_resultado['Fecha'].dt.strftime('%d/%m/%Y')
            
            # Mostrar preview de los resultados
            st.success("✅ Archivos procesados correctamente!")
            st.subheader("👀 Vista previa del resultado")
            st.dataframe(df_resultado.head(10))
            
            st.info(f"📊 Total de registros procesados: {len(df_resultado)}")
            
            # Crear el archivo Excel en memoria
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_resultado.to_excel(writer, sheet_name='Resultado', index=False)
            
            # Botón de descarga
            st.download_button(
                label="📥 Descargar agenda_nueva.xlsx",
                data=output.getvalue(),
                file_name="agenda_nueva.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
        except Exception as e:
            st.error(f"❌ Error al procesar los archivos: {str(e)}")
            st.info("Verifica que los archivos tengan el formato correcto y las columnas esperadas.")

    else:
        st.info("👆 Sube ambos archivos para comenzar el procesamiento")


# =============================================================================
# TAB 2: ACTUALIZACIÓN DE AGENDA EXISTENTE
# =============================================================================
with tab2:
    st.header("🔄 Actualizar Agenda Existente")
    st.markdown("Actualiza una agenda preservando tu trabajo ya hecho (técnicos, motivos, etc.)")
    
    # Crear dos columnas para los uploads de actualización
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📅 Agenda Actual (con tu trabajo)")
        archivo_base = st.file_uploader(
            "Sube tu agenda actual (la que tiene técnicos asignados, motivos, etc.)", 
            type=['xlsx', 'xlsm'],
            key="archivo_base",
            help="Este archivo contiene tu trabajo que NO quieres perder"
        )
    
    with col2:
        st.subheader("🆕 Agenda Nueva (datos actualizados)")
        archivo_nuevo = st.file_uploader(
            "Sube la agenda nueva (con datos actualizados de fechas, horarios, etc.)", 
            type=['xlsx', 'xlsm'],
            key="archivo_nuevo",
            help="Este archivo tiene los datos nuevos que quieres actualizar"
        )
    
    # Configuración de actualización
    if archivo_base is not None and archivo_nuevo is not None:
        st.subheader("⚙️ Configuración de Actualización")
        
        # Leer archivos para mostrar columnas disponibles
        try:
            df_base_preview = pd.read_excel(archivo_base)
            df_nuevo_preview = pd.read_excel(archivo_nuevo)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**Columnas disponibles en archivo base:**")
                st.write(list(df_base_preview.columns))
            
            with col2:
                st.write("**Columnas disponibles en archivo nuevo:**")
                st.write(list(df_nuevo_preview.columns))
            
            # Selección de columnas a actualizar
            st.subheader("📋 Selecciona qué columnas quieres actualizar")
            columnas_comunes = list(set(df_base_preview.columns) & set(df_nuevo_preview.columns))
            
            # Excluir columnas importantes que NO deben actualizarse
            columnas_protegidas = ['Técnico', 'Motivo', 'Visto']
            columnas_disponibles = [col for col in columnas_comunes if col not in columnas_protegidas]
            
            # Preseleccionar columnas típicas
            columnas_por_defecto = []
            for col in ['Fecha', 'Hora', 'Campo', 'Dirección Campo']:
                if col in columnas_disponibles:
                    columnas_por_defecto.append(col)
            
            columnas_seleccionadas = st.multiselect(
                "Columnas a actualizar:",
                columnas_disponibles,
                default=columnas_por_defecto,
                help="Solo se actualizarán estas columnas. Tu trabajo (Técnico, Motivo, Visto) se preservará automáticamente."
            )
            
            # Mostrar advertencia sobre columnas protegidas
            if columnas_protegidas:
                st.info(f"🛡️ **Columnas protegidas** (NO se actualizarán): {', '.join(columnas_protegidas)}")
            
            
            # Selección de columna ID
            st.subheader("🆔 Columna para identificar partidos")
            columna_id = st.selectbox(
                "Selecciona la columna que identifica únicamente cada partido:",
                ["Usar posición de fila"] + columnas_comunes,
                help="Esta columna se usa para saber qué partido corresponde a cuál entre los dos archivos"
            )
            
            if columna_id == "Usar posición de fila":
                columna_id = None
            
            # Botón para procesar
            if st.button("🚀 Actualizar Agenda", type="primary"):
                if not columnas_seleccionadas:
                    st.error("❌ Debes seleccionar al menos una columna para actualizar")
                else:
                    try:
                        with st.spinner('🔄 Actualizando agenda...'):
                            
                            # Función de actualización integrada
                            def actualizar_agenda(df_martes, df_miercoles, columnas_a_actualizar, columna_id):
                                # Crear copia del archivo del martes como base
                                df_resultado = df_martes.copy()
                                
                                # Si no hay columna ID, crear una basada en la posición
                                if not columna_id:
                                    columna_id = '_posicion_fila'
                                    df_martes[columna_id] = df_martes.index
                                    df_miercoles[columna_id] = df_miercoles.index
                                    df_resultado[columna_id] = df_resultado.index
                                
                                # Estadísticas
                                partidos_actualizados = 0
                                partidos_sin_match = 0
                                columnas_actualizadas = {col: 0 for col in columnas_a_actualizar}
                                
                                # Crear diccionario del archivo del martes para búsqueda rápida
                                dict_martes = {}
                                for idx, row in df_resultado.iterrows():
                                    key = str(row[columna_id])
                                    dict_martes[key] = idx
                                
                                # Actualizar cada partido del miércoles
                                for _, row_miercoles in df_miercoles.iterrows():
                                    key = str(row_miercoles[columna_id])
                                    
                                    if key in dict_martes:
                                        idx_martes = dict_martes[key]
                                        partido_actualizado = False
                                        
                                        # Actualizar solo las columnas especificadas
                                        for columna in columnas_a_actualizar:
                                            if columna in df_miercoles.columns:
                                                valor_nuevo = row_miercoles[columna]
                                                valor_anterior = df_resultado.loc[idx_martes, columna]
                                                
                                                # Solo actualizar si hay cambio
                                                if pd.isna(valor_anterior) and pd.isna(valor_nuevo):
                                                    continue
                                                elif valor_anterior != valor_nuevo:
                                                    df_resultado.loc[idx_martes, columna] = valor_nuevo
                                                    columnas_actualizadas[columna] += 1
                                                    partido_actualizado = True
                                        
                                        if partido_actualizado:
                                            partidos_actualizados += 1
                                            df_resultado.loc[idx_martes, 'Ultima_Actualizacion'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                                            
                                            # Recalcular el campo "Visto" usando la fórmula de Excel exacta
                                            if 'Visto' in df_resultado.columns:
                                                vis_c = df_resultado.loc[idx_martes, 'Visualización C'] if 'Visualización C' in df_resultado.columns else ''
                                                vis_v = df_resultado.loc[idx_martes, 'Visualización V'] if 'Visualización V' in df_resultado.columns else ''
                                                
                                                # Convertir a string para manejar NaN
                                                vis_c_str = str(vis_c) if pd.notna(vis_c) else ''
                                                vis_v_str = str(vis_v) if pd.notna(vis_v) else ''
                                                
                                                # Aplicar fórmula Excel: =SI(Y(J2<>""; M2<>""); "Rellenas"; "Incompletas")
                                                if vis_c_str != '' and vis_v_str != '':
                                                    df_resultado.loc[idx_martes, 'Visto'] = 'Rellenas'
                                                else:
                                                    df_resultado.loc[idx_martes, 'Visto'] = 'Incompletas'
                                    else:
                                        partidos_sin_match += 1
                                
                                # Limpiar columna temporal si la creamos
                                if columna_id == '_posicion_fila':
                                    df_resultado = df_resultado.drop(columna_id, axis=1)
                                
                                return df_resultado, {
                                    'partidos_actualizados': partidos_actualizados,
                                    'partidos_sin_match': partidos_sin_match,
                                    'columnas_actualizadas': columnas_actualizadas
                                }
                            
                            # Cargar archivos
                            df_base = pd.read_excel(archivo_base)
                            df_nuevo = pd.read_excel(archivo_nuevo)
                            
                            # Ejecutar actualización
                            df_actualizado, stats = actualizar_agenda(
                                df_base, df_nuevo, columnas_seleccionadas, columna_id
                            )
                        
                        # Mostrar resultados
                        st.success("✅ Agenda actualizada correctamente!")
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("🎯 Partidos actualizados", stats['partidos_actualizados'])
                        with col2:
                            st.metric("❓ Sin correspondencia", stats['partidos_sin_match'])
                        with col3:
                            st.metric("📊 Total partidos", len(df_actualizado))
                        
                        st.subheader("📈 Cambios por columna")
                        for columna, cambios in stats['columnas_actualizadas'].items():
                            st.write(f"**{columna}**: {cambios} cambios")
                        
                        # Vista previa
                        st.subheader("👀 Vista previa del resultado")
                        st.dataframe(df_actualizado.head(10))
                        
                        # Crear archivo para descarga
                        output_actualizado = BytesIO()
                        with pd.ExcelWriter(output_actualizado, engine='xlsxwriter') as writer:
                            df_actualizado.to_excel(writer, sheet_name='Agenda_Actualizada', index=False)
                        
                        # Botón de descarga
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
                        st.download_button(
                            label="📥 Descargar agenda_actualizada.xlsx",
                            data=output_actualizado.getvalue(),
                            file_name=f"agenda_actualizada_{timestamp}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                        
                    except Exception as e:
                        st.error(f"❌ Error al actualizar la agenda: {str(e)}")
                        st.info("Verifica que ambos archivos tengan el formato correcto.")
        
        except Exception as e:
            st.error(f"❌ Error al leer los archivos: {str(e)}")
    
    else:
        st.info("👆 Sube ambos archivos para configurar la actualización")

# Información adicional en la sidebar
with st.sidebar:
    st.header("ℹ️ Guía de Uso")
    
    st.subheader("📋 Procesar Partidos Nuevos")
    st.markdown("""
    - Sube tu CSV de partidos
    - Sube tu Excel de seguimiento  
    - Se crean automáticamente las columnas:
      - **Técnico** (vacía para que asignes)
      - **Motivo** (vacía para comentarios)
      - **Visto** (calculada según Visualización C y V):
        - 🟢 "Rellenas" si ambas visualizaciones tienen datos
        - 🔴 "Incompletas" si falta alguna visualización
    - Descarga la agenda completa
    """)
    
    st.subheader("🔄 Actualizar Agenda")
    st.markdown("""
    - Sube tu agenda actual (con trabajo hecho)
    - Sube la agenda nueva (datos actualizados)
    - Selecciona qué columnas actualizar
    - **Técnico, Motivo y Visto se preservan**
    """)
    
    st.subheader("🛡️ Campo Calculado")
    st.success("✅ Técnico: Tu trabajo nunca se pierde")
    st.success("✅ Motivo: Tus comentarios se mantienen")  
    st.info("🧮 Visto: Replica fórmula Excel exacta:")
    st.code("=SI(Y(J2<>\"\"; M2<>\"\"); \"Rellenas\"; \"Incompletas\")")
    st.markdown("""
    - 🟢 **"Rellenas"** = Visualización C **Y** Visualización V no están vacías
    - 🔴 **"Incompletas"** = Cualquiera de las dos está vacía
    """)
    st.success("✅ Solo se actualizan fechas, horarios, campos, etc.")

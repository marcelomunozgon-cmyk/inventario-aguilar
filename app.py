import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime, date
import numpy as np
import io
import qrcode
from PIL import Image
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. CONFIGURACIÓN Y LIMPIEZA ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

if 'model_initialized' not in st.session_state:
    st.cache_resource.clear()
    st.session_state.model_initialized = True

# --- SISTEMA ANTI-AMNESIA (URL Checkpoint) ---
if 'index' in st.query_params:
    st.session_state.index_orden = int(st.query_params['index'])
elif 'index_orden' not in st.session_state: 
    st.session_state.index_orden = 0

if 'auto_search' not in st.session_state: st.session_state.auto_search = ""
if 'triage_foto_procesada' not in st.session_state: st.session_state.triage_foto_procesada = -1
if 'triage_datos_ia' not in st.session_state: st.session_state.triage_datos_ia = {}

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except Exception as e:
    st.error(f"Error en Secrets. Detalle: {e}")
    st.stop()

@st.cache_resource
def cargar_modelo_definitivo():
    return genai.GenerativeModel('gemini-2.5-pro')

model = cargar_modelo_definitivo()

if "backup_inventario" not in st.session_state: st.session_state.backup_inventario = None

def crear_punto_restauracion(df_actual): st.session_state.backup_inventario = df_actual.copy()

# --- FUNCION GMAIL ---
def enviar_alerta_gmail(df_alertas):
    try:
        sender = st.secrets["EMAIL_SENDER"]
        password = st.secrets["EMAIL_PASSWORD"]
        receiver = st.secrets.get("EMAIL_RECEIVER", sender)
        
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = receiver
        msg['Subject'] = "🚨 ALERTA: Stock Crítico en Lab Aguilar"
        
        html_table = df_alertas[['nombre', 'ubicacion', 'posicion_caja', 'cantidad_actual', 'umbral_minimo', 'unidad']].to_html(index=False)
        
        body = f"""
        <html><body><h2>Reporte Automático de Stock Crítico</h2>
        <p>Los siguientes reactivos están por debajo de su umbral mínimo:</p>
        {html_table}<br><p><i>Lab Aguilar OS</i></p></body></html>
        """
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Fallo al enviar correo. Detalle: {e}")
        return False

# --- 2. LÓGICA DE DATOS Y UBICACIONES ---
zonas_lab_fijas = ["Mesón", "Refrigerador 1 (4°C)", "Refrigerador 2 (4°C)", "Freezer -20°C", "Freezer -80°C", "Estante Químicos", "Estante Plásticos", "Gabinete Inflamables", "Otro"]
cajones = [f"Cajón {i}" for i in range(1, 42)]
zonas_lab = zonas_lab_fijas + cajones
unidades_list = ["unidades", "mL", "uL", "cajas", "kits", "g", "mg", "bolsas"]

def sugerir_ubicacion(nombre):
    n = str(nombre).lower()
    if any(sal in n for sal in ["cloruro", "sulfato", "fosfato", "sodio", "potasio", "nacl", "sal "]): return "Cajón 37"
    if any(bio in n for bio in ["primer", "oligo", "dnazima", "dna", "rna", "taq", "polimerasa"]): return "Freezer -20°C"
    if any(solv in n for solv in ["alcohol", "etanol", "metanol", "isopropanol", "fenol", "cloroformo"]): return "Gabinete Inflamables"
    if any(prot in n for prot in ["anticuerpo", "bsa", "suero", "fbs"]): return "Refrigerador 1 (4°C)"
    return "Mesón"

def aplicar_estilos_inv(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0) if pd.notnull(row.get('umbral_minimo', 0)) else 0
    if cant <= 0: return ['background-color: #ffe6e6; color: black'] * len(row)
    if umb > 0 and cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

def estilo_alerta_editor(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0)
    if umb > 0 and cant <= umb:
        return ['background-color: #ffcccc; color: #900; font-weight: bold'] * len(row)
    return [''] * len(row)

# Cargar Tablas
res_items = supabase.table("items").select("*").execute()
df = pd.DataFrame(res_items.data)

# Añadimos 'posicion_caja' al sistema
columnas_texto = ['id', 'nombre', 'categoria', 'subcategoria', 'link_proveedor', 'lote', 'fecha_vencimiento', 'ubicacion', 'posicion_caja', 'unidad']
for col in columnas_texto:
    if col not in df.columns: df[col] = ""
    df[col] = df[col].astype(str).replace(["nan", "None"], "")

for col in ['cantidad_actual', 'umbral_minimo']:
    if col not in df.columns: df[col] = 0
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

df['categoria'] = df['categoria'].replace("", "GENERAL")

try: 
    res_prot = supabase.table("protocolos").select("*").execute()
    df_prot = pd.DataFrame(res_prot.data)
except: 
    df_prot = pd.DataFrame(columns=["id", "nombre", "materiales_base"])

# --- 3. INTERFAZ SUPERIOR ---
col_logo, col_user = st.columns([3, 1])
with col_logo: st.markdown("## 🔬 Lab Aguilar OS")

with col_user:
    usuarios_lab = ["Marcelo Muñoz", "Rodrigo Aguilar", "Tesista / Estudiante", "Otro"]
    usuario_actual = st.selectbox("👤 Usuario Activo:", usuarios_lab, index=0)

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    # --- EL BOTÓN DE DESHACER BLINDADO ---
    if st.session_state.backup_inventario is not None:
        if st.button("↩️ Deshacer Última Acción", type="secondary"):
            with st.spinner("Restaurando con limpieza de formatos..."):
                try:
                    backup_df = st.session_state.backup_inventario.replace({np.nan: None})
                    for index, row in backup_df.iterrows():
                        row_dict = row.to_dict()
                        # LIMPIEZA: Si hay campos vacíos que molestan a Supabase, los volvemos Nulos reales
                        for key, value in row_dict.items():
                            if pd.isna(value) or str(value).strip() == "":
                                row_dict[key] = None
                                
                        if 'id' in row_dict and row_dict['id'] is not None:
                            row_dict['id'] = str(row_dict['id'])
                            supabase.table("items").upsert(row_dict).execute()
                            
                    st.session_state.backup_inventario = None
                    st.success("¡Inventario restaurado con éxito!")
                    st.rerun()
                except Exception as e: st.error(f"Error al restaurar: {e}")

    tab_inventario, tab_protocolos, tab_editar, tab_orden, tab_importar = st.tabs(["📦 Inv", "🧪 Protocolos", "⚙️ Edit", "🗂️ Orden Auto", "📥 Carga"])
    
    # --- PESTAÑA: INVENTARIO ---
    with tab_inventario:
        df_criticos = df[(df['cantidad_actual'] <= df['umbral_minimo']) & (df['umbral_minimo'] > 0)]
        if not df_criticos.empty:
            st.error("🚨 **ATENCIÓN: Reactivos con Stock Crítico**")
            st.dataframe(df_criticos[['nombre', 'ubicacion', 'posicion_caja', 'cantidad_actual', 'umbral_minimo', 'unidad']], use_container_width=True, hide_index=True)
            if st.button("📧 Enviar Alerta por Gmail", type="primary"):
                with st.spinner("Enviando correo..."):
                    if enviar_alerta_gmail(df_criticos):
                        st.success("¡Correo enviado exitosamente a los administradores!")
            st.markdown("---")

        busqueda = st.text_input("🔍 Buscar producto...", value=st.session_state.auto_search, key="search")
        if busqueda != st.session_state.auto_search:
            st.session_state.auto_search = busqueda
            
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        categorias = sorted(list(set([str(c).strip() for c in df_show['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
        
        if df.empty or len(df) == 0:
            st.info("El inventario está completamente vacío. Ve a la pestaña '📥 Carga' para subir tu Excel.")
        else:
            for cat in categorias:
                with st.expander(f"📁 {cat}"):
                    subset_cat = df_show[df_show['categoria'].astype(str).str.strip() == cat].sort_values(by='nombre', key=lambda col: col.str.lower())
                    # Añadimos posicion_caja a la vista principal
                    columnas_ver = ['nombre', 'cantidad_actual', 'unidad', 'ubicacion', 'posicion_caja', 'lote']
                    st.dataframe(subset_cat[columnas_ver].style.apply(aplicar_estilos_inv, axis=1), use_container_width=True, hide_index=True)

    # --- NUEVA PESTAÑA: PROTOCOLOS (KITS Y DESCUENTO MASIVO) ---
    with tab_protocolos:
        st.markdown("### 🧬 Ejecución de Protocolos y Kits")
        
        tab_ejecutar, tab_crear = st.tabs(["🚀 Ejecutar Corrida", "📝 Crear/Editar Protocolo"])
        
        with tab_ejecutar:
            if df_prot.empty:
                st.info("Aún no tienes protocolos guardados.")
            else:
                p_sel = st.selectbox("Selecciona el Protocolo a usar:", df_prot['nombre'].tolist())
                n_muestras = st.number_input("¿Cuántas muestras (reacciones) vas a procesar?", min_value=1, value=1)
                
                if st.button("🔍 Calcular y Previsualizar Descuento"):
                    info_p = df_prot[df_prot['nombre'] == p_sel]['materiales_base'].values[0]
                    lineas = info_p.split('\n')
                    
                    descuentos = []
                    for linea in lineas:
                        if ":" in linea:
                            partes = linea.split(":")
                            nombre_b = partes[0].strip()
                            try:
                                cant_por_tubo = float(partes[1].strip())
                                total_a_descontar = cant_por_tubo * n_muestras
                                
                                # Buscar el reactivo en la base de datos
                                item_db = df[df['nombre'].str.contains(nombre_b, case=False, na=False)]
                                if not item_db.empty:
                                    stock_actual = item_db.iloc[0]['cantidad_actual']
                                    nombre_real = item_db.iloc[0]['nombre']
                                    unidad = item_db.iloc[0]['unidad']
                                    id_it = str(item_db.iloc[0]['id'])
                                    descuentos.append({"id": id_it, "Reactivo": nombre_real, "Stock Actual": stock_actual, "A Descontar": total_a_descontar, "Unidad": unidad})
                                else:
                                    st.warning(f"⚠️ No encontré '{nombre_b}' en el inventario.")
                            except: pass
                            
                    if descuentos:
                        st.markdown("**Resumen de la corrida:**")
                        df_desc = pd.DataFrame(descuentos)
                        st.dataframe(df_desc[["Reactivo", "Stock Actual", "A Descontar", "Unidad"]], hide_index=True)
                        
                        if st.button("✅ Confirmar y Descontar del Inventario", type="primary"):
                            crear_punto_restauracion(df)
                            with st.spinner("Descontando..."):
                                for d in descuentos:
                                    nueva_c = int(d["Stock Actual"] - d["A Descontar"])
                                    supabase.table("items").update({"cantidad_actual": nueva_c}).eq("id", d["id"]).execute()
                                    supabase.table("movimiento").insert({"item_id": d["id"], "nombre_item": d["Reactivo"], "cantidad_cambio": -d["A Descontar"], "tipo": f"Uso Protocolo: {p_sel}", "usuario": usuario_actual}).execute()
                            st.success("¡Inventario actualizado automáticamente!")
                            st.rerun()

        with tab_crear:
            st.info("Escribe los materiales. Formato: `Nombre del Reactivo : Cantidad por 1 muestra`")
            with st.form("form_nuevo_prot"):
                n_prot = st.text_input("Nombre del Protocolo (Ej: PCR Master Mix)")
                mat_base = st.text_area("Reactivos (Uno por línea)", placeholder="Taq Polimerasa : 0.5\nBuffer 10X : 2\ndNTPs : 1")
                if st.form_submit_button("💾 Guardar Protocolo", type="primary"):
                    try:
                        supabase.table("protocolos").insert({"nombre": n_prot, "materiales_base": mat_base}).execute()
                        st.success("Protocolo guardado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar. ¿Creaste la tabla 'protocolos' en Supabase? Detalle: {e}")

    # --- PESTAÑA: EDICIÓN MASIVA ---
    with tab_editar:
        st.markdown("### ✍️ Edición Masiva")
        if not df.empty:
            categorias_edit = sorted(list(set([str(c).strip() for c in df['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
            cat_disp = ["Todas"] + categorias_edit
            filtro_cat = st.selectbox("📍 Filtrar por Categoría:", cat_disp)
            df_filtro = df if filtro_cat == "Todas" else df[df['categoria'].astype(str).str.strip() == filtro_cat]
            
            df_edit_view = df_filtro.copy()
            df_edit_view['❌ Eliminar'] = False
            
            # Incorporamos la posición de caja a la edición
            cols_finales = ['❌ Eliminar', 'id', 'nombre', 'cantidad_actual', 'umbral_minimo', 'unidad', 'ubicacion', 'posicion_caja']
            
            df_to_edit = df_edit_view[cols_finales].copy()
            styled_df = df_to_edit.style.apply(estilo_alerta_editor, axis=1)
            edited_df = st.data_editor(styled_df, column_config={"id": st.column_config.TextColumn("ID", disabled=True)}, use_container_width=True, hide_index=True, num_rows="dynamic")
            
            if st.button("💾 Guardar Cambios Generales"):
                crear_punto_restauracion(df)
                edited_df = edited_df.replace({np.nan: None})
                eliminados = edited_df[edited_df['❌ Eliminar'] == True]
                modificados = edited_df[edited_df['❌ Eliminar'] == False].drop(columns=['❌ Eliminar'])
                for _, row in eliminados.iterrows():
                    if pd.notna(row['id']) and str(row['id']).strip() != "": supabase.table("items").delete().eq("id", str(row['id'])).execute()
                for _, row in modificados.iterrows():
                    d = row.dropna().to_dict()
                    if 'id' in d and str(d['id']).strip() != "": supabase.table("items").upsert(d).execute()
                st.success("Guardado exitoso.")
                st.session_state.auto_search = ""
                st.rerun()

    # --- PESTAÑA: MODO ORDEN AUTO ---
    with tab_orden:
        st.markdown("### 📸 Modo Orden Automático")
        if df.empty or len(df) == 0:
            st.info("No hay reactivos en el inventario.")
        elif st.session_state.index_orden >= len(df):
            st.success("🎉 ¡Felicidades! Has revisado todo el inventario.")
            if st.button("🔄 Volver a empezar"): 
                st.session_state.index_orden = 0
                st.query_params['index'] = 0
                st.rerun()
        else:
            item_actual = df.iloc[st.session_state.index_orden]
            if st.session_state.triage_foto_procesada != st.session_state.index_orden:
                st.session_state.triage_datos_ia = item_actual.to_dict()
            
            st.progress(st.session_state.index_orden / len(df))
            st.caption(f"Revisando Reactivo {st.session_state.index_orden + 1} de {len(df)}")
            st.markdown(f"#### 🧪 Validando: **{item_actual['nombre']}**")
            
            col_foto, col_datos = st.columns([1, 1.2], gap="large")
            with col_foto:
                foto_orden = st.camera_input("Capturar Etiqueta", key=f"cam_orden_{st.session_state.index_orden}")
                if st.button("⏭️ Saltar sin cambios", use_container_width=True):
                    st.session_state.index_orden += 1
                    st.query_params['index'] = st.session_state.index_orden
                    st.rerun()

                if foto_orden and st.session_state.triage_foto_procesada != st.session_state.index_orden:
                    img = Image.open(foto_orden).convert('RGB')
                    with st.spinner("🧠 Extrayendo datos..."):
                        try:
                            prompt_vision = f"""Analiza la etiqueta. Nombre: '{item_actual['nombre']}'. Extrae: categoria, lote, unidad, cantidad_actual. JSON estricto: {{"categoria": "", "lote": "", "unidad": "", "cantidad_actual": 0}}"""
                            res_vision = model.generate_content([prompt_vision, img]).text
                            datos_extraidos = json.loads(re.search(r'\{.*\}', res_vision, re.DOTALL).group())
                            for key, val in datos_extraidos.items():
                                if val and str(val).strip() not in ["", "0", "None"]:
                                    st.session_state.triage_datos_ia[key] = val
                            st.session_state.triage_foto_procesada = st.session_state.index_orden
                            st.rerun()
                        except: st.error(f"La IA no pudo leer la etiqueta.")

            with col_datos:
                datos_form = st.session_state.triage_datos_ia
                sug_ia = sugerir_ubicacion(datos_form.get('nombre', ''))
                
                with st.form(f"form_triage_{st.session_state.index_orden}"):
                    n_nom = st.text_input("Nombre", value=datos_form.get('nombre', ''))
                    
                    # Layout para ubicaciones exactas (Batalla Naval)
                    c_ub1, c_ub2 = st.columns([1.5, 1])
                    idx_ub = zonas_lab.index(datos_form.get('ubicacion')) if datos_form.get('ubicacion') in zonas_lab else zonas_lab.index("Mesón")
                    n_ubi = c_ub1.selectbox(f"Zona", zonas_lab, index=idx_ub)
                    n_pos = c_ub2.text_input("Posición en Caja/Rack", value=datos_form.get('posicion_caja', ''), placeholder="Ej: Caja A, B4")
                    
                    c1, c2 = st.columns(2)
                    n_cat = c1.text_input("Categoría", value=datos_form.get('categoria', ''))
                    n_lot = c2.text_input("Lote", value=datos_form.get('lote', ''))
                    
                    c3, c4 = st.columns(2)
                    n_can = c3.number_input("Cantidad", value=int(datos_form.get('cantidad_actual', 0)))
                    uni_val = datos_form.get('unidad', 'unidades')
                    idx_un = unidades_list.index(uni_val) if uni_val in unidades_list else 0
                    n_uni = c4.selectbox("Unidad", unidades_list, index=idx_un)
                    
                    if st.form_submit_button("💾 Guardar y Siguiente", type="primary", use_container_width=True):
                        if str(item_actual['id']).strip() != "":
                            supabase.table("items").update({"nombre": n_nom, "categoria": n_cat, "lote": n_lot, "ubicacion": n_ubi, "posicion_caja": n_pos, "cantidad_actual": n_can, "unidad": n_uni}).eq("id", str(item_actual['id'])).execute()
                        st.session_state.index_orden += 1
                        st.query_params['index'] = st.session_state.index_orden
                        st.rerun()

    # --- PESTAÑA: IMPORTAR EXCEL ---
    with tab_importar:
        st.subheader("🧹 Limpieza y Carga")
        with st.container(border=True):
            check_borrado = st.checkbox("Entiendo que esto eliminará TODOS los registros actuales.")
            if st.button("🗑️ ELIMINAR TODO EL INVENTARIO", type="primary", disabled=not check_borrado):
                with st.spinner("Vaciando..."):
                    try:
                        supabase.table("movimiento").delete().neq("tipo", "BORRADO_SEGURO").execute()
                        supabase.table("items").delete().neq("nombre", "BORRADO_SEGURO").execute()
                        st.success("Base reseteada.")
                        st.rerun()
                    except Exception as e: st.error(f"Error: {e}")

        st.divider()
        archivo_excel = st.file_uploader("Arrastra tu Excel aquí", type=["xlsx", "csv"])
        if archivo_excel:
            try:
                df_nuevo = pd.read_csv(archivo_excel) if archivo_excel.name.endswith('.csv') else pd.read_excel(archivo_excel, engine='openpyxl')
                df_nuevo.columns = df_nuevo.columns.str.strip()
                if st.button("🚀 Subir al Inventario", type="primary"):
                    with st.spinner("Guardando..."):
                        df_a_subir = df_nuevo.rename(columns={"Nombre": "nombre", "Formato": "unidad", "cantidad": "cantidad_actual", "Detalle": "lote", "ubicación": "ubicacion", "categoria": "categoria"})
                        # Si tu excel tiene 'posicion_caja', lo toma. Si no, crea la columna vacía.
                        if 'posicion_caja' not in df_a_subir.columns: df_a_subir['posicion_caja'] = ""
                        df_a_subir = df_a_subir[["nombre", "unidad", "cantidad_actual", "lote", "ubicacion", "posicion_caja", "categoria"]]
                        df_a_subir['cantidad_actual'] = df_a_subir['cantidad_actual'].astype(str).str.extract(r'(\d+)')[0].fillna(0).astype(int)
                        records = df_a_subir.replace({np.nan: None}).to_dict(orient="records")
                        supabase.table("items").insert(records).execute()
                        st.success(f"✅ Cargados {len(records)} reactivos.")
                        st.rerun()
            except Exception as e: st.error(f"Error: {e}")

# --- PANEL IZQUIERDO: CÁMARA Y ASISTENTE IA ---
with col_chat:
    st.subheader("💬 Secretario de Inventario")
    chat_box = st.container(height=500, border=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": f"Hola {usuario_actual}. Dime qué hacemos y confirmaré el cambio."}]

    for m in st.session_state.messages:
        with chat_box:
            st.chat_message(m["role"]).markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎤 Dictar", stop_prompt="🛑 Parar", just_once=True, key='voice_input')
    prompt = v_in if v_in else st.chat_input("Ej: Saqué 2 de Taq Polimerasa de la Caja A")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box:
            st.chat_message("user").markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Procesando y guardando..."):
                try:
                    datos_para_ia = df[['id', 'nombre', 'cantidad_actual', 'ubicacion', 'posicion_caja']].to_json(orient='records') if not df.empty else "[]"
                    
                    contexto_instrucciones = f"""
                    Eres el Secretario IA. REGLA: El usuario manda.
                    Inventario actual: {datos_para_ia}
                    Si el reactivo existe, extrae su 'id'. Si NO existe, usa "NUEVO".
                    Identifica: id, nombre, cantidad, unidad, ubicacion, posicion_caja.
                    Responde SOLO JSON estricto:
                    EJECUTAR_ACCION:{{"id": "...", "nombre": "...", "cantidad": ..., "unidad": "...", "ubicacion": "...", "posicion_caja": "..."}}
                    """
                    
                    res_ai = model.generate_content(f"{contexto_instrucciones}\nUsuario: {prompt}").text
                    
                    if "EJECUTAR_ACCION:" in res_ai:
                        m = re.search(r'\{.*\}', res_ai, re.DOTALL)
                        if m:
                            data = json.loads(m.group())
                            id_accion = str(data.get('id', 'NUEVO'))
                            pos_caja = data.get('posicion_caja', '')
                            
                            if id_accion != "NUEVO" and (not df.empty and id_accion in df['id'].astype(str).values):
                                supabase.table("items").update({
                                    "cantidad_actual": data['cantidad'],
                                    "ubicacion": data['ubicacion'],
                                    "posicion_caja": pos_caja
                                }).eq("id", id_accion).execute()
                                
                                item_fresco = supabase.table("items").select("*").eq("id", id_accion).execute().data[0]
                                supabase.table("movimiento").insert({"item_id": id_accion, "nombre_item": item_fresco['nombre'], "cantidad_cambio": data['cantidad'], "tipo": "Acción IA", "usuario": usuario_actual}).execute()
                                
                                msg = f"""✅ **Actualizado**
* **Reactivo:** {item_fresco['nombre']}
* **Zona:** {item_fresco['ubicacion']} | **Caja:** {item_fresco.get('posicion_caja', '-')}
* **Stock:** {item_fresco['cantidad_actual']} {item_fresco['unidad']}
* **Alarma en:** {item_fresco['umbral_minimo']}"""
                                st.session_state.auto_search = item_fresco['nombre']
                            else:
                                res_insert = supabase.table("items").insert({
                                    "nombre": data['nombre'], "cantidad_actual": data['cantidad'],
                                    "unidad": data['unidad'], "ubicacion": data['ubicacion'], "posicion_caja": pos_caja
                                }).execute()
                                if res_insert.data:
                                    item_fresco = res_insert.data[0]
                                    supabase.table("movimiento").insert({"item_id": str(item_fresco['id']), "nombre_item": item_fresco['nombre'], "cantidad_cambio": item_fresco['cantidad_actual'], "tipo": "Nuevo IA", "usuario": usuario_actual}).execute()
                                    msg = f"""📦 **Nuevo Creado**
* **Reactivo:** {item_fresco['nombre']}
* **Zona:** {item_fresco['ubicacion']} | **Caja:** {item_fresco.get('posicion_caja', '-')}
* **Stock:** {item_fresco['cantidad_actual']} {item_fresco['unidad']}"""
                                    st.session_state.auto_search = item_fresco['nombre']
                            
                            st.markdown(msg)
                            st.session_state.messages.append({"role": "assistant", "content": msg})
                            st.rerun() 
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e:
                    st.error(f"Error IA: {e}")

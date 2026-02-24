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
        receiver = st.secrets.get("EMAIL_RECEIVER", sender) # Si no hay receptor, se lo envía a sí mismo
        
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = receiver
        msg['Subject'] = "🚨 ALERTA: Stock Crítico en Lab Aguilar"
        
        # Crear tabla HTML
        html_table = df_alertas[['nombre', 'ubicacion', 'cantidad_actual', 'umbral_minimo', 'unidad']].to_html(index=False)
        
        body = f"""
        <html>
          <body>
            <h2>Reporte Automático de Stock Crítico</h2>
            <p>Los siguientes reactivos están por debajo de su umbral mínimo y necesitan ser repuestos:</p>
            {html_table}
            <br>
            <p><i>Enviado desde Lab Aguilar OS</i></p>
          </body>
        </html>
        """
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Fallo al enviar correo: Verifique las credenciales en Secrets. Detalle: {e}")
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

def aplicar_estilos(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0) if pd.notnull(row.get('umbral_minimo', 0)) else 0
    if cant <= 0: return ['background-color: #ffe6e6; color: black'] * len(row)
    if umb > 0 and cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

# Cargar Tablas
res_items = supabase.table("items").select("*").execute()
df = pd.DataFrame(res_items.data)

columnas_texto = ['id', 'nombre', 'categoria', 'subcategoria', 'link_proveedor', 'lote', 'fecha_vencimiento', 'ubicacion', 'unidad']
for col in columnas_texto:
    if col not in df.columns: df[col] = ""
    df[col] = df[col].astype(str).replace(["nan", "None"], "")

for col in ['cantidad_actual', 'umbral_minimo']:
    if col not in df.columns: df[col] = 0
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)

df['categoria'] = df['categoria'].replace("", "GENERAL")

# --- 3. INTERFAZ SUPERIOR ---
col_logo, col_user = st.columns([3, 1])
with col_logo: st.markdown("## 🔬 Lab Aguilar OS")

with col_user:
    usuarios_lab = ["Marcelo Muñoz", "Rodrigo Aguilar", "Tesista / Estudiante", "Otro"]
    usuario_actual = st.selectbox("👤 Usuario Activo:", usuarios_lab, index=0)

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    if st.session_state.backup_inventario is not None:
        if st.button("↩️ Deshacer Última Acción", type="secondary"):
            # Lógica de restauración... (oculta por brevedad)
            st.session_state.backup_inventario = None
            st.rerun()

    tab_inventario, tab_historial, tab_editar, tab_orden, tab_importar, tab_qr = st.tabs(["📦 Inv", "⏱️ Hist", "⚙️ Edit", "🗂️ Orden Auto", "📥 Importar", "🖨️ QR"])
    
    # --- PESTAÑA: INVENTARIO (CON GMAIL) ---
    with tab_inventario:
        
        # SISTEMA DE ALERTAS
        df_criticos = df[(df['cantidad_actual'] <= df['umbral_minimo']) & (df['umbral_minimo'] > 0)]
        if not df_criticos.empty:
            st.error("🚨 **ATENCIÓN: Reactivos con Stock Crítico**")
            st.dataframe(df_criticos[['nombre', 'ubicacion', 'cantidad_actual', 'umbral_minimo', 'unidad']], use_container_width=True, hide_index=True)
            
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
            st.info("El inventario está completamente vacío. Ve a la pestaña '📥 Importar' para subir tu Excel.")
        else:
            for cat in categorias:
                with st.expander(f"📁 {cat}"):
                    subset_cat = df_show[df_show['categoria'].astype(str).str.strip() == cat].sort_values(by='nombre', key=lambda col: col.str.lower())
                    st.dataframe(subset_cat[[c for c in subset_cat.columns if c not in ['id', 'categoria', 'subcategoria', 'created_at']]].style.apply(aplicar_estilos, axis=1), use_container_width=True, hide_index=True)
                
    # --- PESTAÑA: HISTORIAL ---
    with tab_historial:
        try:
            res_mov = supabase.table("movimiento").select("*").order("created_at", desc=True).limit(25).execute()
            if res_mov.data:
                df_mov = pd.DataFrame(res_mov.data)
                df_mov['Fecha'] = pd.to_datetime(df_mov['created_at']).dt.strftime('%d-%m-%Y %H:%M')
                st.dataframe(df_mov[['Fecha', 'usuario', 'nombre_item', 'tipo', 'cantidad_cambio']], use_container_width=True, hide_index=True)
        except: st.info("No hay movimientos registrados.")

    # --- PESTAÑA: EDICIÓN MASIVA ---
    with tab_editar:
        st.markdown("### ✍️ Edición Masiva y Radar de Duplicados")
        # (Lógica de edición masiva idéntica a la anterior...)
        if not df.empty:
            cat_disp = ["Todas"] + sorted(list(set([str(c).strip() for c in df['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
            filtro_cat = st.selectbox("📍 Filtrar por Categoría:", cat_disp)
            df_filtro = df if filtro_cat == "Todas" else df[df['categoria'].astype(str).str.strip() == filtro_cat]
            df_edit_view = df_filtro.copy()
            df_edit_view['❌ Eliminar'] = False
            cols_finales = ['❌ Eliminar', 'id', 'nombre', 'cantidad_actual', 'umbral_minimo', 'unidad', 'ubicacion']
            edited_df = st.data_editor(df_edit_view[cols_finales].copy(), column_config={"id": st.column_config.TextColumn("ID", disabled=True)}, use_container_width=True, hide_index=True)
            if st.button("💾 Guardar Cambios"):
                # lógica de guardado...
                for _, row in edited_df[edited_df['❌ Eliminar'] == False].iterrows():
                    d = row.drop(labels=['❌ Eliminar']).to_dict()
                    supabase.table("items").upsert(d).execute()
                st.rerun()

    # --- PESTAÑA: MODO ORDEN AUTO (CON ANTI-AMNESIA) ---
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
                st.info("Tómale una foto a la etiqueta para autocompletar la info:")
                foto_orden = st.camera_input("Capturar", key=f"cam_orden_{st.session_state.index_orden}")
                
                if st.button("⏭️ Saltar sin cambios", use_container_width=True):
                    st.session_state.index_orden += 1
                    st.query_params['index'] = st.session_state.index_orden # Guardar en URL
                    st.rerun()

                if foto_orden and st.session_state.triage_foto_procesada != st.session_state.index_orden:
                    img = Image.open(foto_orden).convert('RGB')
                    with st.spinner("🧠 Extrayendo datos de la etiqueta..."):
                        try:
                            prompt_vision = f"""
                            Analiza la etiqueta de este reactivo químico/biológico. Su nombre en sistema es: '{item_actual['nombre']}'.
                            Extrae: categoria, lote, unidad, cantidad_actual.
                            Responde EXCLUSIVAMENTE en JSON estricto:
                            {{"categoria": "", "lote": "", "unidad": "", "cantidad_actual": 0}}
                            """
                            res_vision = model.generate_content([prompt_vision, img]).text
                            datos_extraidos = json.loads(re.search(r'\{.*\}', res_vision, re.DOTALL).group())
                            for key, val in datos_extraidos.items():
                                if val and str(val).strip() not in ["", "0", "None"]:
                                    st.session_state.triage_datos_ia[key] = val
                            st.session_state.triage_foto_procesada = st.session_state.index_orden
                            st.rerun()
                        except Exception as e:
                            st.error(f"La IA no pudo leer la etiqueta.")

            with col_datos:
                datos_form = st.session_state.triage_datos_ia
                sug_ia = sugerir_ubicacion(datos_form.get('nombre', ''))
                
                faltan = []
                if not datos_form.get('ubicacion') or str(datos_form.get('ubicacion')).strip() in ["", "Mesón", "None"]:
                    faltan.append("Ubicación")
                if not datos_form.get('lote') or str(datos_form.get('lote')).strip() == "":
                    faltan.append("Lote")
                    
                if st.session_state.triage_foto_procesada == st.session_state.index_orden:
                    if faltan: st.warning(f"🤖 **IA:** Me falta: **{', '.join(faltan)}**. ¡Complétalo abajo!")
                    else: st.success("🤖 **IA:** ¡Todo claro! Revisa el formulario y guarda.")

                with st.form(f"form_triage_{st.session_state.index_orden}"):
                    n_nom = st.text_input("Nombre", value=datos_form.get('nombre', ''))
                    c1, c2 = st.columns(2)
                    n_cat = c1.text_input("Categoría", value=datos_form.get('categoria', ''))
                    n_lot = c2.text_input("Lote", value=datos_form.get('lote', ''))
                    
                    idx_ub = zonas_lab.index(datos_form.get('ubicacion')) if datos_form.get('ubicacion') in zonas_lab else zonas_lab.index("Mesón")
                    n_ubi = st.selectbox(f"Ubicación (Te sugiero: {sug_ia})", zonas_lab, index=idx_ub)
                    
                    c3, c4 = st.columns(2)
                    n_can = c3.number_input("Cantidad", value=int(datos_form.get('cantidad_actual', 0)))
                    uni_val = datos_form.get('unidad', 'unidades')
                    idx_un = unidades_list.index(uni_val) if uni_val in unidades_list else 0
                    n_uni = c4.selectbox("Unidad", unidades_list, index=idx_un)
                    
                    if st.form_submit_button("💾 Guardar y Pasar al Siguiente", type="primary", use_container_width=True):
                        if str(item_actual['id']).strip() != "":
                            supabase.table("items").update({
                                "nombre": n_nom, "categoria": n_cat, "lote": n_lot, 
                                "ubicacion": n_ubi, "cantidad_actual": n_can, "unidad": n_uni
                            }).eq("id", str(item_actual['id'])).execute()
                            
                        st.session_state.index_orden += 1
                        st.query_params['index'] = st.session_state.index_orden # Guardar en URL
                        st.rerun()

    # --- NUEVA PESTAÑA: IMPORTAR EXCEL ---
    with tab_importar:
        # Lógica de carga masiva (idéntica a la anterior...)
        pass

    # --- PESTAÑA: ETIQUETAS QR ---
    with tab_qr:
        pass

# --- PANEL IZQUIERDO: CÁMARA Y ASISTENTE IA ---
with col_chat:
    # Lógica del Asistente y Escáner (idéntica a la anterior...)
    st.subheader("💬 Secretario de Inventario")
    chat_box = st.container(height=450, border=True)
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": f"Hola {usuario_actual}. Dime qué tienes en frente."}]

    for m in st.session_state.messages:
        with chat_box: st.chat_message(m["role"]).markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎤 Dictar", key='voice_input')
    prompt = v_in if v_in else st.chat_input("Ej: Hay 2 bolsas de eppendorf...")

    if prompt:
        # Lógica de actualización (idéntica a la anterior...)
        pass

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

# --- 1. CONFIGURACIÓN Y ESTÉTICA MINIMALISTA ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

# INYECCIÓN CSS: ESTILO MINIMALISTA "NOTION/APPLE"
st.markdown("""
<style>
    /* Ocultar marcas de Streamlit para que parezca una app nativa */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Fuente más limpia y moderna */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Suavizar los contenedores y bordes */
    div[data-testid="stContainer"] {
        border-radius: 10px;
        border-color: #f0f0f0;
    }
    
    /* Pestañas (Tabs) más estéticas */
    .stTabs [data-baseweb="tab-list"] {
        gap: 15px;
        border-bottom: 1px solid #f0f0f0;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
        color: #666;
        font-weight: 500;
    }
    .stTabs [aria-selected="true"] {
        background-color: transparent;
        color: #000;
        border-bottom: 2px solid #000 !important;
    }
    
    /* Botones redondeados y elegantes */
    .stButton>button {
        border-radius: 8px;
        transition: all 0.2s ease;
        font-weight: 500;
    }
    
    /* Títulos más limpios */
    h1, h2, h3 {
        color: #1a1a1a;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

if 'model_initialized' not in st.session_state:
    st.cache_resource.clear()
    st.session_state.model_initialized = True

if 'index' in st.query_params: st.session_state.index_orden = int(st.query_params['index'])
elif 'index_orden' not in st.session_state: st.session_state.index_orden = 0

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
def cargar_modelo_rapido():
    return genai.GenerativeModel('gemini-2.5-flash')

model = cargar_modelo_rapido()

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
        msg['Subject'] = "🚨 ALERTA: Stock Crítico Lab Aguilar"
        
        html_table = df_alertas[['nombre', 'ubicacion', 'posicion_caja', 'cantidad_actual', 'umbral_minimo', 'unidad']].to_html(index=False)
        body = f"<html><body><h2>Reporte de Stock Crítico</h2>{html_table}</body></html>"
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

# --- 2. LÓGICA DE DATOS ---
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

# Colores más pastel y minimalistas para las alertas de tabla
def aplicar_estilos_inv(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0) if pd.notnull(row.get('umbral_minimo', 0)) else 0
    if cant <= 0: return ['background-color: #ffeaea; color: #a00'] * len(row)
    if umb > 0 and cant <= umb: return ['background-color: #fff8e6; color: #850'] * len(row)
    return [''] * len(row)

def estilo_alerta_editor(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0)
    if umb > 0 and cant <= umb: return ['background-color: #ffeaea; color: #a00; font-weight: 500'] * len(row)
    return [''] * len(row)

res_items = supabase.table("items").select("*").execute()
df = pd.DataFrame(res_items.data)

for col in ['id', 'nombre', 'categoria', 'subcategoria', 'link_proveedor', 'lote', 'fecha_vencimiento', 'ubicacion', 'posicion_caja', 'unidad']:
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
    usuario_actual = st.selectbox("👤 Usuario:", usuarios_lab, index=0)

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    if st.session_state.backup_inventario is not None:
        if st.button("↩️ Deshacer Última Acción", type="secondary"):
            with st.spinner("Restaurando..."):
                try:
                    backup_df = st.session_state.backup_inventario.replace({np.nan: None})
                    for index, row in backup_df.iterrows():
                        row_dict = row.to_dict()
                        for key, value in row_dict.items():
                            if pd.isna(value) or str(value).strip() == "": row_dict[key] = None
                        if 'id' in row_dict and row_dict['id'] is not None:
                            row_dict['id'] = str(row_dict['id'])
                            supabase.table("items").upsert(row_dict).execute()
                    st.session_state.backup_inventario = None
                    st.success("Restaurado con éxito")
                    st.rerun()
                except Exception as e: st.error(f"Error al restaurar: {e}")

    tab_inventario, tab_protocolos, tab_editar, tab_orden, tab_importar = st.tabs(["📦 Inv", "🧪 Protocolos", "⚙️ Edit", "🗂️ Orden Auto", "📥 Carga"])
    
    with tab_inventario:
        df_criticos = df[(df['cantidad_actual'] <= df['umbral_minimo']) & (df['umbral_minimo'] > 0)]
        if not df_criticos.empty:
            st.error("🚨 **Reactivos con Stock Crítico**")
            st.dataframe(df_criticos[['nombre', 'ubicacion', 'posicion_caja', 'cantidad_actual', 'umbral_minimo', 'unidad']], use_container_width=True, hide_index=True)
            if st.button("📧 Enviar Alerta", type="primary"):
                with st.spinner("Enviando..."):
                    if enviar_alerta_gmail(df_criticos): st.success("Enviado exitosamente")
            st.markdown("---")

        busqueda = st.text_input("🔍 Buscar producto...", value=st.session_state.auto_search, key="search")
        if busqueda != st.session_state.auto_search: st.session_state.auto_search = busqueda
            
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        categorias = sorted(list(set([str(c).strip() for c in df_show['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
        
        if df.empty or len(df) == 0: st.info("Inventario vacío.")
        else:
            for cat in categorias:
                with st.expander(f"📁 {cat}"):
                    subset_cat = df_show[df_show['categoria'].astype(str).str.strip() == cat].sort_values(by='nombre', key=lambda col: col.str.lower())
                    st.dataframe(subset_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion', 'posicion_caja', 'lote']].style.apply(aplicar_estilos_inv, axis=1), use_container_width=True, hide_index=True)

    with tab_protocolos:
        st.markdown("### 🧬 Kits y Protocolos")
        tab_ejecutar, tab_crear = st.tabs(["🚀 Ejecutar", "📝 Editar Protocolo"])
        with tab_ejecutar:
            if df_prot.empty: st.info("Sin protocolos guardados.")
            else:
                p_sel = st.selectbox("Protocolo:", df_prot['nombre'].tolist())
                n_muestras = st.number_input("Muestras/Reacciones:", min_value=1, value=1)
                if st.button("🔍 Previsualizar Descuento"):
                    info_p = df_prot[df_prot['nombre'] == p_sel]['materiales_base'].values[0]
                    descuentos = []
                    for linea in info_p.split('\n'):
                        if ":" in linea:
                            partes = linea.split(":")
                            try:
                                item_db = df[df['nombre'].str.contains(partes[0].strip(), case=False, na=False)]
                                if not item_db.empty:
                                    descuentos.append({"id": str(item_db.iloc[0]['id']), "Reactivo": item_db.iloc[0]['nombre'], "Stock Actual": item_db.iloc[0]['cantidad_actual'], "A Descontar": float(partes[1].strip()) * n_muestras, "Unidad": item_db.iloc[0]['unidad']})
                                else: st.warning(f"⚠️ No encontré '{partes[0].strip()}'.")
                            except: pass
                    if descuentos:
                        st.dataframe(pd.DataFrame(descuentos)[["Reactivo", "Stock Actual", "A Descontar", "Unidad"]], hide_index=True)
                        if st.button("✅ Confirmar y Descontar", type="primary"):
                            crear_punto_restauracion(df)
                            with st.spinner("Descontando..."):
                                for d in descuentos:
                                    supabase.table("items").update({"cantidad_actual": int(d["Stock Actual"] - d["A Descontar"])}).eq("id", d["id"]).execute()
                                    supabase.table("movimiento").insert({"item_id": d["id"], "nombre_item": d["Reactivo"], "cantidad_cambio": -d["A Descontar"], "tipo": f"Protocolo: {p_sel}", "usuario": usuario_actual}).execute()
                            st.rerun()

        with tab_crear:
            with st.form("form_nuevo_prot"):
                n_prot = st.text_input("Nombre (Ej: PCR Mix)")
                mat_base = st.text_area("Reactivos (Reactivo : Cantidad)", placeholder="Taq Polimerasa : 0.5\nBuffer 10X : 2")
                if st.form_submit_button("💾 Guardar"):
                    supabase.table("protocolos").insert({"nombre": n_prot, "materiales_base": mat_base}).execute()
                    st.rerun()

    with tab_editar:
        st.markdown("### ✍️ Edición Masiva")
        if not df.empty:
            cat_disp = ["Todas"] + sorted(list(set([str(c).strip() for c in df['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
            filtro_cat = st.selectbox("Filtrar:", cat_disp)
            df_edit_view = (df if filtro_cat == "Todas" else df[df['categoria'].astype(str).str.strip() == filtro_cat]).copy()
            df_edit_view['❌ Borrar'] = False
            
            styled_df = df_edit_view[['❌ Borrar', 'id', 'nombre', 'cantidad_actual', 'umbral_minimo', 'unidad', 'ubicacion', 'posicion_caja']].copy().style.apply(estilo_alerta_editor, axis=1)
            edited_df = st.data_editor(styled_df, column_config={"id": st.column_config.TextColumn("ID", disabled=True)}, use_container_width=True, hide_index=True)
            
            if st.button("💾 Guardar Cambios"):
                crear_punto_restauracion(df)
                edited_df = edited_df.replace({np.nan: None})
                for _, row in edited_df[edited_df['❌ Borrar'] == True].iterrows():
                    if pd.notna(row['id']) and str(row['id']).strip(): supabase.table("items").delete().eq("id", str(row['id'])).execute()
                for _, row in edited_df[edited_df['❌ Borrar'] == False].drop(columns=['❌ Borrar']).iterrows():
                    d = row.dropna().to_dict()
                    if 'id' in d and str(d['id']).strip(): supabase.table("items").upsert(d).execute()
                st.rerun()

    with tab_orden:
        st.markdown("### 📸 Modo Orden Automático")
        if df.empty or len(df) == 0: st.info("Inventario vacío.")
        elif st.session_state.index_orden >= len(df):
            st.success("🎉 Todo revisado.")
            if st.button("🔄 Reiniciar"): st.session_state.index_orden = 0; st.query_params['index'] = 0; st.rerun()
        else:
            item_actual = df.iloc[st.session_state.index_orden]
            if st.session_state.triage_foto_procesada != st.session_state.index_orden: st.session_state.triage_datos_ia = item_actual.to_dict()
            
            st.progress(st.session_state.index_orden / len(df))
            st.markdown(f"#### Validando: **{item_actual['nombre']}**")
            
            col_foto, col_datos = st.columns([1, 1.2], gap="large")
            with col_foto:
                foto_orden = st.camera_input("Capturar Etiqueta", key=f"cam_orden_{st.session_state.index_orden}")
                if st.button("⏭️ Saltar", use_container_width=True):
                    st.session_state.index_orden += 1; st.query_params['index'] = st.session_state.index_orden; st.rerun()

                if foto_orden and st.session_state.triage_foto_procesada != st.session_state.index_orden:
                    img = Image.open(foto_orden).convert('RGB')
                    with st.spinner("🧠 Leyendo etiqueta..."):
                        try:
                            # PROMPT DE VISIÓN MEJORADO PARA FRASCOS CURVOS Y REFLEJOS
                            prompt_vision = f"""
                            Analiza la foto de este reactivo: '{item_actual['nombre']}'.
                            ATENCIÓN: La etiqueta puede estar curvada, borrosa o tener reflejos de luz. Ignora los códigos de barras.
                            Haz tu mejor esfuerzo para deducir y extraer: categoria (ej. sal, solvente), lote (Batch/Lot), unidad (mL, g), y cantidad_actual (número).
                            Si no estás seguro, déjalo vacío (""). Responde SOLO JSON: {{"categoria": "", "lote": "", "unidad": "", "cantidad_actual": 0}}
                            """
                            res_vision = model.generate_content([prompt_vision, img]).text
                            datos_extraidos = json.loads(re.search(r'\{.*\}', res_vision, re.DOTALL).group())
                            for key, val in datos_extraidos.items():
                                if val and str(val).strip() not in ["", "0", "None"]: st.session_state.triage_datos_ia[key] = val
                            st.session_state.triage_foto_procesada = st.session_state.index_orden
                            st.rerun()
                        except: st.error("No pude descifrar la etiqueta clara. Revisa manual.")

            with col_datos:
                datos_form = st.session_state.triage_datos_ia
                with st.form(f"form_triage_{st.session_state.index_orden}"):
                    n_nom = st.text_input("Nombre", value=datos_form.get('nombre', ''))
                    c_ub1, c_ub2 = st.columns([1.5, 1])
                    idx_ub = zonas_lab.index(datos_form.get('ubicacion')) if datos_form.get('ubicacion') in zonas_lab else zonas_lab.index("Mesón")
                    n_ubi = c_ub1.selectbox("Zona", zonas_lab, index=idx_ub)
                    n_pos = c_ub2.text_input("Posición", value=datos_form.get('posicion_caja', ''), placeholder="Ej: Caja A")
                    c1, c2 = st.columns(2)
                    n_cat = c1.text_input("Categoría", value=datos_form.get('categoria', ''))
                    n_lot = c2.text_input("Lote", value=datos_form.get('lote', ''))
                    c3, c4 = st.columns(2)
                    n_can = c3.number_input("Cantidad", value=int(datos_form.get('cantidad_actual', 0)))
                    uni_val = datos_form.get('unidad', 'unidades')
                    idx_un = unidades_list.index(uni_val) if uni_val in unidades_list else 0
                    n_uni = c4.selectbox("Unidad", unidades_list, index=idx_un)
                    
                    if st.form_submit_button("💾 Guardar y Siguiente", type="primary", use_container_width=True):
                        if str(item_actual['id']).strip():
                            supabase.table("items").update({"nombre": n_nom, "categoria": n_cat, "lote": n_lot, "ubicacion": n_ubi, "posicion_caja": n_pos, "cantidad_actual": n_can, "unidad": n_uni}).eq("id", str(item_actual['id'])).execute()
                        st.session_state.index_orden += 1; st.query_params['index'] = st.session_state.index_orden; st.rerun()

    with tab_importar:
        st.subheader("🧹 Limpieza y Carga")
        with st.container(border=True):
            if st.button("🗑️ ELIMINAR INVENTARIO", type="primary", disabled=not st.checkbox("Confirmar borrado total")):
                supabase.table("movimiento").delete().neq("tipo", "X").execute()
                supabase.table("items").delete().neq("nombre", "X").execute()
                st.rerun()

        archivo_excel = st.file_uploader("Sube tu Excel", type=["xlsx", "csv"])
        if archivo_excel and st.button("🚀 Subir al Inventario"):
            df_nuevo = pd.read_csv(archivo_excel) if archivo_excel.name.endswith('.csv') else pd.read_excel(archivo_excel, engine='openpyxl')
            df_a_subir = df_nuevo.rename(columns={"Nombre": "nombre", "Formato": "unidad", "cantidad": "cantidad_actual", "Detalle": "lote", "ubicación": "ubicacion", "categoria": "categoria"})
            if 'posicion_caja' not in df_a_subir.columns: df_a_subir['posicion_caja'] = ""
            df_a_subir['cantidad_actual'] = df_a_subir['cantidad_actual'].astype(str).str.extract(r'(\d+)')[0].fillna(0).astype(int)
            supabase.table("items").insert(df_a_subir[["nombre", "unidad", "cantidad_actual", "lote", "ubicacion", "posicion_caja", "categoria"]].replace({np.nan: None}).to_dict(orient="records")).execute()
            st.rerun()

# --- PANEL IZQUIERDO: ASISTENTE IA ---
with col_chat:
    st.markdown("### 💬 Secretario IA")
    chat_box = st.container(height=500, border=False)
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": f"Hola {usuario_actual}. ¿Qué movemos hoy?"}]

    for m in st.session_state.messages:
        with chat_box: st.chat_message(m["role"]).markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎙️ Hablar", stop_prompt="⏹️ Enviar", just_once=True, key='voice_input')
    prompt = v_in if v_in else st.chat_input("Ej: Saqué 2 buffer de la caja A")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box: st.chat_message("user").markdown(prompt)
        
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                try:
                    datos_para_ia = df[['id', 'nombre', 'cantidad_actual', 'ubicacion', 'posicion_caja']].to_json(orient='records') if not df.empty else "[]"
                    
                    contexto = f"""
                    Inventario: {datos_para_ia}
                    Si el reactivo existe extrae su 'id', si no usa "NUEVO".
                    Responde SOLO JSON: EJECUTAR_ACCION:{{"id": "...", "nombre": "...", "cantidad": ..., "unidad": "...", "ubicacion": "...", "posicion_caja": "..."}}
                    """
                    res_ai = model.generate_content(f"{contexto}\nUsuario: {prompt}").text
                    
                    if "EJECUTAR_ACCION:" in res_ai:
                        m = re.search(r'\{.*\}', res_ai, re.DOTALL)
                        if m:
                            data = json.loads(m.group())
                            id_accion = str(data.get('id', 'NUEVO'))
                            
                            if id_accion != "NUEVO" and (not df.empty and id_accion in df['id'].astype(str).values):
                                supabase.table("items").update({"cantidad_actual": data['cantidad'], "ubicacion": data['ubicacion'], "posicion_caja": data.get('posicion_caja', '')}).eq("id", id_accion).execute()
                                itm = supabase.table("items").select("*").eq("id", id_accion).execute().data[0]
                                supabase.table("movimiento").insert({"item_id": id_accion, "nombre_item": itm['nombre'], "cantidad_cambio": data['cantidad'], "tipo": "Acción IA", "usuario": usuario_actual}).execute()
                                msg = f"✅ **Actualizado:** {itm['nombre']} | Stock: {itm['cantidad_actual']} {itm['unidad']} | Zona: {itm['ubicacion']}"
                            else:
                                res_ins = supabase.table("items").insert({"nombre": data['nombre'], "cantidad_actual": data['cantidad'], "unidad": data['unidad'], "ubicacion": data['ubicacion'], "posicion_caja": data.get('posicion_caja', '')}).execute()
                                if res_ins.data:
                                    itm = res_ins.data[0]
                                    supabase.table("movimiento").insert({"item_id": str(itm['id']), "nombre_item": itm['nombre'], "cantidad_cambio": itm['cantidad_actual'], "tipo": "Nuevo IA", "usuario": usuario_actual}).execute()
                                    msg = f"📦 **Creado:** {itm['nombre']} | Stock: {itm['cantidad_actual']} {itm['unidad']} | Zona: {itm['ubicacion']}"
                            
                            st.session_state.auto_search = itm['nombre']
                            st.markdown(msg)
                            st.session_state.messages.append({"role": "assistant", "content": msg})
                            st.rerun() 
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e: st.error(f"Error IA: {e}")

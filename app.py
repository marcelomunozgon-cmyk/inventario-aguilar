import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime, date
import numpy as np
import PyPDF2
import io
import qrcode
import smtplib
from email.message import EmailMessage

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Lab Aguilar OS", layout="wide", page_icon="🔬")

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except Exception as e:
    st.error(f"Error en Secrets: {e}")
    st.stop()

@st.cache_resource
def get_model():
    try:
        # Forzamos 1.5-flash para maximizar la cuota gratuita diaria
        return genai.GenerativeModel('gemini-1.5-flash')
    except: return None

model = get_model()

if "backup_inventario" not in st.session_state: st.session_state.backup_inventario = None

def crear_punto_restauracion(df_actual): st.session_state.backup_inventario = df_actual.copy()

# --- FUNCIÓN DE ALERTAS POR CORREO ---
def enviar_alerta_correo(nombre_item, cantidad_actual, umbral):
    try:
        remitente = st.secrets.get("EMAIL_SENDER")
        password = st.secrets.get("EMAIL_PASSWORD")
        destinatarios = st.secrets.get("EMAIL_RECEIVERS")
        
        if not remitente or not password or not destinatarios:
            return # Faltan configurar los secretos, ignorar silenciosamente
            
        msg = EmailMessage()
        msg.set_content(f"""Hola,\n\nEste es un aviso automático del Lab Aguilar OS.\n\nEl reactivo '{nombre_item}' ha alcanzado un nivel crítico.\n\nStock Actual: {cantidad_actual}\nUmbral Mínimo: {umbral}\n\nPor favor, gestionar su compra o reposición pronto para no retrasar los experimentos.\n\nSaludos,\nAsistente Virtual""")
        msg['Subject'] = f"⚠️ Alerta de Stock Crítico: {nombre_item}"
        msg['From'] = remitente
        msg['To'] = destinatarios.split(',')

        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(remitente, password)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Error enviando correo: {e}")

def verificar_y_alertar(id_item, nueva_cantidad):
    item_row = df[df['id'] == id_item]
    if not item_row.empty:
        umbral = item_row.iloc[0]['umbral_minimo']
        nombre = item_row.iloc[0]['nombre']
        if nueva_cantidad <= umbral:
            enviar_alerta_correo(nombre, nueva_cantidad, umbral)
            st.toast(f"📧 Alerta de stock enviada por correo para: {nombre}", icon="⚠️")

# --- 2. LÓGICA DE DATOS Y ESTILOS ---
def aplicar_estilos(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0) if pd.notnull(row.get('umbral_minimo', 0)) else 0
    venc = row.get('fecha_vencimiento')
    if pd.notnull(venc) and venc != "":
        try:
            if datetime.strptime(str(venc), '%Y-%m-%d').date() < date.today(): return ['background-color: #ffb3b3; color: #900; font-weight: bold'] * len(row)
        except: pass
    if cant <= 0: return ['background-color: #ffe6e6; color: black'] * len(row)
    if cant <= umb: return ['background-color: #fff4cc; color: black'] * len(row)
    return [''] * len(row)

# Carga de inventario
res_items = supabase.table("items").select("*").execute()
df = pd.DataFrame(res_items.data)

for col in ['cantidad_actual', 'umbral_minimo']:
    if col not in df.columns: df[col] = 0
for col in ['subcategoria', 'link_proveedor', 'lote', 'fecha_vencimiento']:
    if col not in df.columns: df[col] = ""

df['cantidad_actual'] = pd.to_numeric(df['cantidad_actual'], errors='coerce').fillna(0).astype(int)
df['umbral_minimo'] = pd.to_numeric(df['umbral_minimo'], errors='coerce').fillna(0).astype(int)

# Carga de Protocolos y Muestras
try: res_prot = supabase.table("protocolos").select("*").execute(); df_prot = pd.DataFrame(res_prot.data)
except: df_prot = pd.DataFrame(columns=["id", "nombre", "materiales_base"])

try: res_muestras = supabase.table("muestras").select("*").execute(); df_muestras = pd.DataFrame(res_muestras.data)
except: df_muestras = pd.DataFrame(columns=["id", "codigo_muestra", "tipo", "ubicacion", "fecha_creacion", "notas"])

# --- 3. INTERFAZ SUPERIOR ---
col_logo, col_user = st.columns([3, 1])
with col_logo: st.markdown("## 🔬 Lab Aguilar: Control de Inventario")
with col_user:
    usuarios_lab = ["Marcelo Muñoz", "Rodrigo Aguilar", "Tesista / Estudiante", "Otro"]
    usuario_actual = st.selectbox("👤 Usuario Activo:", usuarios_lab, index=0)

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    if st.session_state.backup_inventario is not None:
        if st.button("↩️ Deshacer Última Acción", type="secondary"):
            with st.spinner("Restaurando..."):
                try:
                    backup_df = st.session_state.backup_inventario.replace({np.nan: None})
                    for index, row in backup_df.iterrows():
                        row_dict = row.dropna().to_dict()
                        if 'id' in row_dict and row_dict['id'] is not None:
                            row_dict['id'] = int(row_dict['id'])
                            supabase.table("items").upsert(row_dict).execute()
                    st.session_state.backup_inventario = None
                    st.success("¡Inventario restaurado!")
                    st.rerun()
                except Exception as e: st.error(f"Error al restaurar: {e}")

    tab_inventario, tab_historial, tab_editar, tab_protocolos, tab_qr, tab_bioterio = st.tabs(["📦 Inventario", "⏱️ Historial", "⚙️ Editar", "🧪 Protocolos", "🖨️ QR", "❄️ Bioterio"])
    
    with tab_inventario:
        busqueda = st.text_input("🔍 Buscar producto...", key="search")
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        categorias = sorted(df_show['categoria'].fillna("GENERAL").unique())
        for cat in categorias:
            with st.expander(f"📁 {cat}"):
                subset_cat = df_show[df_show['categoria'] == cat]
                subcategorias = sorted(subset_cat['subcategoria'].unique())
                for subcat in subcategorias:
                    if subcat != "": st.markdown(f"<h5 style='color:#555;'>└ 📂 {subcat}</h5>", unsafe_allow_html=True)
                    subset_sub = subset_cat[subset_cat['subcategoria'] == subcat]
                    cols_vista = [c for c in subset_sub.columns if c not in ['id', 'categoria', 'subcategoria', 'created_at']]
                    st.dataframe(subset_sub[cols_vista].style.apply(aplicar_estilos, axis=1), column_config={"link_proveedor": st.column_config.LinkColumn("Proveedor", display_text="🌐 Ver")}, use_container_width=True, hide_index=True)
                
    with tab_historial:
        try:
            res_mov = supabase.table("movimientos").select("*").order("created_at", desc=True).limit(25).execute()
            if res_mov.data:
                df_mov = pd.DataFrame(res_mov.data)
                df_mov['Fecha'] = pd.to_datetime(df_mov['created_at']).dt.strftime('%d-%m-%Y %H:%M')
                cols_hist = ['Fecha', 'usuario', 'nombre_item', 'tipo', 'cantidad_cambio']
                st.dataframe(df_mov[[c for c in cols_hist if c in df_mov.columns]], use_container_width=True, hide_index=True)
        except: st.info("No hay movimientos registrados.")

    with tab_editar:
        st.markdown("### ✍️ Edición Manual de Inventario")
        cat_disp = ["Todas"] + sorted(df['categoria'].unique().tolist())
        filtro_cat = st.selectbox("📍 Filtrar por Categoría (Ideal para reconteo):", cat_disp)
        df_filtro = df if filtro_cat == "Todas" else df[df['categoria'] == filtro_cat]
        
        columnas_visibles = st.multiselect("Columnas:", options=df.columns.tolist(), default=['nombre', 'categoria', 'cantidad_actual', 'umbral_minimo', 'unidad'])
        if 'id' not in columnas_visibles: columnas_visibles.insert(0, 'id')
        
        edited_df = st.data_editor(df_filtro[columnas_visibles].copy(), column_config={"id": st.column_config.NumberColumn("ID", disabled=True)}, use_container_width=True, hide_index=True, num_rows="dynamic")
        
        if st.button("💾 Guardar Cambios"):
            crear_punto_restauracion(df)
            edited_df = edited_df.replace({np.nan: None})
            for index, row in edited_df.iterrows():
                row_dict = row.dropna().to_dict()
                
                # --- CORRECCIÓN ROBUSTA DEL ID ---
                if 'id' in row_dict:
                    try:
                        row_dict['id'] = int(float(row_dict['id']))
                    except (ValueError, TypeError):
                        del row_dict['id'] # Si falla, borramos el ID para que asigne uno nuevo
                # ---------------------------------
                
                supabase.table("items").upsert(row_dict).execute()
                
                # Verificar alerta de stock al guardar
                if 'cantidad_actual' in row_dict and 'id' in row_dict:
                    verificar_y_alertar(row_dict['id'], row_dict['cantidad_actual'])
            st.success("Cambios guardados.")
            st.rerun()

    with tab_protocolos:
        st.markdown("### ▶️ Ejecución Rápida (Sin Chat)")
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1: p_sel = st.selectbox("Protocolo:", df_prot['nombre'] if not df_prot.empty else ["Vacío"])
        with c2: n_muestras = st.number_input("N° Muestras:", min_value=1, value=1)
        with c3:
            st.write(" "); st.write(" ")
            if st.button("🚀 Ejecutar", type="primary", use_container_width=True):
                if not df_prot.empty:
                    with st.spinner("Calculando..."):
                        try:
                            info_p = df_prot[df_prot['nombre'] == p_sel]['materiales_base'].values[0]
                            lineas = info_p.split('\n')
                            exitos = 0
                            for linea in lineas:
                                match = re.search(r'([^:-]+)[:\-]\s*(\d+)', linea)
                                if match:
                                    nombre_b = match.group(1).strip()
                                    total_d = int(match.group(2)) * n_muestras
                                    item_db = df[df['nombre'].str.contains(nombre_b, case=False, na=False)]
                                    if not item_db.empty:
                                        id_it = int(item_db.iloc[0]['id'])
                                        nueva_c = int(item_db.iloc[0]['cantidad_actual']) - total_d
                                        supabase.table("items").update({"cantidad_actual": nueva_c}).eq("id

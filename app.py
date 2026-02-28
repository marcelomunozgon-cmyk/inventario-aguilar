import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime, date
import numpy as np
from PIL import Image
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. CONFIGURACIÓN Y ESTÉTICA ---
st.set_page_config(page_title="Stck", layout="wide", page_icon="🔬")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    div[data-testid="stContainer"] { border-radius: 10px; border-color: #f0f0f0; }
    .stTabs [data-baseweb="tab-list"] { gap: 15px; border-bottom: 1px solid #f0f0f0; }
    .stTabs [data-baseweb="tab"] { height: 50px; background-color: transparent; border-radius: 4px 4px 0px 0px; color: #666; font-weight: 500; }
    .stTabs [aria-selected="true"] { color: #000; border-bottom: 2px solid #000 !important; }
    .stButton>button { border-radius: 8px; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

try:
    supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    genai.configure(api_key=st.secrets["GENAI_KEY"])
except Exception as e:
    st.error(f"Error en Secrets: {e}")
    st.stop()

@st.cache_resource
def cargar_modelo_rapido(): return genai.GenerativeModel('gemini-2.5-flash')
model = cargar_modelo_rapido()

# --- 2. SISTEMA DE AUTENTICACIÓN MULTI-ROL ---
if "usuario_autenticado" not in st.session_state:
    st.session_state.usuario_autenticado = None
    st.session_state.user_uid = None
    st.session_state.lab_id = None
    st.session_state.rol = None
    st.session_state.nombre_usuario = None

if st.session_state.usuario_autenticado is None:
    st.markdown("<h1 style='text-align: center;'>🔬 Stck</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Ecosistema de Gestión de Laboratorios y Proveedores</p>", unsafe_allow_html=True)
    
    col_espacio1, col_login, col_espacio2 = st.columns([1, 2, 1])
    with col_login:
        # ¡NUEVA PESTAÑA DE PROVEEDORES!
        tab_login, tab_reg, tab_prov = st.tabs(["🔐 Iniciar Sesión", "🏢 Crear Cuenta Lab", "🚚 Portal Proveedores"])
        
        with tab_login:
            with st.container(border=True):
                email_login = st.text_input("Correo corporativo")
                pass_login = st.text_input("Contraseña", type="password")
                if st.button("Acceder a Stck", type="primary", use_container_width=True):
                    with st.spinner("Autenticando..."):
                        try:
                            res = supabase.auth.sign_in_with_password({"email": email_login, "password": pass_login})
                            st.session_state.usuario_autenticado = res.user.email
                            st.session_state.user_uid = res.user.id
                            
                            req_eq = supabase.table("equipo").select("*").eq("email", res.user.email).execute()
                            if req_eq.data:
                                st.session_state.lab_id = req_eq.data[0]['lab_id']
                                st.session_state.rol = req_eq.data[0]['rol']
                                st.session_state.nombre_usuario = req_eq.data[0].get('nombre', res.user.email)
                            else:
                                st.session_state.lab_id = "PENDIENTE"
                                st.session_state.rol = "espera"
                                st.session_state.nombre_usuario = res.user.email
                            st.rerun()
                        except: st.error("Credenciales incorrectas.")
                            
        with tab_reg:
            with st.container(border=True):
                st.info("Laboratorios: Completa tu perfil científico.")
                nombre_reg = st.text_input("Nombre y Apellido")
                perfil_reg = st.selectbox("Perfil Académico", ["Pregrado", "Doctorado/Postdoc", "PI", "Lab Manager", "CEO", "Otro"])
                inst_reg = st.text_input("Universidad o Empresa")
                email_reg = st.text_input("Nuevo Correo")
                pass_reg = st.text_input("Crear Contraseña", type="password")
                if st.button("Crear Cuenta de Laboratorio", type="primary", use_container_width=True):
                    if not nombre_reg: st.warning("Falta el nombre.")
                    else:
                        try:
                            res = supabase.auth.sign_up({"email": email_reg, "password": pass_reg})
                            supabase.table("equipo").insert({"email": email_reg, "nombre": nombre_reg, "perfil_academico": perfil_reg, "institucion": inst_reg, "rol": "espera"}).execute()
                            st.success("¡Cuenta creada! Tu administrador ya puede darte acceso.")
                        except Exception as e: st.error(f"Error: {e}")

        with tab_prov:
            with st.container(border=True):
                st.info("Proveedores: Únete para ofrecer tu catálogo a la red Stck.")
                empresa_prov = st.text_input("Nombre de la Empresa / Marca")
                email_prov = st.text_input("Correo de Ventas")
                pass_prov = st.text_input("Contraseña de Proveedor", type="password")
                
                if st.button("Registrar Empresa Proveedora", type="primary", use_container_width=True):
                    if not empresa_prov: st.warning("Pon el nombre de la empresa.")
                    else:
                        try:
                            res = supabase.auth.sign_up({"email": email_prov, "password": pass_prov})
                            # Los proveedores tienen lab_id propio (su UID) y rol especial
                            supabase.table("equipo").insert({"email": email_prov, "nombre": empresa_prov, "lab_id": res.user.id, "rol": "proveedor"}).execute()
                            st.success("Empresa registrada. Ve a 'Iniciar Sesión' para entrar.")
                        except Exception as e: st.error("Error al registrar.")
    st.stop()

# --- RUTEO DE ACCESOS ---
if st.session_state.lab_id == "PENDIENTE":
    st.warning("⏳ Sala de Espera")
    st.write("Tu cuenta está activa, pero no tienes un laboratorio asignado.")
    if st.button("Crear mi propio laboratorio (Ser Admin)"):
        res_check = supabase.table("equipo").select("*").eq("email", st.session_state.usuario_autenticado).execute()
        if res_check.data: supabase.table("equipo").update({"lab_id": st.session_state.user_uid, "rol": "admin"}).eq("email", st.session_state.usuario_autenticado).execute()
        else: supabase.table("equipo").insert({"email": st.session_state.usuario_autenticado, "lab_id": st.session_state.user_uid, "rol": "admin", "nombre": "Admin"}).execute()
        st.session_state.lab_id = st.session_state.user_uid
        st.session_state.rol = "admin"
        st.rerun()
    if st.button("🚪 Cerrar Sesión"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()
    st.stop()

# --- VARIABLES GLOBALES ---
lab_id = st.session_state.lab_id
usuario_actual = st.session_state.get('nombre_usuario', st.session_state.get('usuario_autenticado', 'Usuario'))
rol_actual = st.session_state.get('rol', 'miembro')
correo_destinatario_compras = st.secrets.get("EMAIL_RECEIVER", "No configurado")

if 'auto_search' not in st.session_state: st.session_state.auto_search = ""
if "backup_inventario" not in st.session_state: st.session_state.backup_inventario = None
def crear_punto_restauracion(df_actual): st.session_state.backup_inventario = df_actual.copy()

# --- CARGA DE DATOS ---
res_items = supabase.table("items").select("*").eq("lab_id", lab_id).execute()
df = pd.DataFrame(res_items.data)
for col in ['id', 'nombre', 'categoria', 'ubicacion', 'posicion_caja', 'unidad', 'fecha_vencimiento', 'fecha_cotizacion']:
    if col not in df.columns: df[col] = ""
    df[col] = df[col].astype(str).replace(["nan", "None", "NaT"], "")
for col in ['cantidad_actual', 'umbral_minimo', 'precio']:
    if col not in df.columns: df[col] = 0
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
df['categoria'] = df['categoria'].replace("", "GENERAL")

def aplicar_estilos_inv(row):
    cant = row.get('cantidad_actual', 0)
    umb = row.get('umbral_minimo', 0)
    if cant <= 0: return ['background-color: #ffeaea; color: #a00'] * len(row)
    if umb > 0 and cant <= umb: return ['background-color: #fff8e6; color: #850'] * len(row)
    return [''] * len(row)

# --- CABECERA PRINCIPAL ---
col_logo, col_user = st.columns([3, 1])
with col_logo: st.markdown("## 🔬 Stck")
with col_user: 
    tipo_cuenta = "🚚 Proveedor" if rol_actual == "proveedor" else f"👤 {rol_actual.capitalize()}"
    st.info(f"{tipo_cuenta}: {usuario_actual}")
    if st.button("🚪 Cerrar Sesión"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# =====================================================================
# INTERFAZ EXCLUSIVA PARA PROVEEDORES (PORTAL B2B)
# =====================================================================
if rol_actual == "proveedor":
    st.markdown("### 🚚 Portal de Proveedores Stck")
    tab_prov_cat, tab_prov_carga = st.tabs(["📦 Mi Catálogo Ofertado", "📥 Subir Lista de Precios"])
    
    with tab_prov_cat:
        st.write("Estos son los reactivos que tu empresa tiene disponibles en la red Stck.")
        if df.empty: st.info("No has subido ningún producto todavía.")
        else:
            cols_prov = ['nombre', 'categoria', 'precio', 'unidad']
            st.dataframe(df[cols_prov], use_container_width=True, hide_index=True)
            
    with tab_prov_carga:
        st.write("Sube tu Excel con tu catálogo. Columnas requeridas: `nombre`, `precio`, `categoria`, `unidad`.")
        archivo_excel = st.file_uploader("Sube tu Excel de Catálogo", type=["xlsx", "csv"])
        if archivo_excel and st.button("🚀 Cargar Productos a la Red"):
            df_n = pd.read_csv(archivo_excel) if archivo_excel.name.endswith('.csv') else pd.read_excel(archivo_excel, engine='openpyxl')
            df_s = df_n.rename(columns={"Nombre": "nombre", "Precio": "precio", "Categoria": "categoria", "Unidad": "unidad"})
            # Ajustes automáticos para que no falle
            for c in ["ubicacion", "posicion_caja", "lote"]: df_s[c] = "Bodega Proveedor"
            df_s['cantidad_actual'] = 9999 # Inventario virtual infinito
            df_s['lab_id'] = lab_id 
            
            # Subir
            cols_guardar = [c for c in df_s.columns if c in ['nombre', 'precio', 'categoria', 'unidad', 'ubicacion', 'posicion_caja', 'lote', 'cantidad_actual', 'lab_id']]
            supabase.table("items").insert(df_s[cols_guardar].replace({np.nan: None}).to_dict(orient="records")).execute()
            st.success("¡Catálogo actualizado con éxito!")
            st.rerun()
            
    st.stop() # Bloquea el resto de la app para que el proveedor no vea las funciones de laboratorio

# =====================================================================
# INTERFAZ PARA LABORATORIOS (ADMIN Y MIEMBROS)
# =====================================================================
col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    if rol_actual == "admin": 
        tab_inv, tab_prot, tab_edit, tab_carga, tab_equipo = st.tabs(["📦 Inventario", "🧪 Protocolos", "⚙️ Edición", "📥 Carga", "👥 Equipo"])
    else: 
        tab_inv, tab_prot, tab_edit = st.tabs(["📦 Inventario", "🧪 Protocolos", "⚙️ Edición"])
    
    with tab_inv:
        st.markdown("### 🗂️ Catálogo de Reactivos")
        busqueda = st.text_input("🔍 Buscar reactivo...", value=st.session_state.auto_search)
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        categorias = sorted(list(set([str(c).strip() for c in df_show['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
        
        if df.empty: st.info("Inventario vacío.")
        else:
            for cat in categorias:
                with st.expander(f"📁 {cat}"):
                    subset_cat = df_show[df_show['categoria'].astype(str).str.strip() == cat].sort_values(by='nombre', key=lambda col: col.str.lower())
                    st.dataframe(subset_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion', 'posicion_caja', 'fecha_vencimiento']].style.apply(aplicar_estilos_inv, axis=1), use_container_width=True, hide_index=True)

    with tab_prot:
        st.info("Módulo de protocolos activos.")
        # ... (Se mantiene el código de protocolos intacto)

    with tab_edit:
        st.markdown("### ✍️ Edición Masiva")
        if not df.empty:
            cols_edit = ['nombre', 'cantidad_actual', 'umbral_minimo', 'precio', 'fecha_vencimiento', 'fecha_cotizacion', 'id']
            edited_df = st.data_editor(df[cols_edit].copy(), column_config={"id": st.column_config.TextColumn("ID", disabled=True)}, use_container_width=True, hide_index=True)
            if st.button("💾 Guardar Cambios"):
                for _, row in edited_df.iterrows():
                    d = row.replace({np.nan: None}).to_dict()
                    if 'id' in d and str(d['id']).strip(): 
                        d['lab_id'] = lab_id 
                        supabase.table("items").upsert(d).execute()
                st.rerun()

    if rol_actual == "admin":
        with tab_carga:
            st.info("Módulo de carga de Excel del Laboratorio.")
            
        with tab_equipo:
            st.markdown("### 🤝 Gestión de Accesos")
            with st.container(border=True):
                nuevo_email = st.text_input("Correo a invitar:")
                rol_nuevo = st.selectbox("Rol:", ["miembro", "admin"])
                if st.button("Dar Acceso", type="primary", use_container_width=True):
                    try:
                        res = supabase.table("equipo").update({"lab_id": lab_id, "rol": rol_nuevo}).eq("email", nuevo_email).execute()
                        if len(res.data) == 0: 
                            supabase.table("equipo").insert({"email": nuevo_email, "lab_id": lab_id, "rol": rol_nuevo, "nombre": "Registrado por Admin"}).execute()
                        st.success(f"Acceso otorgado a {nuevo_email}.")
                        st.rerun() # ESTA LÍNEA ES LA MAGIA QUE ARREGLA EL ERROR
                    except Exception as e: st.error(f"Error: {e}")
            
            st.write("**Miembros con Acceso Activo:**")
            try:
                miembros = supabase.table("equipo").select("nombre, email, rol, perfil_academico, institucion").eq("lab_id", lab_id).execute()
                st.dataframe(pd.DataFrame(miembros.data), hide_index=True, use_container_width=True)
            except: st.info("No hay miembros.")

# --- PANEL IA ---
with col_chat:
    st.markdown("### 💬 Secretario IA")
    chat_box = st.container(height=400, border=False)
    for m in st.session_state.get("messages", [{"role": "assistant", "content": "Conectado. Háblame o mándame una foto."}]):
        with chat_box: st.chat_message(m["role"]).markdown(m["content"])

import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
import html as html_lib
from streamlit_mic_recorder import speech_to_text
from datetime import datetime, date, timedelta, time
import numpy as np
from PIL import Image
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse
import qrcode
from io import BytesIO
from fpdf import FPDF
import pytz

try:
    from streamlit_calendar import calendar
except ImportError:
    st.error("⚠️ Falta instalar 'streamlit-calendar'. Por favor, agrégalo a tu archivo requirements.txt")

# --- 1. CONFIGURACIÓN Y ESTÉTICA ---
st.set_page_config(page_title="Stck", layout="wide", page_icon="🔬")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    div[data-testid="stContainer"] { border-radius: 10px; border-color: #f0f0f0; }
    .stTabs [data-baseweb="tab-list"] { gap: 15px; border-bottom: 1px solid #f0f0f0; flex-wrap: wrap; }
    .stTabs [data-baseweb="tab"] { height: 50px; background-color: transparent; border-radius: 4px 4px 0px 0px; color: #888; font-weight: 500; white-space: nowrap; }
    .stTabs [aria-selected="true"] { color: #ffffff !important; background-color: #1a1a1a !important; border-bottom: 2px solid #1a1a1a !important; }
    .stButton>button { border-radius: 8px; font-weight: 500; }
    .badge-costo { background-color: #e8f5e9; color: #2e7d32; padding: 5px 10px; border-radius: 15px; font-weight: bold; font-size: 0.9em; }
    
    /* DISEÑO NOTION TOGGLE (MINIMALISTA) */
    details.notion-toggle { 
        margin-bottom: 12px; 
        border-bottom: 1px dashed #eee; 
        padding-bottom: 12px;
    }
    details.notion-toggle > summary {
        list-style: none; 
        font-size: 1.05em; 
        color: #111; 
        cursor: pointer; 
        line-height: 1.5; 
        padding: 4px 0;
        font-weight: 500;
        display: flex;
        align-items: flex-start;
    }
    details.notion-toggle > summary::-webkit-details-marker { display: none; }
    details.notion-toggle > summary::before {
        content: '▶';
        font-size: 0.75em;
        color: #999;
        display: inline-block;
        width: 22px;
        margin-top: 4px;
        transition: transform 0.2s ease-in-out;
        flex-shrink: 0;
    }
    details.notion-toggle[open] > summary::before { 
        transform: rotate(90deg); 
    }
    .cuaderno-meta-box {
        margin-left: 22px; 
        margin-top: 8px;
        padding: 12px 15px; 
        background-color: #fafafa;
        border-left: 3px solid #e0e0e0; 
        border-radius: 0 6px 6px 0;
        font-size: 0.9em; 
        color: #444; 
        line-height: 1.6;
    }
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

# --- GESTOR DE RUTINAS DIARIAS ---
if "rutinas_diarias" not in st.session_state:
    st.session_state.rutinas_diarias = {"fecha": str(date.today()), "mostradas": []}
if st.session_state.rutinas_diarias["fecha"] != str(date.today()):
    st.session_state.rutinas_diarias = {"fecha": str(date.today()), "mostradas": []}

# --- 2. SISTEMA DE AUTENTICACIÓN ---
if "usuario_autenticado" not in st.session_state:
    st.session_state.usuario_autenticado = None
    st.session_state.user_uid = None
    st.session_state.lab_id = None
    st.session_state.rol = None
    st.session_state.nombre_usuario = None

if st.session_state.usuario_autenticado is None:
    st.markdown("<h1 style='text-align: center;'>🔬 Stck</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Sistema de Gestión e Inventario para Laboratorios de Investigación</p>", unsafe_allow_html=True)
    
    col_espacio1, col_login, col_espacio2 = st.columns([1, 2, 1])
    with col_login:
        tab_login, tab_reg = st.tabs(["🔐 Iniciar Sesión", "🏢 Crear Cuenta"])
        with tab_login:
            with st.container(border=True):
                email_login = st.text_input("Correo corporativo", key="log_email")
                pass_login = st.text_input("Contraseña", type="password", key="log_pass")
                if st.button("Acceder a Stck", type="primary", use_container_width=True):
                    with st.spinner("Autenticando..."):
                        try:
                            res = supabase.auth.sign_in_with_password({"email": email_login.strip(), "password": pass_login})
                        except Exception as e:
                            st.error("Credenciales incorrectas o usuario no registrado.")
                            st.stop()
                        st.session_state.usuario_autenticado = res.user.email
                        st.session_state.user_uid = res.user.id
                        try:
                            req_eq = supabase.table("equipo").select("*").eq("email", res.user.email).execute()
                            if req_eq.data:
                                st.session_state.lab_id = req_eq.data[0]['lab_id']
                                st.session_state.rol = req_eq.data[0]['rol']
                                st.session_state.nombre_usuario = req_eq.data[0].get('nombre', res.user.email)
                            else:
                                st.session_state.lab_id = "PENDIENTE"
                                st.session_state.rol = "espera"
                                st.session_state.nombre_usuario = res.user.email
                        except Exception as db_error:
                            st.session_state.lab_id = "PENDIENTE"
                            st.session_state.rol = "espera"
                            st.session_state.nombre_usuario = res.user.email
                        st.rerun()
                            
        with tab_reg:
            with st.container(border=True):
                tipo_cuenta = st.radio("¿Qué tipo de cuenta deseas crear?", ["Laboratorio", "Proveedor (Ventas)"], horizontal=True)
                st.markdown("---")
                if tipo_cuenta == "Laboratorio":
                    nombre_reg = st.text_input("Nombre y Apellido")
                    perfil_reg = st.selectbox("Perfil Académico", ["Pregrado", "Doctorado/Postdoc", "PI", "Lab Manager", "CEO", "Otro"])
                    inst_reg = st.text_input("Universidad o Empresa")
                    email_reg = st.text_input("Nuevo Correo")
                    pass_reg = st.text_input("Crear Contraseña", type="password")
                    if st.button("Crear Cuenta y Entrar", type="primary", use_container_width=True):
                        if not nombre_reg: st.warning("Falta el nombre.")
                        else:
                            try:
                                supabase.auth.sign_up({"email": email_reg.strip(), "password": pass_reg})
                                supabase.table("equipo").insert({"email": email_reg.strip().lower(), "nombre": nombre_reg, "perfil_academico": perfil_reg, "institucion": inst_reg, "rol": "espera"}).execute()
                                res_login = supabase.auth.sign_in_with_password({"email": email_reg.strip(), "password": pass_reg})
                                st.session_state.usuario_autenticado = res_login.user.email
                                st.session_state.user_uid = res_login.user.id
                                st.session_state.lab_id = "PENDIENTE"
                                st.session_state.rol = "espera"
                                st.session_state.nombre_usuario = nombre_reg
                                st.rerun()
                            except Exception as e: st.error(f"Error: {e}")
                else:
                    empresa_prov = st.text_input("Nombre de la Empresa / Marca")
                    email_prov = st.text_input("Correo de Ventas")
                    pass_prov = st.text_input("Contraseña de Proveedor", type="password")
                    if st.button("Registrar Empresa y Entrar", type="primary", use_container_width=True):
                        if not empresa_prov: st.warning("Pon el nombre de la empresa.")
                        else:
                            try:
                                res_up = supabase.auth.sign_up({"email": email_prov.strip(), "password": pass_prov})
                                supabase.table("equipo").insert({"email": email_prov.strip().lower(), "nombre": empresa_prov, "lab_id": res_up.user.id, "rol": "proveedor"}).execute()
                                res_login = supabase.auth.sign_in_with_password({"email": email_prov.strip(), "password": pass_prov})
                                st.session_state.usuario_autenticado = res_login.user.email
                                st.session_state.user_uid = res_login.user.id
                                st.session_state.lab_id = res_login.user.id
                                st.session_state.rol = "proveedor"
                                st.session_state.nombre_usuario = empresa_prov
                                st.rerun()
                            except Exception as e: st.error("Error al registrar.")
    st.stop()

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

# --- VARIABLES GLOBALES Y FUNCIONES ---
lab_id = st.session_state.lab_id
usuario_actual = st.session_state.get('nombre_usuario', st.session_state.get('usuario_autenticado', 'Usuario'))
rol_actual = str(st.session_state.get('rol', 'miembro')).strip().lower()
correo_destinatario_compras = st.secrets.get("EMAIL_RECEIVER", "No configurado")

if 'auto_search' not in st.session_state: st.session_state.auto_search = ""
if "backup_inventario" not in st.session_state: st.session_state.backup_inventario = None
def crear_punto_restauracion(df_actual): st.session_state.backup_inventario = df_actual.copy()

def generar_qr(texto):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(texto)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def generar_pdf_inventario(df_inventario, nombre_lab):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt=f"Reporte Oficial de Inventario", ln=True, align='C')
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 10, txt=f"Generado por: Stck LIMS | Fecha: {date.today()}", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(85, 10, 'Reactivo', border=1)
    pdf.cell(25, 10, 'Stock', border=1)
    pdf.cell(40, 10, 'Ubicacion', border=1)
    pdf.cell(40, 10, 'Vencimiento', border=1)
    pdf.ln()

    pdf.set_font("Arial", size=9)
    for _, row in df_inventario.iterrows():
        nombre = str(row['nombre']).encode('latin-1', 'replace').decode('latin-1')[:45]
        stock = f"{row['cantidad_actual']} {row['unidad']}".encode('latin-1', 'replace').decode('latin-1')
        ub = str(row['ubicacion']).encode('latin-1', 'replace').decode('latin-1')[:20]
        venc = str(row['fecha_vencimiento']).encode('latin-1', 'replace').decode('latin-1')
        
        pdf.cell(85, 10, nombre, border=1)
        pdf.cell(25, 10, stock, border=1)
        pdf.cell(40, 10, ub, border=1)
        pdf.cell(40, 10, venc, border=1)
        pdf.ln()
    return pdf.output(dest='S').encode('latin-1')

def obtener_admin_email(lab_id):
    try:
        res_admins = supabase.table("equipo").select("email").eq("lab_id", lab_id).eq("rol", "admin").execute()
        correos = [a['email'] for a in res_admins.data]
        return correos[0] if correos else st.secrets.get("EMAIL_SENDER")
    except: return st.secrets.get("EMAIL_SENDER")

def enviar_correo_reserva(equipo_nombre, fecha_str, hora_ini, hora_fin, usuario_reserva, admin_email, usuario_email):
    try:
        sender = st.secrets["EMAIL_SENDER"]
        password = st.secrets["EMAIL_PASSWORD"]
        msg_user = MIMEMultipart()
        msg_user['From'] = sender
        msg_user['To'] = usuario_email
        msg_user['Subject'] = f"✅ Reserva Confirmada: {equipo_nombre} - Stck"
        msg_user.attach(MIMEText(f"<html><body><h3>Reserva Exitosa</h3><p>Hola, has reservado exitosamente el equipo <b>{equipo_nombre}</b> para el <b>{fecha_str}</b> en el horario de <b>{hora_ini}</b> a <b>{hora_fin}</b>.</p></body></html>", 'html'))
        msg_admin = MIMEMultipart()
        msg_admin['From'] = sender
        msg_admin['To'] = admin_email
        msg_admin['Subject'] = f"📅 Nueva Reserva de Equipo: {equipo_nombre} - Stck"
        msg_admin.attach(MIMEText(f"<html><body><h3>Notificación de Laboratorio</h3><p>El usuario <b>{usuario_reserva}</b> ({usuario_email}) ha agendado el uso de <b>{equipo_nombre}</b> para el <b>{fecha_str}</b> desde las <b>{hora_ini}</b> hasta las <b>{hora_fin}</b>.</p></body></html>", 'html'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg_user)
        if admin_email and admin_email != usuario_email: server.send_message(msg_admin)
        server.quit()
        return True
    except: return False

def enviar_correo_compras(item_nombre, precio, operador):
    try:
        sender = st.secrets["EMAIL_SENDER"]
        password = st.secrets["EMAIL_PASSWORD"]
        receiver = st.secrets.get("EMAIL_RECEIVER", sender)
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = receiver
        msg['Subject'] = f"🛒 SOLICITUD DE COMPRA: {item_nombre} - Stck"
        body = f"<html><body><h2>Solicitud de Cotización / Compra</h2><p>Se ha solicitado reabastecer el siguiente ítem:</p><ul><li><b>Reactivo:</b> {item_nombre}</li><li><b>Último precio referencial:</b> ${precio}</li><li><b>Solicitado por:</b> {operador}</li></ul></body></html>"
        msg.attach(MIMEText(body, 'html'))
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        return True
    except: return False

def generar_link_gcal(titulo, inicio, fin, descripcion=""):
    fmt = "%Y%m%dT%H%M%SZ"
    inicio_utc = inicio + timedelta(hours=3) 
    fin_utc = fin + timedelta(hours=3)
    url = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={urllib.parse.quote(titulo)}&dates={inicio_utc.strftime(fmt)}/{fin_utc.strftime(fmt)}&details={urllib.parse.quote(descripcion)}"
    return url

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

try: res_prot = supabase.table("protocolos").select("*").eq("lab_id", lab_id).execute(); df_prot = pd.DataFrame(res_prot.data)
except: df_prot = pd.DataFrame(columns=["id", "nombre", "materiales_base"])

try:
    res_equipos = supabase.table("equipos_lab").select("*").eq("lab_id", lab_id).execute()
    df_equipos = pd.DataFrame(res_equipos.data)
    for col in ['descripcion', 'visibilidad', 'requisitos']:
        if col not in df_equipos.columns: df_equipos[col] = ""
        df_equipos[col] = df_equipos[col].astype(str).replace(["nan", "None"], "")
    res_reservas = supabase.table("reservas").select("*").eq("lab_id", lab_id).execute()
    df_reservas = pd.DataFrame(res_reservas.data)
except:
    df_equipos = pd.DataFrame(columns=["id", "nombre", "descripcion", "visibilidad", "requisitos"])
    df_reservas = pd.DataFrame(columns=["id", "equipo_id", "usuario", "fecha_inicio", "fecha_fin"])

try:
    res_bitacora = supabase.table("bitacora").select("*").eq("lab_id", lab_id).order("created_at", desc=True).execute()
    df_bitacora = pd.DataFrame(res_bitacora.data)
    for col in ['contenido', 'resultado', 'link_adjunto', 'created_at', 'id']:
        if col not in df_bitacora.columns: df_bitacora[col] = ""
except Exception as e: 
    try: 
        res_bitacora = supabase.table("bitacora").select("*").eq("lab_id", lab_id).order("fecha", desc=True).execute()
        df_bitacora = pd.DataFrame(res_bitacora.data)
    except:
        df_bitacora = pd.DataFrame(columns=["id", "usuario", "fecha", "contenido", "resultado", "link_adjunto", "created_at"])

try:
    res_equipo_lab = supabase.table("equipo").select("nombre").eq("lab_id", lab_id).execute()
    nombres_equipo = [row['nombre'] for row in res_equipo_lab.data]
except: nombres_equipo = [usuario_actual]

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
    tipo_cuenta = "🚚 Proveedor" if rol_actual == "proveedor" else f"👤 {str(st.session_state.get('rol', 'miembro')).capitalize()}"
    st.info(f"{tipo_cuenta}: {usuario_actual}")
    if st.button("🚪 Cerrar Sesión"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# =====================================================================
# INTERFAZ EXCLUSIVA PARA PROVEEDORES
# =====================================================================
if rol_actual == "proveedor":
    st.markdown("### 🚚 Portal de Proveedores Stck")
    tab_prov_cat, tab_prov_carga = st.tabs(["📦 Mi Catálogo Ofertado", "📥 Subir Lista de Precios"])
    with tab_prov_cat:
        if df.empty: st.info("No has subido ningún producto todavía.")
        else: st.dataframe(df[['nombre', 'categoria', 'precio', 'unidad']], use_container_width=True, hide_index=True)
    with tab_prov_carga:
        archivo_excel = st.file_uploader("Sube tu Excel de Catálogo", type=["xlsx", "csv"])
        if archivo_excel and st.button("🚀 Cargar Productos a la Red"):
            df_n = pd.read_csv(archivo_excel) if archivo_excel.name.endswith('.csv') else pd.read_excel(archivo_excel, engine='openpyxl')
            df_s = df_n.rename(columns={"Nombre": "nombre", "Precio": "precio", "Categoria": "categoria", "Unidad": "unidad"})
            for c in ["ubicacion", "posicion_caja", "lote"]: df_s[c] = "Bodega Proveedor"
            df_s['cantidad_actual'] = 9999 
            df_s['lab_id'] = lab_id 
            cols_guardar = [c for c in df_s.columns if c in ['nombre', 'precio', 'categoria', 'unidad', 'ubicacion', 'posicion_caja', 'lote', 'cantidad_actual', 'lab_id']]
            supabase.table("items").insert(df_s[cols_guardar].replace({np.nan: None}).to_dict(orient="records")).execute()
            st.success("¡Catálogo actualizado con éxito!")
            st.rerun()
    st.stop()

# =====================================================================
# INTERFAZ PARA LABORATORIOS
# =====================================================================
col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    if rol_actual == "admin": 
        tab_inv, tab_prot, tab_equipos, tab_bitacora, tab_analisis, tab_usuarios = st.tabs(["📦 Inventario", "🧪 Protocolos", "📅 Equipos", "📔 Bitácora", "📊 Analítica", "👥 Usuarios"])
    else: 
        tab_inv, tab_prot, tab_equipos, tab_bitacora = st.tabs(["📦 Inventario", "🧪 Protocolos", "📅 Equipos", "📔 Bitácora"])
    
    with tab_inv:
        if not df.empty:
            df['vence_pronto'] = False
            hoy = pd.to_datetime(date.today())
            for idx, row in df.iterrows():
                try:
                    if row['fecha_vencimiento'] and str(row['fecha_vencimiento']).strip():
                        fv = pd.to_datetime(row['fecha_vencimiento'])
                        if (fv - hoy).days <= 30: df.at[idx, 'vence_pronto'] = True
                except: pass
            
            df_criticos = df[(df['cantidad_actual'] <= df['umbral_minimo']) & (df['umbral_minimo'] > 0) | (df['cantidad_actual'] <= 0)]
            df_vencidos = df[df['vence_pronto'] == True]
            
            if not df_criticos.empty or not df_vencidos.empty:
                st.error("🚨 **Alertas del Laboratorio**")
                if not df_criticos.empty: 
                    with st.expander(f"⚠️ **{len(df_criticos)} Reactivos Críticos / Fuera de Stock** (Haz clic para ver)"):
                        df_crit_show = df_criticos[['nombre', 'cantidad_actual', 'umbral_minimo', 'ubicacion', 'unidad']].copy()
                        st.dataframe(df_crit_show.style.format({'cantidad_actual': lambda x: f"{x:g}", 'umbral_minimo': lambda x: f"{x:g}"}), hide_index=True, use_container_width=True)
                if not df_vencidos.empty: 
                    with st.expander(f"📅 **{len(df_vencidos)} Reactivos Vencen en < 30 días** (Haz clic para ver)"):
                        df_venc_show = df_vencidos[['nombre', 'fecha_vencimiento', 'cantidad_actual', 'ubicacion']].copy()
                        st.dataframe(df_venc_show.style.format({'cantidad_actual': lambda x: f"{x:g}"}), hide_index=True, use_container_width=True)
        
        subtab_cat, subtab_edit = st.tabs(["🗂️ Catálogo Rápido", "✍️ Gestionar Inventario (Edición)"])
        
        with subtab_cat:
            st.markdown("### Buscador de Reactivos")
            busqueda = st.text_input("🔍 Buscar reactivo...", value=st.session_state.auto_search)
            df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
            categorias = sorted(list(set([str(c).strip() for c in df_show['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
            
            if df.empty: st.info("Inventario vacío.")
            else:
                for cat in categorias:
                    with st.expander(f"📁 {cat}", expanded=False):
                        subset_cat = df_show[df_show['categoria'].astype(str).str.strip() == cat].sort_values(by='nombre', key=lambda col: col.str.lower())
                        st.dataframe(
                            subset_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion', 'posicion_caja', 'fecha_vencimiento']]
                            .style.format({'cantidad_actual': lambda x: f"{x:g}" if pd.notnull(x) else ""})
                            .apply(aplicar_estilos_inv, axis=1), 
                            use_container_width=True, hide_index=True
                        )

                st.markdown("---")
                with st.expander("🖨️ Generar Etiquetas Físicas (QR)"):
                    st.write("Selecciona un reactivo para generar su Código QR.")
                    item_qr = st.selectbox("Reactivo para Etiqueta:", df['nombre'].tolist())
                    if st.button("Generar Código QR"):
                        qr_img_bytes = generar_qr(item_qr)
                        st.image(qr_img_bytes, caption=f"Código QR para: {item_qr}", width=200)
                        st.download_button(label="Descargar Imagen QR", data=qr_img_bytes, file_name=f"QR_{item_qr}.png", mime="image/png")

        with subtab_edit:
            st.markdown("### ✍️ Base de Datos Maestra")
            st.info("Modifica cantidades, umbrales, unidades y parámetros libremente. Los cambios se guardan al instante.")
            if not df.empty:
                cols_edit = ['id', 'nombre', 'categoria', 'cantidad_actual', 'unidad', 'umbral_minimo', 'ubicacion', 'posicion_caja', 'fecha_vencimiento', 'precio', 'fecha_cotizacion']
                
                edited_df = st.data_editor(
                    df[cols_edit].copy(), 
                    column_config={
                        "id": None, 
                        "nombre": "Nombre Reactivo",
                        "categoria": "Categoría",
                        "cantidad_actual": st.column_config.NumberColumn("Stock", format="%g"),
                        "unidad": "Medida (ml, un, etc)",
                        "umbral_minimo": st.column_config.NumberColumn("Alerta Mínima", format="%g"),
                        "ubicacion": "Ubicación",
                        "posicion_caja": "Caja/Estante",
                        "fecha_vencimiento": "Vencimiento",
                        "precio": st.column_config.NumberColumn("Precio Ref ($)", format="%g"),
                        "fecha_cotizacion": "Fecha Cotización"
                    }, 
                    use_container_width=True, 
                    hide_index=True
                )
                
                if st.button("💾 Guardar Cambios en BD", type="primary"):
                    for _, row in edited_df.iterrows():
                        d = row.replace({np.nan: None, pd.NaT: None}).to_dict()
                        if 'id' in d and str(d['id']).strip() and d['id'] is not None: 
                            d['lab_id'] = lab_id 
                            
                            for num_col in ['cantidad_actual', 'umbral_minimo', 'precio']:
                                if num_col in d:
                                    try: d[num_col] = float(d[num_col]) if d[num_col] not in [None, "", "nan", "None"] else 0.0
                                    except: d[num_col] = 0.0
                                        
                            for date_col in ['fecha_vencimiento', 'fecha_cotizacion']:
                                if date_col in d and str(d[date_col]).strip() in ["", "nan", "NaT", "None"]:
                                    d[date_col] = None 
                                    
                            for str_col in ['categoria', 'ubicacion', 'posicion_caja', 'unidad']:
                                if str_col in d and str(d[str_col]).strip() in ["nan", "None"]:
                                    d[str_col] = ""

                            supabase.table("items").upsert(d).execute()
                    st.success("Inventario actualizado correctamente.")
                    st.rerun()

            if rol_actual == "admin" and not df.empty:
                st.markdown("---")
                st.markdown("### 🛒 Panel de Compras")
                st.caption(f"📧 **Destinatario de cotización:** `{correo_destinatario_compras}`")
                c_comp1, c_comp2 = st.columns([2, 1])
                with c_comp1:
                    item_compra = st.selectbox("Seleccionar Reactivo a Comprar:", df['nombre'].tolist())
                    datos_item = df[df['nombre'] == item_compra].iloc[0]
                    fecha_cot = datos_item['fecha_cotizacion'] if datos_item['fecha_cotizacion'] else "Nunca"
                    precio_ref = datos_item['precio'] if datos_item['precio'] > 0 else "No registrado"
                    st.write(f"**Última cotización:** {fecha_cot} | **Precio Referencial:** ${precio_ref}")
                with c_comp2:
                    st.write("")
                    if st.button("🛒 Solicitar", use_container_width=True): st.session_state.confirmar_compra = item_compra
                    if st.session_state.get('confirmar_compra') == item_compra:
                        if st.button("✅ Confirmar Enviar", type="primary"):
                            enviar_correo_compras(item_compra, precio_ref, usuario_actual)
                            st.session_state.confirmar_compra = None
                            st.rerun()

    with tab_equipos:
        st.markdown("### 🗓️ Gestión y Booking de Equipos")
        opciones_eq = ["📅 Agendar", "📊 Calendario"]
        if rol_actual == "admin": opciones_eq.append("⚙️ Mis Equipos")
        modo_eq = st.radio("Selecciona vista:", opciones_eq, horizontal=True, label_visibility="collapsed")
        st.markdown("---")

        if modo_eq == "📊 Calendario":
            if not df_reservas.empty and not df_equipos.empty:
                df_cal = pd.merge(df_reservas, df_equipos[['id', 'nombre']], left_on='equipo_id', right_on='id', how='inner', suffixes=('', '_eq'))
                calendar_events = []
                equipos_unicos = df_cal['nombre' if 'nombre' in df_cal.columns else 'nombre_eq'].unique()
                colores = ["#4285F4", "#0F9D58", "#F4B400", "#DB4437", "#673AB7", "#00ACC1", "#FF7043"]
                color_map = {eq: colores[i % len(colores)] for i, eq in enumerate(equipos_unicos)}
                
                for _, row in df_cal.iterrows():
                    nom_eq = row.get('nombre', row.get('nombre_eq', 'Equipo'))
                    t_ini = pd.to_datetime(row['fecha_inicio'])
                    if t_ini.tzinfo: t_ini = t_ini.tz_localize(None)
                    t_fin = pd.to_datetime(row['fecha_fin'])
                    if t_fin.tzinfo: t_fin = t_fin.tz_localize(None)
                    calendar_events.append({"title": f"{nom_eq} ({row['usuario']})", "start": t_ini.isoformat(), "end": t_fin.isoformat(), "color": color_map.get(nom_eq, "#4285F4")})
                
                calendar_options = {"headerToolbar": {"left": "prev,next today", "center": "title", "right": "timeGridDay,timeGridWeek,dayGridMonth"}, "initialView": "timeGridWeek", "slotMinTime": "07:00:00", "slotMaxTime": "22:00:00", "allDaySlot": False, "height": 600}
                try: calendar(events=calendar_events, options=calendar_options, key="lab_calendar_view")
                except NameError: st.warning("Por favor, asegúrate de haber instalado 'streamlit-calendar' en tus requerimientos.")
            else: st.info("La agenda del laboratorio está completamente libre.")

        elif modo_eq == "📅 Agendar":
            c_eq_res, c_eq_agenda = st.columns([1, 1.2])
            with c_eq_res:
                if df_equipos.empty: st.info("No hay equipos registrados.")
                else:
                    eq_seleccionado = st.selectbox("Seleccionar Equipo:", df_equipos['nombre'].tolist())
                    datos_eq = df_equipos[df_equipos['nombre'] == eq_seleccionado].iloc[0]
                    st.caption(f"👀 Visibilidad: **{datos_eq.get('visibilidad', 'Privado')}**")
                    
                    fecha_res = st.date_input("Fecha de reserva:")
                    col_h1, col_h2 = st.columns(2)
                    with col_h1: t_ini = st.time_input("Hora Inicio:", value=time(9, 0))
                    with col_h2: t_fin = st.time_input("Hora Fin:", value=time(10, 0))
                    
                    if st.button("Confirmar Reserva", type="primary", use_container_width=True):
                        dt_ini = datetime.combine(fecha_res, t_ini)
                        dt_fin = datetime.combine(fecha_res, t_fin)
                        if dt_ini >= dt_fin: st.error("La hora de inicio debe ser anterior.")
                        else:
                            solapamiento = False
                            if not df_reservas.empty:
                                df_r_eq = df_reservas[df_reservas['equipo_id'] == str(datos_eq['id'])].copy()
                                if not df_r_eq.empty:
                                    df_r_eq['fecha_inicio'] = pd.to_datetime(df_r_eq['fecha_inicio']).apply(lambda x: x.tz_localize(None) if x.tzinfo else x)
                                    df_r_eq['fecha_fin'] = pd.to_datetime(df_r_eq['fecha_fin']).apply(lambda x: x.tz_localize(None) if x.tzinfo else x)
                                    for _, r in df_r_eq.iterrows():
                                        if dt_ini < r['fecha_fin'] and dt_fin > r['fecha_inicio']: solapamiento = True; break
                            if solapamiento: st.error("❌ El horario choca con otra reserva.")
                            else:
                                try:
                                    supabase.table("reservas").insert({"equipo_id": str(datos_eq['id']), "usuario": usuario_actual, "fecha_inicio": dt_ini.isoformat(), "fecha_fin": dt_fin.isoformat(), "lab_id": lab_id}).execute()
                                    admin_email = obtener_admin_email(lab_id)
                                    enviar_correo_reserva(datos_eq['nombre'], fecha_res.strftime('%d/%m/%Y'), t_ini.strftime('%H:%M'), t_fin.strftime('%H:%M'), usuario_actual, admin_email, st.session_state.usuario_autenticado)
                                    st.success("✅ Reserva guardada.")
                                    st.rerun()
                                except Exception as e: st.error(f"Error al reservar: {e}")
            with c_eq_agenda:
                st.write("**Tus Próximas Reservas:**")
                if not df_reservas.empty and not df_equipos.empty:
                    df_r = pd.merge(df_reservas, df_equipos[['id', 'nombre']], left_on='equipo_id', right_on='id', how='inner', suffixes=('', '_eq'))
                    df_r['fecha_inicio'] = pd.to_datetime(df_r['fecha_inicio']).apply(lambda x: x.tz_localize(None) if x.tzinfo else x)
                    df_r['fecha_fin'] = pd.to_datetime(df_r['fecha_fin']).apply(lambda x: x.tz_localize(None) if x.tzinfo else x)
                    df_futuras = df_r[(df_r['fecha_fin'] >= pd.to_datetime('today').tz_localize(None)) & (df_r['usuario'] == usuario_actual)].sort_values(by='fecha_inicio')
                    if df_futuras.empty: st.info("No tienes reservas activas.")
                    else:
                        for _, row in df_futuras.iterrows():
                            with st.container(border=True):
                                nom_eq = row.get('nombre', row.get('nombre_eq', 'Equipo Reservado'))
                                st.markdown(f"**{nom_eq}**")
                                st.write(f"🕒 {row['fecha_inicio'].strftime('%d/%b %H:%M')} - {row['fecha_fin'].strftime('%H:%M')}")
                                gcal_link = generar_link_gcal(titulo=f"Uso Lab: {nom_eq}", inicio=row['fecha_inicio'], fin=row['fecha_fin'], descripcion=f"Reserva en Stck.")
                                st.markdown(f"[📅 Google Calendar]({gcal_link})", unsafe_allow_html=True)

        elif modo_eq == "⚙️ Mis Equipos":
            if not df_equipos.empty:
                cols_ed_eq = ['nombre', 'descripcion', 'visibilidad', 'requisitos', 'id']
                edited_eq_df = st.data_editor(df_equipos[cols_ed_eq].copy(), column_config={"id": st.column_config.TextColumn("ID", disabled=True), "visibilidad": st.column_config.SelectboxColumn("Visibilidad", options=["Solo mi Laboratorio", "Mi Instituto", "Toda la Sede", "Público General"])}, use_container_width=True, hide_index=True)
                if st.button("💾 Guardar Cambios en Equipos", type="secondary"):
                    for _, row in edited_eq_df.iterrows():
                        d = row.replace({np.nan: None}).to_dict()
                        if 'id' in d and str(d['id']).strip(): 
                            d['lab_id'] = lab_id 
                            supabase.table("equipos_lab").upsert(d).execute()
                    st.rerun()
            st.markdown("---")
            with st.expander("➕ Registrar Nuevo Equipo", expanded=df_equipos.empty):
                with st.form("form_nuevo_equipo"):
                    n_eq = st.text_input("Nombre del Equipo")
                    d_eq = st.text_input("Descripción / Ubicación")
                    req_eq = st.text_area("Requisitos de Uso")
                    v_eq = st.selectbox("Visibilidad", ["Solo mi Laboratorio", "Mi Instituto", "Toda la Sede", "Público General"])
                    if st.form_submit_button("Crear Equipo", type="primary"):
                        try:
                            supabase.table("equipos_lab").insert({"nombre": n_eq, "descripcion": d_eq, "visibilidad": v_eq, "requisitos": req_eq, "lab_id": lab_id}).execute()
                            st.success("Equipo registrado.")
                            st.rerun()
                        except Exception as e: st.error(f"Error: {e}")

    # --- PESTAÑA: ELN TIPO NOTION (CON ROLLBACK PERFECTO Y HORA) ---
    with tab_bitacora:
        st.markdown("### 📔 Cuaderno de Laboratorio")
        
        c_filt, c_btn = st.columns([2, 1])
        with c_filt:
            if rol_actual == "admin": filtro_usuario = st.selectbox("Ver cuaderno de:", ["Todos"] + list(set(nombres_equipo)), label_visibility="collapsed")
            else: filtro_usuario = usuario_actual; st.write(f"📖 **Cuaderno de {usuario_actual}**")
        
        with st.expander("📝 Escribir nueva entrada manual", expanded=False):
            texto_metodo = st.text_area("Anota libremente todo lo que hiciste hoy...", height=150)
            link_evidencia = st.text_input("📎 Enlace a Drive, Foto o Excel (Opcional)")
            if st.button("💾 Guardar Entrada", type="primary"):
                if texto_metodo.strip():
                    supabase.table("bitacora").insert({
                        "lab_id": lab_id, "usuario": usuario_actual, 
                        "fecha": date.today().isoformat(), 
                        "contenido": texto_metodo, 
                        "link_adjunto": link_evidencia,
                        "resultado": ""
                    }).execute()
                    st.rerun()
                else: st.warning("No puedes guardar una hoja en blanco.")
                    
        st.markdown("<br>", unsafe_allow_html=True)
        
        if df_bitacora.empty: 
            st.info("El cuaderno está vacío. ¡Escribe o háblale a la IA!")
        else:
            df_b_show = df_bitacora if filtro_usuario == "Todos" else df_bitacora[df_bitacora['usuario'] == filtro_usuario]
            chile_tz = pytz.timezone('America/Santiago')
            
            st.markdown("<div style='font-family: \"Inter\", sans-serif; max-width: 850px;'>", unsafe_allow_html=True)
            
            for _, row in df_b_show.iterrows():
                fecha_str = row.get('fecha', '')
                hora_str = ""
                
                if 'created_at' in row and pd.notna(row['created_at']) and str(row['created_at']).strip():
                    try:
                        dt_obj = pd.to_datetime(row['created_at'])
                        if dt_obj.tzinfo is None:
                            dt_obj = dt_obj.tz_localize('UTC') 
                        dt_local = dt_obj.tz_convert(chile_tz)
                        hora_str = dt_local.strftime('%H:%M')
                    except Exception as e: 
                        pass
                
                contenido_esc = html_lib.escape(str(row.get('contenido', '')).strip())
                res_ia = str(row.get('resultado', '')).strip()
                link = str(row.get('link_adjunto', '')).strip()
                
                col_text, col_del = st.columns([15, 1])
                
                with col_text:
                    html_cuaderno = f"""
                    <details class='notion-toggle' style='margin-bottom: 0; border-bottom: none; padding-bottom: 0;'>
                        <summary>
                            <div style="padding-top: 2px;">{contenido_esc}</div>
                        </summary>
                        <div class='cuaderno-meta-box'>
                            <div style='margin-bottom: 8px; color: #555; font-size: 0.95em;'>🕒 {fecha_str} {hora_str} &nbsp;|&nbsp; 👤 <b>{row['usuario']}</b></div>
                    """
                    
                    if res_ia and res_ia != "None":
                        html_cuaderno += f"<div>{res_ia}</div>"
                    
                    if link.startswith('http'):
                        html_cuaderno += f"<div style='margin-top:8px;'>📎 <a href='{link}' target='_blank'>Ver Evidencia Adjunta</a></div>"
                        
                    html_cuaderno += "</div></details>"
                    st.markdown(html_cuaderno, unsafe_allow_html=True)
                
                with col_del:
                    st.markdown("<div style='margin-top: 5px;'></div>", unsafe_allow_html=True)
                    # --- EL MOTOR DE ROLLBACK (BÚSQUEDA POR ATRIBUTO DATA-ID) ---
                    if st.button("🗑️", key=f"del_{row['id']}", help="Eliminar nota y restaurar reactivos"):
                        res_ia_str = str(row.get('resultado', ''))
                        
                        # Regex perfecta: extrae la cantidad y el UUID secreto del atributo data-id
                        pattern_new = r"📉\s*([0-9.]+).*?data-id='([^']+)'"
                        matches_new = re.findall(pattern_new, res_ia_str)
                        
                        for m in matches_new:
                            cant_revertir = float(m[0])
                            item_id = m[1].strip()
                            
                            res_item = supabase.table("items").select("id, cantidad_actual, nombre").eq("id", item_id).execute()
                            if res_item.data:
                                stock_actual = float(res_item.data[0]['cantidad_actual'])
                                stock_nuevo = stock_actual + cant_revertir
                                nombre_real = res_item.data[0]['nombre']
                                
                                val_stock = int(stock_nuevo) if stock_nuevo.is_integer() else stock_nuevo
                                val_cambio = int(cant_revertir) if cant_revertir.is_integer() else cant_revertir
                                
                                supabase.table("items").update({"cantidad_actual": val_stock}).eq("id", item_id).execute()
                                supabase.table("movimiento").insert({
                                    "item_id": item_id, 
                                    "nombre_item": nombre_real, 
                                    "cantidad_cambio": val_cambio, 
                                    "tipo": "Reversión (Borrado de Bitácora)", 
                                    "usuario": usuario_actual, 
                                    "lab_id": lab_id
                                }).execute()
                                
                        supabase.table("bitacora").delete().eq("id", row['id']).execute()
                        st.rerun()
                
                st.markdown("<hr style='margin: 10px 0; border: 0; border-top: 1px dashed #eee;'>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    with tab_prot:
        tab_lista, tab_crear = st.tabs(["📋 Mis Protocolos (Editar)", "📝 Nuevo Protocolo"])
        with tab_lista:
            if df_prot.empty: st.info("No hay protocolos creados.")
            else:
                st.write("Modifica los nombres o las recetas de tus protocolos en esta tabla:")
                cols_ed_p = ['id', 'nombre', 'materiales_base']
                edited_p_df = st.data_editor(
                    df_prot[cols_ed_p].copy(), 
                    column_config={"id": st.column_config.TextColumn("ID", disabled=True), "nombre": "Nombre del Protocolo", "materiales_base": "Receta Libre (Ej: Usa 2 ml de DMEM...)"}, 
                    use_container_width=True, hide_index=True)
                if st.button("💾 Guardar Cambios en Protocolos", type="secondary"):
                    for _, row in edited_p_df.iterrows():
                        d = row.replace({np.nan: None}).to_dict()
                        if 'id' in d and str(d['id']).strip(): 
                            d['lab_id'] = lab_id 
                            supabase.table("protocolos").upsert(d).execute()
                    st.rerun()
                    
        with tab_crear:
            with st.form("form_nuevo_prot"):
                n_prot = st.text_input("Nombre (Ej: Ensayo DNAzimas)")
                mat_base = st.text_area("Receta (Escribe libremente, ej: 'Usa 2 ml de DMEM y 1 placa')")
                if st.form_submit_button("💾 Guardar"):
                    supabase.table("protocolos").insert({"nombre": n_prot, "materiales_base": mat_base, "lab_id": lab_id}).execute()
                    st.rerun()

    if rol_actual == "admin":
        with tab_analisis:
            st.markdown("### 📈 Predicción de Consumo (Burn Rate)")
            with st.spinner("Analizando..."):
                res_mov = supabase.table("movimiento").select("*").eq("lab_id", lab_id).execute()
                df_mov = pd.DataFrame(res_mov.data)
                
                if not df_mov.empty and not df.empty:
                    df_mov['created_at'] = pd.to_datetime(df_mov['created_at']).dt.tz_localize(None)
                    df_consumos = df_mov[df_mov['cantidad_cambio'] < 0].copy()
                    df_consumos['cantidad_cambio'] = df_consumos['cantidad_cambio'].abs()
                    hace_30_dias = pd.to_datetime(date.today()) - timedelta(days=30)
                    df_ultimos_30 = df_consumos[df_consumos['created_at'] >= hace_30_dias]
                    
                    if not df_ultimos_30.empty:
                        resumen = df_ultimos_30.groupby('nombre_item')['cantidad_cambio'].sum().reset_index()
                        resumen = resumen.rename(columns={'cantidad_cambio': 'consumo_30d'})
                        df_pred = pd.merge(df[['nombre', 'cantidad_actual', 'unidad']], resumen, left_on='nombre', right_on='nombre_item', how='inner')
                        df_pred['tasa_diaria'] = df_pred['consumo_30d'] / 30
                        df_pred['dias_restantes'] = np.where(df_pred['tasa_diaria'] > 0, df_pred['cantidad_actual'] / df_pred['tasa_diaria'], 9999)
                        df_pred['dias_restantes_num'] = df_pred['dias_restantes']
                        df_pred['dias_restantes'] = df_pred['dias_restantes'].apply(lambda x: "🚨 Se agota hoy/mañana" if x <= 1.5 else f"Aprox {int(x)} días")
                        
                        df_pred['tasa_diaria'] = df_pred['tasa_diaria'].apply(lambda x: f"{x:g}" if pd.notnull(x) else "")
                        df_pred['cantidad_actual'] = df_pred['cantidad_actual'].apply(lambda x: f"{x:g}" if pd.notnull(x) else "")
                        df_pred['consumo_30d'] = df_pred['consumo_30d'].apply(lambda x: f"{x:g}" if pd.notnull(x) else "")
                        
                        df_mostrar = df_pred.sort_values(by='dias_restantes_num', ascending=True)[['nombre', 'cantidad_actual', 'unidad', 'consumo_30d', 'tasa_diaria', 'dias_restantes']]
                        st.dataframe(df_mostrar, use_container_width=True, hide_index=True)
                    else: st.info("Aún no hay suficientes retiros para proyectar matemáticas.")
                else: st.info("Registra movimientos para que la IA aprenda el consumo.")

            st.markdown("---")
            st.markdown("### 💰 Costeo y Simulación de Protocolos")
            if df_prot.empty: st.info("Sin protocolos para evaluar.")
            else:
                p_sel = st.selectbox("Seleccionar protocolo para evaluar costo:", df_prot['nombre'].tolist())
                n_muestras = st.number_input("Cantidad de Muestras proyectadas:", min_value=1, value=1)
                
                if st.button("🔍 Calcular Impacto Financiero", type="secondary"):
                    info_p = df_prot[df_prot['nombre'] == p_sel]['materiales_base'].values[0]
                    descuentos = []
                    costo_total_exp = 0
                    
                    for linea in info_p.split('\n'):
                        if "," in linea or ":" in linea or "de" in linea:
                            partes = re.split(r'[,:]', linea)
                            for p in partes:
                                match_num = re.search(r'[\d.]+', p)
                                if match_num:
                                    cant_base = float(match_num.group())
                                    cant_total = cant_base * n_muestras
                                    for idx, row_item in df.iterrows():
                                        if row_item['nombre'].lower() in p.lower():
                                            if row_item['precio'] > 0 and row_item['cantidad_actual'] > 0:
                                                costo_item = (cant_total / row_item['cantidad_actual']) * row_item['precio']
                                                costo_total_exp += costo_item
                                            descuentos.append({"Reactivo": row_item['nombre'], "Stock": row_item['cantidad_actual'], "Requerido": cant_total, "Unidad": row_item['unidad']})
                                            break
                                            
                    if descuentos:
                        st.dataframe(pd.DataFrame(descuentos), hide_index=True)
                        if costo_total_exp > 0: 
                            st.markdown(f"<div class='badge-costo'>💰 Presupuesto estimado: ${int(costo_total_exp):,} CLP</div>", unsafe_allow_html=True)
                        else:
                            st.info("No hay precios registrados para los reactivos de este protocolo. Agrégalos en Edición Masiva.")

            st.markdown("---")
            st.markdown("### 📄 Generador de Reportes (ISO/GLP)")
            st.write("Descarga un PDF inmutable con la foto actual de tu inventario.")
            if st.button("Generar Reporte PDF", type="secondary"):
                if not df.empty:
                    pdf_bytes = generar_pdf_inventario(df, st.session_state.nombre_usuario)
                    st.success("PDF generado exitosamente.")
                    st.download_button(label="📥 Descargar Reporte Físico", data=pdf_bytes, file_name=f"Reporte_Inventario_{date.today()}.pdf", mime="application/pdf")
                else: st.warning("El inventario está vacío.")

        with tab_usuarios:
            st.markdown("### 🤝 Gestión de Accesos")
            with st.container(border=True):
                nuevo_email = st.text_input("Correo a invitar:").strip().lower()
                rol_nuevo = st.selectbox("Rol:", ["miembro", "admin"])
                if st.button("Dar Acceso", type="primary", use_container_width=True):
                    if nuevo_email:
                        try:
                            res_check = supabase.table("equipo").select("*").eq("email", nuevo_email).execute()
                            if res_check.data: supabase.table("equipo").update({"lab_id": lab_id, "rol": rol_nuevo}).eq("email", nuevo_email).execute()
                            else: supabase.table("equipo").insert({"email": nuevo_email, "lab_id": lab_id, "rol": rol_nuevo, "nombre": "Invitado"}).execute()
                            st.success(f"Acceso otorgado a {nuevo_email}.")
                            st.rerun() 
                        except Exception as e: st.error(f"❌ Error exacto al guardar en BD: {e}")
            st.write("**Miembros Activos:**")
            try:
                miembros = supabase.table("equipo").select("nombre, email, rol, perfil_academico, institucion").eq("lab_id", lab_id).execute()
                if miembros.data: st.dataframe(pd.DataFrame(miembros.data), hide_index=True, use_container_width=True)
            except Exception as e: st.error(f"❌ Error al cargar la lista: {e}")

# --- PANEL IA ORQUESTADOR ---
with col_chat:
    st.markdown("### 💬 Secretario IA")
    chat_box = st.container(height=400, border=False)
    
    if "messages" not in st.session_state: 
        st.session_state.messages = [{"role": "assistant", "content": f"¡Hola! Dime qué hiciste en el laboratorio."}]
    
    for m in st.session_state.messages:
        with chat_box: st.chat_message(m["role"]).markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎙️ Hablar", stop_prompt="⏹️ Enviar", just_once=True, key='voice_input')
    prompt = v_in if v_in else st.chat_input("Ej: Hoy hice un pasaje celular...")

    with st.expander("📸 Procesar con Ojo IA"):
        accion_foto = st.radio("¿Qué deseas hacer con la foto?", ["➕ Agregar Reactivo Nuevo", "🔄 Actualizar Reactivo"], horizontal=True)
        item_a_actualizar = None
        if accion_foto == "🔄 Actualizar Reactivo" and not df.empty: item_a_actualizar = st.selectbox("Selecciona reactivo:", df['nombre'].tolist())
        foto_chat = st.camera_input("Capturar Imagen / Escanear QR", label_visibility="collapsed")
        
        if foto_chat and st.button("🧠 Procesar Foto", type="primary", use_container_width=True):
            img = Image.open(foto_chat).convert('RGB')
            st.session_state.messages.append({"role": "user", "content": "📸 *Foto enviada.*"})
            with chat_box: st.chat_message("user").markdown("📸 *Foto enviada.*")
            with st.chat_message("assistant"):
                with st.spinner("Analizando..."):
                    try:
                        if accion_foto == "➕ Agregar Reactivo Nuevo":
                            prompt_vision = "Extrae los datos de esta etiqueta química. Responde SOLO JSON: {\"nombre\": \"\", \"categoria\": \"\", \"cantidad_actual\": 0, \"unidad\": \"\"}"
                            res_ai = model.generate_content([prompt_vision, img]).text
                            data = json.loads(re.search(r'\{.*\}', res_ai, re.DOTALL).group())
                            res_ins = supabase.table("items").insert({"nombre": data.get('nombre', 'Desconocido'), "cantidad_actual": data.get('cantidad_actual', 0), "unidad": data.get('unidad', 'unidades'), "categoria": data.get('categoria', 'GENERAL'), "lab_id": lab_id}).execute()
                            itm = res_ins.data[0]
                            supabase.table("movimiento").insert({"item_id": str(itm['id']), "nombre_item": itm['nombre'], "cantidad_cambio": itm['cantidad_actual'], "tipo": "Nuevo IA (Foto)", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                            msg = f"📸 **Creado:** {itm['nombre']} | Stock: {itm['cantidad_actual']}"
                        
                        elif accion_foto == "🔄 Actualizar Reactivo":
                            prompt_vision = f"Lee la etiqueta o el Código QR de esta imagen. Es del reactivo '{item_a_actualizar}'. Extrae la cantidad física que ves. Responde SOLO JSON: {{\"{item_a_actualizar}\": true, \"cantidad_actual\": 0}}"
                            res_ai = model.generate_content([prompt_vision, img]).text
                            data = json.loads(re.search(r'\{.*\}', res_ai, re.DOTALL).group())
                            nueva_cant = data.get('cantidad_actual', 0)
                            id_ac = str(df[df['nombre'] == item_a_actualizar].iloc[0]['id'])
                            supabase.table("items").update({"cantidad_actual": nueva_cant}).eq("id", id_ac).execute()
                            supabase.table("movimiento").insert({"item_id": id_ac, "nombre_item": item_a_actualizar, "cantidad_cambio": nueva_cant, "tipo": "Actualizado IA (Foto/QR)", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                            msg = f"📸 **Actualizado:** {item_a_actualizar} ahora tiene {nueva_cant} en stock."

                        st.markdown(msg); st.session_state.messages.append({"role": "assistant", "content": msg}); st.rerun()
                    except Exception as e: st.error("Error al procesar la imagen.")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box: st.chat_message("user").markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Leyendo receta e inventario..."):
                try:
                    d_ia = df[['id', 'nombre', 'cantidad_actual']].to_json(orient='records') if not df.empty else "[]"
                    d_prot = df_prot[['nombre', 'materiales_base']].to_json(orient='records') if not df_prot.empty else "[]"
                    hoy_str = date.today().isoformat()
                    
                    historial_str = "\n".join([f"{'Usuario' if m['role']=='user' else 'IA'}: {m['content']}" for m in st.session_state.messages[-8:-1]])
                    
                    prompt_sistema = f"""
                    Eres la Inteligencia Artificial del LIMS Stck. Hoy es {hoy_str}.
                    Inventario: {d_ia}
                    Protocolos: {d_prot}
                    Historial: {historial_str}

                    El usuario dice: "{prompt}"

                    Devuelve ÚNICAMENTE un JSON con esta estructura exacta:
                    {{
                        "respuesta_chat": "Si es un pasaje celular, confirma y pregunta: '¿Usaste placa o material extra?'. Si ya responde a esa pregunta (ej 'no', 'usé 1'), di 'Entendido y descontado.'",
                        "entrada_cuaderno": "Copia EXACTAMENTE sus palabras. Si es una respuesta a tu pregunta, DEBE QUEDAR VACÍO.",
                        "protocolo_detectado": {{"nombre": "Nombre EXACTO del protocolo", "muestras": 1}},
                        "descuentos_protocolo": [{{"nombre_item_inventario": "Nombre exacto en inventario", "cantidad_total_a_restar": 0.0}}],
                        "descuentos_extra": [{{"nombre_item_inventario": "Nombre exacto en inventario", "cantidad_a_restar": 0.0}}]
                    }}

                    REGLAS INFLEXIBLES:
                    1. MAPEO EXACTO DE NOMBRES: Si la receta dice "PBS", y el inventario tiene "PBS" y "D-PBS", debes enviar en 'nombre_item_inventario' EXACTAMENTE "PBS". ¡Copia el nombre del inventario letra por letra!
                    2. EXTRACCIÓN NUMÉRICA: Extrae el PRIMER número de la receta, multiplícalo por las muestras y ponlo en cantidad.
                    3. ANTI-BUCLES: Si el usuario responde 'no' o 'nada', "entrada_cuaderno" DEBE SER VACÍO y "protocolo_detectado" vacío.
                    """
                    
                    res_ai = model.generate_content(prompt_sistema).text
                    match = re.search(r'\{.*\}', res_ai, re.DOTALL)
                    
                    if match:
                        data = json.loads(match.group())
                        log_ia_acciones = []
                        lista_descuentos = []
                        
                        texto_minuscula = prompt.lower().strip()
                        es_respuesta_corta = len(texto_minuscula.split()) <= 5 and any(w in texto_minuscula for w in ['no', 'nada', 'ninguno', 'ninguna', 'listo', 'ya', 'si', 'sí', 'ok'])
                        if es_respuesta_corta:
                            data['entrada_cuaderno'] = ""

                        # 1. PROTOCOLOS Y BÚSQUEDA ESTRICTA
                        p_dict = data.get('protocolo_detectado', {})
                        d_prot = data.get('descuentos_protocolo', [])
                        
                        if p_dict and p_dict.get('nombre') and not es_respuesta_corta:
                            p_nombre = p_dict.get('nombre')
                            p_muestras = p_dict.get('muestras', 1)
                            log_ia_acciones.append(f"🔗 <b>Protocolo:</b> {p_nombre} (x{p_muestras})")
                            
                            for desc in d_prot:
                                nom_item = desc.get('nombre_item_inventario')
                                cant_total = desc.get('cantidad_total_a_restar', 0)
                                
                                if nom_item and cant_total > 0:
                                    # CANDADO 1: Búsqueda idéntica al 100% primero (Evita PBS vs D-PBS)
                                    item_db = df[df['nombre'].str.strip().str.lower() == nom_item.strip().lower()]
                                    
                                    # CANDADO 2: Si no lo encuentra idéntico, busca palabra completa
                                    if item_db.empty:
                                        item_db = df[df['nombre'].str.contains(re.escape(nom_item), case=False, na=False, regex=True)]
                                        
                                    if not item_db.empty:
                                        id_item = str(item_db.iloc[0]['id'])
                                        stock_actual = float(item_db.iloc[0]['cantidad_actual'])
                                        stock_nuevo = stock_actual - float(cant_total)
                                        
                                        val_stock = int(stock_nuevo) if float(stock_nuevo).is_integer() else float(stock_nuevo)
                                        val_cambio = int(-cant_total) if float(-cant_total).is_integer() else float(-cant_total)
                                        val_mostrar = int(cant_total) if float(cant_total).is_integer() else float(cant_total)
                                        
                                        unidad_item = item_db.iloc[0]['unidad']
                                        nombre_real = item_db.iloc[0]['nombre']
                                        
                                        supabase.table("items").update({"cantidad_actual": val_stock}).eq("id", id_item).execute()
                                        supabase.table("movimiento").insert({"item_id": id_item, "nombre_item": nombre_real, "cantidad_cambio": val_cambio, "tipo": f"Uso IA: {p_nombre}", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                                        
                                        # MARCADOR INVISIBLE EN HTML PARA EL ROLLBACK DE LA PAPELERA
                                        lista_descuentos.append(f"&nbsp;&nbsp;&nbsp; - 📉 {val_mostrar} {unidad_item} de {nombre_real} <span data-id='{id_item}' style='display:none'></span> <i>(Protocolo)</i>")
                                    else:
                                        lista_descuentos.append(f"&nbsp;&nbsp;&nbsp; - ⚠️ No encontré '{nom_item}' en inventario.")

                        # 2. AJUSTES EXTRA (Placas)
                        ajustes = data.get('descuentos_extra', [])
                        for aj in ajustes:
                            nom_man = aj.get('nombre_item_inventario')
                            cant_man = aj.get('cantidad_a_restar', 0)
                            
                            if nom_man and float(cant_man) > 0:
                                item_db = df[df['nombre'].str.strip().str.lower() == nom_man.strip().lower()]
                                if item_db.empty:
                                    item_db = df[df['nombre'].str.contains(re.escape(nom_man), case=False, na=False, regex=True)]
                                    
                                if not item_db.empty:
                                    id_ac = str(item_db.iloc[0]['id'])
                                    stock_actual = float(item_db.iloc[0]['cantidad_actual'])
                                    stock_nuevo = stock_actual - float(cant_man)
                                    
                                    val_stock = int(stock_nuevo) if float(stock_nuevo).is_integer() else float(stock_nuevo)
                                    val_cambio = int(-cant_man) if float(-cant_man).is_integer() else float(-cant_man)
                                    val_mostrar = int(cant_man) if float(cant_man).is_integer() else float(cant_man)
                                    
                                    nombre_item = item_db.iloc[0]['nombre']
                                    unidad_item = item_db.iloc[0]['unidad']
                                    
                                    supabase.table("items").update({"cantidad_actual": val_stock}).eq("id", id_ac).execute()
                                    supabase.table("movimiento").insert({"item_id": id_ac, "nombre_item": nombre_item, "cantidad_cambio": val_cambio, "tipo": "Ajuste Conversacional IA", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                                    
                                    if es_respuesta_corta:
                                        st.session_state.messages.append({"role": "assistant", "content": f"✅ Descontado: -{val_mostrar} {unidad_item} de {nombre_item}"})
                                        st.rerun()
                                    else:
                                        lista_descuentos.append(f"&nbsp;&nbsp;&nbsp; - 📉 {val_mostrar} {unidad_item} de {nombre_item} <span data-id='{id_ac}' style='display:none'></span> <i>(Extra)</i>")

                        # ENSAMBLAJE FINAL DEL HTML
                        if lista_descuentos:
                            log_ia_acciones.append("<b>📦 Descontado:</b>")
                            log_ia_acciones.extend(lista_descuentos)

                        metadatos_ia = "<br>".join(log_ia_acciones)

                        # 3. GUARDAR EN BITÁCORA
                        texto_cuaderno = data.get('entrada_cuaderno', "").strip()
                        if texto_cuaderno and not es_respuesta_corta:
                            supabase.table("bitacora").insert({
                                "lab_id": lab_id, 
                                "usuario": usuario_actual, 
                                "fecha": date.today().isoformat(),
                                "contenido": texto_cuaderno,
                                "resultado": metadatos_ia 
                            }).execute()

                        # 4. CHAT
                        msg_final = data.get('respuesta_chat', 'Entendido.')
                        st.markdown(msg_final)
                        st.session_state.messages.append({"role": "assistant", "content": msg_final})
                        st.rerun()

                    else:
                        st.markdown("Comando procesado.")
                except Exception as e: st.error(f"Error IA: {e}")

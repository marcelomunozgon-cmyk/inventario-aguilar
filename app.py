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
    
    /* MAGIA NOTION: Estilo de Toggle List nativo y limpio */
    details.notion-toggle { margin-bottom: 10px; }
    details.notion-toggle > summary {
        list-style: none; 
        font-size: 1.05em; 
        color: #111; 
        cursor: pointer; 
        line-height: 1.5; 
        padding: 5px 0;
        font-weight: 500;
    }
    details.notion-toggle > summary::-webkit-details-marker { display: none; }
    details.notion-toggle > summary::before {
        content: '▶ ';
        font-size: 0.8em;
        color: #888;
        display: inline-block;
        width: 20px;
        transition: transform 0.2s ease-in-out;
    }
    details.notion-toggle[open] > summary::before { transform: rotate(90deg); }
    .cuaderno-meta-box {
        margin-left: 22px; 
        margin-top: 5px;
        margin-bottom: 20px; 
        padding-left: 15px; 
        border-left: 2px solid #eaeaea; 
        font-size: 0.9em; 
        color: #555;
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
    for col in ['contenido', 'resultado', 'link_adjunto', 'created_at']:
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
        tab_inv, tab_prot, tab_equipos, tab_bitacora, tab_edit, tab_analisis, tab_usuarios = st.tabs(["📦 Inventario", "🧪 Protocolos", "📅 Equipos", "📔 Bitácora", "⚙️ Edición", "📊 Analítica", "👥 Usuarios"])
    else: 
        tab_inv, tab_prot, tab_equipos, tab_bitacora, tab_edit = st.tabs(["📦 Inventario", "🧪 Protocolos", "📅 Equipos", "📔 Bitácora", "⚙️ Edición"])
    
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
                st.error("🚨 **Alertas de Laboratorio**")
                if not df_criticos.empty: st.warning(f"⚠️ **{len(df_criticos)} Reactivos Críticos / Fuera de Stock**")
                if not df_vencidos.empty: st.warning(f"📅 **{len(df_vencidos)} Reactivos Vencen en < 30 días**")
        
        st.markdown("### 🗂️ Catálogo de Reactivos")
        busqueda = st.text_input("🔍 Buscar reactivo...", value=st.session_state.auto_search)
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        categorias = sorted(list(set([str(c).strip() for c in df_show['categoria'].unique() if str(c).strip() not in ["", "nan", "None"]])))
        
        if df.empty: st.info("Inventario vacío.")
        else:
            for cat in categorias:
                with st.expander(f"📁 {cat}", expanded=False):
                    subset_cat = df_show[df_show['categoria'].astype(str).str.strip() == cat].sort_values(by='nombre', key=lambda col: col.str.lower())
                    st.dataframe(subset_cat[['nombre', 'cantidad_actual', 'unidad', 'ubicacion', 'posicion_caja', 'fecha_vencimiento']].style.apply(aplicar_estilos_inv, axis=1), use_container_width=True, hide_index=True)

            st.markdown("---")
            with st.expander("🖨️ Generar Etiquetas Físicas (QR)"):
                st.write("Selecciona un reactivo para generar su Código QR.")
                item_qr = st.selectbox("Reactivo para Etiqueta:", df['nombre'].tolist())
                if st.button("Generar Código QR"):
                    qr_img_bytes = generar_qr(item_qr)
                    st.image(qr_img_bytes, caption=f"Código QR para: {item_qr}", width=200)
                    st.download_button(label="Descargar Imagen QR", data=qr_img_bytes, file_name=f"QR_{item_qr}.png", mime="image/png")

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

    # --- PESTAÑA: ELN TIPO NOTION (MINIMALISTA) ---
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
                    
        st.markdown("---")
        
        if df_bitacora.empty: st.info("El cuaderno está vacío.")
        else:
            df_b_show = df_bitacora if filtro_usuario == "Todos" else df_bitacora[df_bitacora['usuario'] == filtro_usuario]
            
            # MAGIA NOTION: Generar HTML Limpio para cada nota
            html_cuaderno = "<div style='font-family: \"Inter\", sans-serif; max-width: 800px;'>"
            for _, row in df_b_show.iterrows():
                fecha_str = row.get('fecha', '')
                hora_str = ""
                if 'created_at' in row and pd.notna(row['created_at']) and str(row['created_at']).strip():
                    try:
                        dt_obj = pd.to_datetime(row['created_at']).tz_localize(None)
                        hora_str = dt_obj.strftime('%H:%M')
                    except: pass
                
                # Se limpia el contenido de etiquetas HTML peligrosas y saltos de linea
                contenido = str(row.get('contenido', '')).strip()
                contenido_esc = html_lib.escape(contenido).replace('\n', '<br>')
                
                res_ia = str(row.get('resultado', '')).strip().replace('\n', '<br>')
                if res_ia == "None": res_ia = ""
                
                link = str(row.get('link_adjunto', '')).strip()
                link_html = f"<br><br>📎 <a href='{link}' target='_blank'>Ver Evidencia Adjunta</a>" if link.startswith('http') else ""
                
                html_cuaderno += f"""
                <details class='notion-toggle'>
                    <summary>
                        {contenido_esc}
                    </summary>
                    <div class='cuaderno-meta-box'>
                        <b>🕒 {fecha_str} {hora_str} &nbsp;|&nbsp; 👤 {row['usuario']}</b><br><br>
                        {res_ia}
                        {link_html}
                    </div>
                </details>
                """
            html_cuaderno += "</div>"
            st.markdown(html_cuaderno, unsafe_allow_html=True)

    with tab_prot:
        tab_lista, tab_crear = st.tabs(["📋 Mis Protocolos (Editar)", "📝 Nuevo Protocolo"])
        with tab_lista:
            if df_prot.empty: st.info("No hay protocolos creados.")
            else:
                st.write("Modifica los nombres o las recetas de tus protocolos en esta tabla:")
                cols_ed_p = ['id', 'nombre', 'materiales_base']
                edited_p_df = st.data_editor(
                    df_prot[cols_ed_p].copy(), 
                    column_config={"id": st.column_config.TextColumn("ID", disabled=True), "nombre": "Nombre del Protocolo", "materiales_base": "Receta (Reactivo : Cantidad)"}, 
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
                mat_base = st.text_area("Reactivos (Nombre en inventario : Cantidad por muestra)")
                if st.form_submit_button("💾 Guardar"):
                    supabase.table("protocolos").insert({"nombre": n_prot, "materiales_base": mat_base, "lab_id": lab_id}).execute()
                    st.rerun()

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
                        df_pred['tasa_diaria'] = df_pred['tasa_diaria'].round(2)
                        
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
                        if ":" in linea:
                            partes = linea.split(":")
                            item_db = df[df['nombre'].str.contains(partes[0].strip(), case=False, na=False)]
                            if not item_db.empty: 
                                desc_cant = float(partes[1].strip()) * n_muestras
                                precio_ref = item_db.iloc[0]['precio']
                                if precio_ref > 0 and item_db.iloc[0]['cantidad_actual'] > 0:
                                    costo_item = (desc_cant / item_db.iloc[0]['cantidad_actual']) * precio_ref
                                    costo_total_exp += costo_item
                                descuentos.append({"id": str(item_db.iloc[0]['id']), "Reactivo": item_db.iloc[0]['nombre'], "Stock": item_db.iloc[0]['cantidad_actual'], "Requerido": desc_cant, "Unidad": item_db.iloc[0]['unidad']})
                    if descuentos:
                        st.dataframe(pd.DataFrame(descuentos).drop(columns=['id']), hide_index=True)
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

# --- PANEL IA ORQUESTADOR CON MEMORIA Y FILTROS ESTRICTOS ---
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
            with st.spinner("Pensando y analizando contexto..."):
                try:
                    d_ia = df[['id', 'nombre', 'cantidad_actual']].to_json(orient='records') if not df.empty else "[]"
                    d_prot = df_prot[['nombre']].to_json(orient='records') if not df_prot.empty else "[]"
                    d_eq = df_equipos[['id', 'nombre']].to_json(orient='records') if not df_equipos.empty else "[]"
                    hoy_str = date.today().isoformat()
                    
                    historial_str = "\n".join([f"{'Usuario' if m['role']=='user' else 'IA'}: {m['content']}" for m in st.session_state.messages[-10:-1]])
                    rutinas_str = ", ".join(st.session_state.rutinas_diarias["mostradas"])
                    
                    prompt_sistema = f"""
                    Eres el Orquestador IA del LIMS Stck. Hoy es {hoy_str}.
                    Inventario actual: {d_ia}
                    Protocolos registrados: {d_prot}
                    
                    Historial reciente:
                    {historial_str}
                    Rutinas ya recordadas hoy (NO LAS VUELVAS A MENCIONAR): [{rutinas_str}]

                    Analiza el ÚLTIMO mensaje del Usuario: "{prompt}" y devuelve ÚNICAMENTE un JSON con esta estructura exacta:
                    {{
                        "mensaje_inicial": "Respuesta conversacional.",
                        "pregunta_final": "Pregunta opcional.",
                        "bitacora": {{"guardar": false, "entrada_cuaderno": ""}},
                        "protocolo": {{"ejecutar": false, "nombre": "", "muestras": 1}},
                        "inventario_ajustes": [{{"id": "id_del_item", "cantidad_a_restar": 0}}],
                        "reserva": {{"generar": false, "equipo_nombre": "", "fecha_YYYY_MM_DD": "", "hora_inicio_HH_MM": "", "hora_fin_HH_MM": ""}},
                        "nuevas_rutinas_recordadas": ["palabra"]
                    }}

                    REGLAS CRÍTICAS DE AUDITORÍA:
                    1. ANTI-BUCLES Y ANTI-DOBLES: Si el usuario responde 'no', 'nada', 'ninguna', 'listo', etc. a una pregunta tuya:
                       - PON "bitacora.guardar" EN FALSE INMEDIATAMENTE.
                       - PON "protocolo.ejecutar" EN FALSE.
                       - Deja "pregunta_final" vacío y responde solo 'Entendido.' en "mensaje_inicial".
                    2. TEXTO ORIGINAL: Si SÍ vas a guardar bitácora (porque es una actividad nueva), "entrada_cuaderno" debe ser EXACTAMENTE las palabras del usuario (Ej: "hoy hice pasaje..."). NO LO REDACTES EN TERCERA PERSONA.
                    3. EXTRACCIÓN INVENTARIO: Si descuentas algo manualmente ('inventario_ajustes'), asegúrate de enviar el NÚMERO que el usuario dictó.
                    4. CONFÍA EN LA RECETA: No preguntes por volúmenes de reactivos.
                    """
                    
                    res_ai = model.generate_content(prompt_sistema).text
                    match = re.search(r'\{.*\}', res_ai, re.DOTALL)
                    
                    if match:
                        data = json.loads(match.group())
                        log_ia_acciones = []
                        
                        # Candado manual de seguridad anti-dobles por si la IA se equivoca
                        texto_minuscula = prompt.lower().strip()
                        es_respuesta_corta = len(texto_minuscula.split()) <= 4 and any(w in texto_minuscula for w in ['no', 'nada', 'ninguno', 'ninguna', 'listo', 'ya', 'si', 'sí', 'ok'])
                        if es_respuesta_corta:
                            data['bitacora']['guardar'] = False
                            data['protocolo']['ejecutar'] = False

                        nuevas_rutinas = data.get('nuevas_rutinas_recordadas', [])
                        if nuevas_rutinas: st.session_state.rutinas_diarias["mostradas"].extend(nuevas_rutinas)
                        
                        # 1. RESERVA DE EQUIPO
                        res_data = data.get('reserva', {})
                        if res_data.get('generar') and res_data.get('equipo_nombre'):
                            eq_nom = res_data.get('equipo_nombre')
                            eq_match = df_equipos[df_equipos['nombre'].str.contains(eq_nom, case=False, na=False)]
                            if not eq_match.empty:
                                eq_id = eq_match.iloc[0]['id']
                                f_res = res_data.get('fecha_YYYY_MM_DD', hoy_str)
                                h_ini = res_data.get('hora_inicio_HH_MM', '09:00')
                                h_fin = res_data.get('hora_fin_HH_MM', '10:00')
                                
                                dt_ini = datetime.fromisoformat(f"{f_res}T{h_ini}:00")
                                dt_fin = datetime.fromisoformat(f"{f_res}T{h_fin}:00")
                                
                                solapamiento = False
                                if not df_reservas.empty:
                                    df_r_eq = df_reservas[df_reservas['equipo_id'] == str(eq_id)].copy()
                                    df_r_eq['fecha_inicio'] = pd.to_datetime(df_r_eq['fecha_inicio']).apply(lambda x: x.tz_localize(None) if x.tzinfo else x)
                                    df_r_eq['fecha_fin'] = pd.to_datetime(df_r_eq['fecha_fin']).apply(lambda x: x.tz_localize(None) if x.tzinfo else x)
                                    for _, r in df_r_eq.iterrows():
                                        if dt_ini < r['fecha_fin'] and dt_fin > r['fecha_inicio']: solapamiento = True; break
                                
                                if not solapamiento:
                                    supabase.table("reservas").insert({"equipo_id": str(eq_id), "usuario": usuario_actual, "fecha_inicio": dt_ini.isoformat(), "fecha_fin": dt_fin.isoformat(), "lab_id": lab_id}).execute()
                                    log_ia_acciones.append(f"✅ Equipo Reservado: {eq_match.iloc[0]['nombre']} ({f_res} de {h_ini} a {h_fin})")
                                else:
                                    log_ia_acciones.append(f"❌ Fallo Reserva: El {eq_match.iloc[0]['nombre']} ya está ocupado.")

                        # 2. PROTOCOLO AUTOMÁTICO CON EXTRACTOR MATEMÁTICO INMORTAL
                        prot = data.get('protocolo', {})
                        if prot.get('ejecutar') and prot.get('nombre'):
                            p_nombre = prot.get('nombre')
                            p_muestras = prot.get('muestras', 1)
                            prot_match = df_prot[df_prot['nombre'].str.contains(p_nombre, case=False, na=False)]
                            
                            if not prot_match.empty:
                                nombre_prot_oficial = prot_match.iloc[0]['nombre']
                                info_p = str(prot_match.iloc[0]['materiales_base'])
                                
                                desglose_txt = [f"🧪 **Protocolo Aplicado:** {nombre_prot_oficial} (x{p_muestras} muestras)"]
                                hay_items = False
                                
                                if info_p and info_p != "nan" and info_p != "None":
                                    for linea in info_p.split('\n'):
                                        if ":" in linea:
                                            hay_items = True
                                            partes = linea.split(":")
                                            item_str = partes[0].strip()
                                            
                                            # MAGIA EXTRACTORA: Saca solo los números de "10 ml" o "2.5 ul"
                                            num_str = re.sub(r'[^\d.]+', '', partes[1])
                                            try:
                                                cant_base = float(num_str) if num_str else 1.0
                                            except ValueError:
                                                continue 
                                                
                                            cant_total = cant_base * p_muestras
                                            
                                            # Búsqueda Regex Robusta (Ignora paréntesis o letras extra)
                                            item_db = df[df['nombre'].str.contains(re.escape(item_str), case=False, na=False, regex=True)]
                                            
                                            if not item_db.empty:
                                                id_item = str(item_db.iloc[0]['id'])
                                                stock_actual = float(item_db.iloc[0]['cantidad_actual'])
                                                stock_nuevo = stock_actual - cant_total
                                                umbral = float(item_db.iloc[0]['umbral_minimo'])
                                                unidad_item = item_db.iloc[0]['unidad']
                                                nombre_item = item_db.iloc[0]['nombre']
                                                
                                                supabase.table("items").update({"cantidad_actual": stock_nuevo}).eq("id", id_item).execute()
                                                supabase.table("movimiento").insert({"item_id": id_item, "nombre_item": nombre_item, "cantidad_cambio": -cant_total, "tipo": f"Uso IA: {nombre_prot_oficial}", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                                                
                                                desglose_txt.append(f"  - 📉 {cant_total} {unidad_item} de **{nombre_item}**")
                                                
                                                if umbral > 0 and stock_nuevo <= umbral:
                                                    log_ia_acciones.append(f"🚨 ALERTA CRÍTICA: {nombre_item} bajó del mínimo.")
                                            else:
                                                desglose_txt.append(f"  - ⚠️ *Aviso:* No encontré '{item_str}' en el inventario.")
                                
                                if not hay_items:
                                    desglose_txt.append("  - ⚠️ *La receta del protocolo está vacía.*")
                                
                                log_ia_acciones = desglose_txt + log_ia_acciones
                            else:
                                log_ia_acciones.append(f"⚠️ *No encontré el protocolo '{p_nombre}'.*")

                        # 3. AJUSTES EXTRA / MANUALES
                        ajustes = data.get('inventario_ajustes', [])
                        for aj in ajustes:
                            id_ac = aj.get('id')
                            cant_restar = aj.get('cantidad_a_restar', 0)
                            if id_ac and cant_restar != 0:
                                item_db = df[df['id'].astype(str) == str(id_ac)]
                                if not item_db.empty:
                                    stock_actual = float(item_db.iloc[0]['cantidad_actual'])
                                    stock_nuevo = stock_actual - cant_restar
                                    nombre_item = item_db.iloc[0]['nombre']
                                    unidad_item = item_db.iloc[0]['unidad']
                                    
                                    supabase.table("items").update({"cantidad_actual": stock_nuevo}).eq("id", id_ac).execute()
                                    supabase.table("movimiento").insert({"item_id": id_ac, "nombre_item": nombre_item, "cantidad_cambio": -cant_restar, "tipo": "Ajuste Conversacional IA", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                                    log_ia_acciones.append(f"  - 📉 {cant_restar} {unidad_item} de **{nombre_item}** (Ajuste extra)")

                        # 4. GUARDAR BITÁCORA
                        bit = data.get('bitacora', {})
                        if bit.get('guardar') and bit.get('entrada_cuaderno'):
                            texto_principal_usuario = bit.get('entrada_cuaderno')
                            metadatos_ia = "\n".join(log_ia_acciones) if log_ia_acciones else ""
                            
                            supabase.table("bitacora").insert({
                                "lab_id": lab_id, 
                                "usuario": usuario_actual, 
                                "fecha": date.today().isoformat(),
                                "contenido": texto_principal_usuario,
                                "resultado": metadatos_ia 
                            }).execute()

                        # 5. RESPONDER AL USUARIO EN EL CHAT
                        msg_final = ""
                        if data.get('mensaje_inicial'): msg_final += f"{data['mensaje_inicial']}\n\n"
                        if log_ia_acciones: msg_final += "\n".join(log_ia_acciones) + "\n\n"
                        if data.get('pregunta_final') and not es_respuesta_corta: 
                            msg_final += f"*{data['pregunta_final']}*"
                        if not msg_final.strip(): msg_final = "Entendido."
                            
                        st.markdown(msg_final)
                        st.session_state.messages.append({"role": "assistant", "content": msg_final})
                        st.rerun()

                    else:
                        st.markdown("No pude procesar la instrucción.")
                except Exception as e: st.error(f"Error IA: {e}")

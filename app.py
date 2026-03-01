import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime, date, timedelta, time
import numpy as np
from PIL import Image
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.parse

# --- 1. CONFIGURACIÓN Y ESTÉTICA ---
st.set_page_config(page_title="Stck", layout="wide", page_icon="🔬")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    div[data-testid="stContainer"] { border-radius: 10px; border-color: #f0f0f0; }
    .stTabs [data-baseweb="tab-list"] { gap: 15px; border-bottom: 1px solid #f0f0f0; }
    .stTabs [data-baseweb="tab"] { height: 50px; background-color: transparent; border-radius: 4px 4px 0px 0px; color: #888; font-weight: 500; }
    .stTabs [aria-selected="true"] { color: #ffffff !important; background-color: #1a1a1a !important; border-bottom: 2px solid #1a1a1a !important; }
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
                with st.form("form_login"):
                    email_login = st.text_input("Correo corporativo")
                    pass_login = st.text_input("Contraseña", type="password")
                    submitted = st.form_submit_button("Acceder a Stck", type="primary", use_container_width=True)
                    if submitted:
                        with st.spinner("Autenticando..."):
                            try:
                                res = supabase.auth.sign_in_with_password({"email": email_login.strip(), "password": pass_login})
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
                            except: 
                                st.error("Credenciales incorrectas.")
                            
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
rol_actual = st.session_state.get('rol', 'miembro')
correo_destinatario_compras = st.secrets.get("EMAIL_RECEIVER", "No configurado")

if 'auto_search' not in st.session_state: st.session_state.auto_search = ""
if "backup_inventario" not in st.session_state: st.session_state.backup_inventario = None
def crear_punto_restauracion(df_actual): st.session_state.backup_inventario = df_actual.copy()

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

        # Correo para el Usuario
        msg_user = MIMEMultipart()
        msg_user['From'] = sender
        msg_user['To'] = usuario_email
        msg_user['Subject'] = f"✅ Reserva Confirmada: {equipo_nombre} - Stck"
        msg_user.attach(MIMEText(f"<html><body><h3>Reserva Exitosa</h3><p>Hola, has reservado exitosamente el equipo <b>{equipo_nombre}</b> para el <b>{fecha_str}</b> en el horario de <b>{hora_ini}</b> a <b>{hora_fin}</b>.</p></body></html>", 'html'))

        # Correo para el Admin
        msg_admin = MIMEMultipart()
        msg_admin['From'] = sender
        msg_admin['To'] = admin_email
        msg_admin['Subject'] = f"📅 Nueva Reserva de Equipo: {equipo_nombre} - Stck"
        msg_admin.attach(MIMEText(f"<html><body><h3>Notificación de Laboratorio</h3><p>El usuario <b>{usuario_reserva}</b> ({usuario_email}) ha agendado el uso de <b>{equipo_nombre}</b> para el <b>{fecha_str}</b> desde las <b>{hora_ini}</b> hasta las <b>{hora_fin}</b>.</p></body></html>", 'html'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg_user)
        # Solo enviar al admin si es distinto al usuario que hace la reserva
        if admin_email and admin_email != usuario_email:
            server.send_message(msg_admin)
        server.quit()
        return True
    except Exception as e: 
        print(e)
        return False

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
except Exception as e:
    df_equipos = pd.DataFrame(columns=["id", "nombre", "descripcion", "visibilidad", "requisitos"])
    df_reservas = pd.DataFrame(columns=["id", "equipo_id", "usuario", "fecha_inicio", "fecha_fin"])

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
        tab_inv, tab_prot, tab_equipos, tab_edit, tab_analisis, tab_equipo = st.tabs(["📦 Inv", "🧪 Prot", "📅 Equipos", "⚙️ Edit", "📊 Data", "👥 Acceso"])
    else: 
        tab_inv, tab_prot, tab_equipos, tab_edit = st.tabs(["📦 Inventario", "🧪 Protocolos", "📅 Equipos", "⚙️ Edición"])
    
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
                if not df_criticos.empty: 
                    st.warning(f"⚠️ **{len(df_criticos)} Reactivos Críticos / Fuera de Stock**")
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

    with tab_equipos:
        st.markdown("### 🗓️ Gestión y Booking de Equipos")
        
        if rol_actual == "admin":
            sub_tab_reserva, sub_tab_mis_equipos = st.tabs(["📅 Agendar Uso", "⚙️ Mis Equipos (Admin)"])
        else:
            sub_tab_reserva, sub_tab_mis_equipos = st.tabs(["📅 Agendar Uso"]), None

        with sub_tab_reserva:
            c_eq_res, c_eq_agenda = st.columns([1, 1.2])
            
            with c_eq_res:
                if df_equipos.empty:
                    st.info("No hay equipos registrados disponibles.")
                else:
                    eq_seleccionado = st.selectbox("Seleccionar Equipo:", df_equipos['nombre'].tolist())
                    datos_eq = df_equipos[df_equipos['nombre'] == eq_seleccionado].iloc[0]
                    
                    st.caption(f"👀 Visibilidad: **{datos_eq.get('visibilidad', 'Privado')}**")
                    if str(datos_eq.get('requisitos', '')).strip():
                        st.warning(f"⚠️ **Requisitos:** {datos_eq['requisitos']}")
                    
                    fecha_res = st.date_input("Fecha de reserva:")
                    
                    # --- MOSTRAR DISPONIBILIDAD (CALENDARIO VISUAL) ---
                    st.markdown(f"**Disponibilidad para el {fecha_res.strftime('%d/%m/%Y')}:**")
                    df_r_dia = pd.DataFrame()
                    if not df_reservas.empty:
                        df_r_eq = df_reservas[df_reservas['equipo_id'] == str(datos_eq['id'])].copy()
                        if not df_r_eq.empty:
                            df_r_eq['fecha_inicio'] = pd.to_datetime(df_r_eq['fecha_inicio'])
                            df_r_eq['fecha_fin'] = pd.to_datetime(df_r_eq['fecha_fin'])
                            df_r_dia = df_r_eq[df_r_eq['fecha_inicio'].dt.date == fecha_res].sort_values(by='fecha_inicio')
                    
                    if not df_r_dia.empty:
                        for _, row in df_r_dia.iterrows():
                            st.markdown(f"🚫 `{row['fecha_inicio'].strftime('%H:%M')} - {row['fecha_fin'].strftime('%H:%M')}` (Reservado por {row['usuario']})")
                    else:
                        st.success("✅ Todo el día está libre.")
                    
                    # --- FORMULARIO DE RESERVA ---
                    col_h1, col_h2 = st.columns(2)
                    with col_h1: t_ini = st.time_input("Hora Inicio:", value=time(9, 0))
                    with col_h2: t_fin = st.time_input("Hora Fin:", value=time(10, 0))
                    
                    if st.button("Confirmar Reserva", type="primary", use_container_width=True):
                        dt_ini = datetime.combine(fecha_res, t_ini)
                        dt_fin = datetime.combine(fecha_res, t_fin)
                        
                        if dt_ini >= dt_fin: 
                            st.error("La hora de inicio debe ser anterior a la de fin.")
                        else:
                            # LÓGICA ANTI-CHOQUE
                            solapamiento = False
                            if not df_r_dia.empty:
                                for _, r in df_r_dia.iterrows():
                                    if dt_ini < r['fecha_fin'] and dt_fin > r['fecha_inicio']:
                                        solapamiento = True
                                        break
                            
                            if solapamiento:
                                st.error("❌ El horario seleccionado choca con una reserva existente. Por favor elige otro bloque.")
                            else:
                                try:
                                    # Guardar en Base de Datos
                                    supabase.table("reservas").insert({
                                        "equipo_id": str(datos_eq['id']), "usuario": usuario_actual, 
                                        "fecha_inicio": dt_ini.isoformat(), "fecha_fin": dt_fin.isoformat(), "lab_id": lab_id
                                    }).execute()
                                    
                                    # Enviar Correos Automatizados
                                    admin_email = obtener_admin_email(lab_id)
                                    user_email = st.session_state.usuario_autenticado
                                    enviar_correo_reserva(
                                        datos_eq['nombre'], fecha_res.strftime('%d/%m/%Y'),
                                        t_ini.strftime('%H:%M'), t_fin.strftime('%H:%M'),
                                        usuario_actual, admin_email, user_email
                                    )
                                    
                                    st.success("✅ Reserva guardada y notificaciones enviadas.")
                                    st.rerun()
                                except Exception as e: st.error(f"Error al reservar: {e}")
            
            with c_eq_agenda:
                st.write("**Tus Próximas Reservas:**")
                if not df_reservas.empty and not df_equipos.empty:
                    df_r = pd.merge(df_reservas, df_equipos[['id', 'nombre']], left_on='equipo_id', right_on='id', how='inner')
                    df_r['fecha_inicio'] = pd.to_datetime(df_r['fecha_inicio'])
                    df_r['fecha_fin'] = pd.to_datetime(df_r['fecha_fin'])
                    df_futuras = df_r[(df_r['fecha_fin'] >= pd.to_datetime('today')) & (df_r['usuario'] == usuario_actual)].sort_values(by='fecha_inicio')
                    
                    if df_futuras.empty: st.info("No tienes reservas activas.")
                    else:
                        for _, row in df_futuras.iterrows():
                            with st.container(border=True):
                                st.markdown(f"**{row['nombre_y']}**")
                                st.write(f"🕒 {row['fecha_inicio'].strftime('%d/%b %H:%M')} - {row['fecha_fin'].strftime('%H:%M')}")
                                gcal_link = generar_link_gcal(
                                    titulo=f"Uso Lab: {row['nombre_y']}", 
                                    inicio=row['fecha_inicio'], fin=row['fecha_fin'], 
                                    descripcion=f"Reserva gestionada en Stck."
                                )
                                st.markdown(f"[📅 Agregar a mi Google Calendar]({gcal_link})", unsafe_allow_html=True)
                else:
                    st.info("No hay reservas.")
                    
        # PANEL DE ADMINISTRACIÓN DE EQUIPOS
        if rol_actual == "admin" and sub_tab_mis_equipos:
            with sub_tab_mis_equipos:
                st.write("Gestiona la información, visibilidad y reglas de uso de tus equipos.")
                if not df_equipos.empty:
                    cols_ed_eq = ['nombre', 'descripcion', 'visibilidad', 'requisitos', 'id']
                    edited_eq_df = st.data_editor(
                        df_equipos[cols_ed_eq].copy(), 
                        column_config={
                            "id": st.column_config.TextColumn("ID", disabled=True),
                            "visibilidad": st.column_config.SelectboxColumn("Visibilidad", options=["Solo mi Laboratorio", "Mi Instituto", "Toda la Sede", "Público General"])
                        }, 
                        use_container_width=True, hide_index=True
                    )
                    
                    if st.button("💾 Guardar Cambios en Equipos", type="secondary"):
                        for _, row in edited_eq_df.iterrows():
                            d = row.replace({np.nan: None}).to_dict()
                            if 'id' in d and str(d['id']).strip(): 
                                d['lab_id'] = lab_id 
                                supabase.table("equipos_lab").upsert(d).execute()
                        st.success("Equipos actualizados.")
                        st.rerun()
                
                st.markdown("---")
                with st.expander("➕ Registrar Nuevo Equipo", expanded=df_equipos.empty):
                    with st.form("form_nuevo_equipo"):
                        n_eq = st.text_input("Nombre del Equipo (Ej: HPLC Agilent)")
                        d_eq = st.text_input("Descripción / Ubicación")
                        req_eq = st.text_area("Requisitos de Uso (Ej: Solo usuarios capacitados)")
                        v_eq = st.selectbox("Visibilidad", ["Solo mi Laboratorio", "Mi Instituto", "Toda la Sede", "Público General"])
                        
                        if st.form_submit_button("Crear Equipo", type="primary"):
                            try:
                                supabase.table("equipos_lab").insert({
                                    "nombre": n_eq, "descripcion": d_eq, "visibilidad": v_eq, 
                                    "requisitos": req_eq, "lab_id": lab_id
                                }).execute()
                                st.success("Equipo registrado exitosamente.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al guardar: {e}")

    with tab_prot:
        tab_ejecutar, tab_crear = st.tabs(["🚀 Ejecutar", "📝 Nuevo"])
        with tab_ejecutar:
            if df_prot.empty: st.info("Sin protocolos.")
            else:
                p_sel = st.selectbox("Protocolo:", df_prot['nombre'].tolist())
                n_muestras = st.number_input("Muestras:", min_value=1, value=1)
                if st.button("🔍 Previsualizar"):
                    info_p = df_prot[df_prot['nombre'] == p_sel]['materiales_base'].values[0]
                    descuentos = []
                    for linea in info_p.split('\n'):
                        if ":" in linea:
                            partes = linea.split(":")
                            item_db = df[df['nombre'].str.contains(partes[0].strip(), case=False, na=False)]
                            if not item_db.empty:
                                descuentos.append({"id": str(item_db.iloc[0]['id']), "Reactivo": item_db.iloc[0]['nombre'], "Stock": item_db.iloc[0]['cantidad_actual'], "Descuento": float(partes[1].strip()) * n_muestras, "Unidad": item_db.iloc[0]['unidad']})
                    if descuentos:
                        st.dataframe(pd.DataFrame(descuentos), hide_index=True)
                        if st.button("✅ Descontar del Inventario", type="primary"):
                            crear_punto_restauracion(df)
                            for d in descuentos:
                                supabase.table("items").update({"cantidad_actual": int(d["Stock"] - d["Descuento"])}).eq("id", d["id"]).execute()
                                supabase.table("movimiento").insert({"item_id": d["id"], "nombre_item": d["Reactivo"], "cantidad_cambio": -d["Descuento"], "tipo": f"Uso Kit: {p_sel}", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                            st.rerun()
        with tab_crear:
            with st.form("form_nuevo_prot"):
                n_prot = st.text_input("Nombre (Ej: PCR Mix)")
                mat_base = st.text_area("Reactivos (Nombre : Cantidad)")
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
                
        if rol_actual == "admin" and not df.empty:
            st.markdown("---")
            st.markdown("### 🛒 Panel de Compras")
            st.caption(f"📧 **Destinatario:** `{correo_destinatario_compras}`")
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
                        
                        st.dataframe(df_pred[['nombre', 'cantidad_actual', 'unidad', 'consumo_30d', 'tasa_diaria', 'dias_restantes']].sort_values(by='dias_restantes_num', ascending=True).drop(columns=['dias_restantes_num']), use_container_width=True, hide_index=True)
                    else: st.info("Aún no hay suficientes retiros para proyectar matemáticas.")
                else: st.info("Registra movimientos para que la IA aprenda el consumo.")

        with tab_equipo:
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
                        except: st.error("Error al dar acceso.")
            st.write("**Miembros Activos:**")
            try:
                miembros = supabase.table("equipo").select("nombre, email, rol, perfil_academico, institucion").eq("lab_id", lab_id).execute()
                if miembros.data: st.dataframe(pd.DataFrame(miembros.data), hide_index=True, use_container_width=True)
            except: pass

# --- PANEL IA ---
with col_chat:
    st.markdown("### 💬 Secretario IA")
    chat_box = st.container(height=400, border=False)
    
    if "messages" not in st.session_state: st.session_state.messages = [{"role": "assistant", "content": f"Conectado. Háblame o mándame una foto."}]
    for m in st.session_state.messages:
        with chat_box: st.chat_message(m["role"]).markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎙️ Hablar", stop_prompt="⏹️ Enviar", just_once=True, key='voice_input')
    prompt = v_in if v_in else st.chat_input("Ej: Saqué 2 buffer...")

    with st.expander("📸 Enviar Foto de Etiqueta"):
        accion_foto = st.radio("¿Qué deseas hacer con la foto?", ["➕ Agregar como Nuevo", "🔄 Actualizar Existente"], horizontal=True)
        item_a_actualizar = None
        if accion_foto == "🔄 Actualizar Existente" and not df.empty: item_a_actualizar = st.selectbox("Selecciona reactivo:", df['nombre'].tolist())
        foto_chat = st.camera_input("Capturar Etiqueta")
        if foto_chat and st.button("🧠 Procesar Foto", type="primary", use_container_width=True):
            img = Image.open(foto_chat).convert('RGB')
            st.session_state.messages.append({"role": "user", "content": "📸 *Foto enviada.*"})
            with chat_box: st.chat_message("user").markdown("📸 *Foto enviada.*")
            with st.chat_message("assistant"):
                with st.spinner("Analizando..."):
                    try:
                        if accion_foto == "➕ Agregar como Nuevo":
                            prompt_vision = "Extrae los datos de esta etiqueta química. Responde SOLO JSON: {\"nombre\": \"\", \"categoria\": \"\", \"cantidad_actual\": 0, \"unidad\": \"\"}"
                            res_ai = model.generate_content([prompt_vision, img]).text
                            data = json.loads(re.search(r'\{.*\}', res_ai, re.DOTALL).group())
                            res_ins = supabase.table("items").insert({"nombre": data.get('nombre', 'Desconocido'), "cantidad_actual": data.get('cantidad_actual', 0), "unidad": data.get('unidad', 'unidades'), "categoria": data.get('categoria', 'GENERAL'), "lab_id": lab_id}).execute()
                            itm = res_ins.data[0]
                            supabase.table("movimiento").insert({"item_id": str(itm['id']), "nombre_item": itm['nombre'], "cantidad_cambio": itm['cantidad_actual'], "tipo": "Nuevo IA (Foto)", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                            msg = f"📸 **Creado:** {itm['nombre']} | Stock: {itm['cantidad_actual']}"
                        else:
                            prompt_vision = f"Esta es una foto del reactivo '{item_a_actualizar}'. Extrae la cantidad. Responde SOLO JSON: {{\"{item_a_actualizar}\": true, \"cantidad_actual\": 0}}"
                            res_ai = model.generate_content([prompt_vision, img]).text
                            data = json.loads(re.search(r'\{.*\}', res_ai, re.DOTALL).group())
                            nueva_cant = data.get('cantidad_actual', 0)
                            id_ac = str(df[df['nombre'] == item_a_actualizar].iloc[0]['id'])
                            supabase.table("items").update({"cantidad_actual": nueva_cant}).eq("id", id_ac).execute()
                            supabase.table("movimiento").insert({"item_id": id_ac, "nombre_item": item_a_actualizar, "cantidad_cambio": nueva_cant, "tipo": "Actualizado IA (Foto)", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                            msg = f"📸 **Actualizado:** {item_a_actualizar} ahora tiene {nueva_cant} en stock."
                        st.markdown(msg); st.session_state.messages.append({"role": "assistant", "content": msg}); st.rerun()
                    except: st.error("No pude leer la etiqueta.")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_box: st.chat_message("user").markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                try:
                    d_ia = df[['id', 'nombre', 'cantidad_actual', 'ubicacion']].to_json(orient='records') if not df.empty else "[]"
                    res_ai = model.generate_content(f"Inventario: {d_ia}\nUsa id si existe, si no 'NUEVO'. JSON: EJECUTAR_ACCION:{{\"id\":\"\",\"nombre\":\"\",\"cantidad\":0,\"unidad\":\"\",\"ubicacion\":\"\"}}\nUsuario: {prompt}").text
                    if "EJECUTAR_ACCION:" in res_ai:
                        data = json.loads(re.search(r'\{.*\}', res_ai, re.DOTALL).group())
                        id_ac = str(data.get('id', 'NUEVO'))
                        if id_ac != "NUEVO" and (not df.empty and id_ac in df['id'].astype(str).values):
                            stock_viejo = df[df['id'].astype(str) == id_ac].iloc[0]['cantidad_actual']
                            cambio = data['cantidad'] - stock_viejo
                            supabase.table("items").update({"cantidad_actual": data['cantidad'], "ubicacion": data.get('ubicacion', '')}).eq("id", id_ac).execute()
                            itm = supabase.table("items").select("*").eq("id", id_ac).execute().data[0]
                            supabase.table("movimiento").insert({"item_id": id_ac, "nombre_item": itm['nombre'], "cantidad_cambio": cambio, "tipo": "Acción IA", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                            msg = f"✅ **Actualizado:** {itm['nombre']} | Stock: {itm['cantidad_actual']}"
                        else:
                            res_ins = supabase.table("items").insert({"nombre": data['nombre'], "cantidad_actual": data['cantidad'], "unidad": data['unidad'], "ubicacion": data.get('ubicacion', ''), "lab_id": lab_id}).execute()
                            itm = res_ins.data[0]
                            supabase.table("movimiento").insert({"item_id": str(itm['id']), "nombre_item": itm['nombre'], "cantidad_cambio": itm['cantidad_actual'], "tipo": "Nuevo IA", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                            msg = f"📦 **Creado:** {itm['nombre']} | Stock: {itm['cantidad_actual']}"
                        
                        st.session_state.auto_search = itm['nombre']
                        st.markdown(msg); st.session_state.messages.append({"role": "assistant", "content": msg}); st.rerun() 
                    else: st.markdown(res_ai); st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except: st.error("Error IA.")

import streamlit as st
import google.generativeai as genai
from supabase import create_client
import pandas as pd
import json
import re
from streamlit_mic_recorder import speech_to_text
from datetime import datetime, date, timedelta
import numpy as np
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

# --- 2. SISTEMA DE AUTENTICACIÓN Y ROLES ---
if "usuario_autenticado" not in st.session_state:
    st.session_state.usuario_autenticado = None
    st.session_state.user_uid = None
    st.session_state.lab_id = None
    st.session_state.rol = None
    st.session_state.nombre_usuario = None

# PANTALLA DE LOGIN
if st.session_state.usuario_autenticado is None:
    st.markdown("<h1 style='text-align: center;'>🔬 Stck</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>Gestión Inteligente de Inventario B2B</p>", unsafe_allow_html=True)
    
    col_espacio1, col_login, col_espacio2 = st.columns([1, 2, 1])
    with col_login:
        tab_login, tab_reg = st.tabs(["🔐 Iniciar Sesión", "🏢 Crear Cuenta"])
        
        with tab_login:
            with st.container(border=True):
                email_login = st.text_input("Correo")
                pass_login = st.text_input("Contraseña", type="password")
                if st.button("Acceder a Stck", type="primary", use_container_width=True):
                    with st.spinner("Autenticando..."):
                        try:
                            res = supabase.auth.sign_in_with_password({"email": email_login, "password": pass_login})
                            email = res.user.email
                            uid = res.user.id
                            st.session_state.usuario_autenticado = email
                            st.session_state.user_uid = uid
                            
                            req_eq = supabase.table("equipo").select("*").eq("email", email).execute()
                            if req_eq.data:
                                st.session_state.lab_id = req_eq.data[0]['lab_id']
                                st.session_state.rol = req_eq.data[0]['rol']
                                st.session_state.nombre_usuario = req_eq.data[0].get('nombre', email)
                            else:
                                st.session_state.lab_id = "PENDIENTE"
                                st.session_state.rol = "espera"
                                st.session_state.nombre_usuario = email
                            st.rerun()
                        except Exception as e:
                            st.error("Credenciales incorrectas.")
                            
        with tab_reg:
            with st.container(border=True):
                st.info("Únete a Stck. Completa tu perfil profesional.")
                nombre_reg = st.text_input("Nombre y Apellido")
                perfil_reg = st.selectbox("Perfil Académico/Profesional", ["Estudiante de Pregrado", "Estudiante de Doctorado/Postdoc", "Investigador Principal (PI)", "Lab Manager", "CEO / Fundador", "Otro"])
                inst_reg = st.text_input("Universidad, Centro de Investigación o Empresa")
                email_reg = st.text_input("Nuevo Correo")
                pass_reg = st.text_input("Crear Contraseña (mín 6 caracteres)", type="password")
                
                if st.button("Crear Cuenta", type="primary", use_container_width=True):
                    if not nombre_reg or not inst_reg:
                        st.warning("Por favor completa tu Nombre y Universidad/Empresa.")
                    else:
                        try:
                            res = supabase.auth.sign_up({"email": email_reg, "password": pass_reg})
                            # Guardar la demografía en la tabla equipo (sin lab_id por ahora)
                            supabase.table("equipo").insert({
                                "email": email_reg, 
                                "nombre": nombre_reg, 
                                "perfil_academico": perfil_reg, 
                                "institucion": inst_reg,
                                "rol": "espera"
                            }).execute()
                            st.success("¡Cuenta creada! Tu administrador ya puede darte acceso.")
                        except Exception as e:
                            st.error(f"Fallo al registrar: {e}")
    st.stop()

# --- PANTALLA DE "SALA DE ESPERA" ---
if st.session_state.lab_id == "PENDIENTE":
    st.warning("⏳ Sala de Espera")
    st.write(f"Hola **{st.session_state.nombre_usuario}**. Tu cuenta está activa, pero aún no has sido asignado a ningún laboratorio.")
    st.write("👉 Pídele al administrador de tu laboratorio que añada tu correo al equipo.")
    st.divider()
    st.write("¿Eres el administrador de un laboratorio nuevo?")
    if st.button("Crear mi propio espacio de trabajo (Ser Admin)"):
        supabase.table("equipo").update({"lab_id": st.session_state.user_uid, "rol": "admin"}).eq("email", st.session_state.usuario_autenticado).execute()
        st.session_state.lab_id = st.session_state.user_uid
        st.session_state.rol = "admin"
        st.rerun()
    if st.button("🚪 Cerrar Sesión"):
        st.session_state.usuario_autenticado = None
        st.rerun()
    st.stop()

# --- VARIABLES GLOBALES ---
lab_id = st.session_state.lab_id
usuario_actual = st.session_state.get('nombre_usuario', st.session_state.get('usuario_autenticado', 'Usuario'))

if 'auto_search' not in st.session_state: st.session_state.auto_search = ""
if "backup_inventario" not in st.session_state: st.session_state.backup_inventario = None
def crear_punto_restauracion(df_actual): st.session_state.backup_inventario = df_actual.copy()

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

# --- CARGA DE DATOS ---
res_items = supabase.table("items").select("*").eq("lab_id", lab_id).execute()
df = pd.DataFrame(res_items.data)

for col in ['id', 'nombre', 'categoria', 'ubicacion', 'posicion_caja', 'unidad', 'fecha_vencimiento', 'fecha_cotizacion']:
    if col not in df.columns: df[col] = ""
    df[col] = df[col].astype(str).replace(["nan", "None", "NaT"], "")
for col in ['cantidad_actual', 'umbral_minimo', 'precio']:
    if col not in df.columns: df[col] = 0
    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

# --- INTERFAZ PRINCIPAL ---
col_logo, col_user = st.columns([3, 1])
with col_logo: st.markdown("## 🔬 Stck")
with col_user: 
    st.info(f"👤 {usuario_actual} ({st.session_state.get('rol', '...')})")
    if st.button("🚪 Cerrar Sesión"):
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

col_chat, col_mon = st.columns([1, 1.6], gap="large")

with col_mon:
    if st.session_state.rol == "admin": tab_inv, tab_edit, tab_equipo = st.tabs(["📦 Inventario & Finanzas", "⚙️ Editar Masivo", "👥 Equipo"])
    else: tab_inv, tab_edit = st.tabs(["📦 Inventario", "⚙️ Editar Masivo"])
    
    with tab_inv:
        # RADAR DE VENCIMIENTOS Y STOCK
        if not df.empty:
            df['vence_pronto'] = False
            hoy = pd.to_datetime(date.today())
            for idx, row in df.iterrows():
                try:
                    if row['fecha_vencimiento'] and str(row['fecha_vencimiento']).strip():
                        fv = pd.to_datetime(row['fecha_vencimiento'])
                        if (fv - hoy).days <= 30: df.at[idx, 'vence_pronto'] = True
                except: pass
            
            df_vencidos = df[df['vence_pronto'] == True]
            df_criticos = df[(df['cantidad_actual'] <= df['umbral_minimo']) & (df['umbral_minimo'] > 0)]
            
            if not df_vencidos.empty or not df_criticos.empty:
                st.error("🚨 **Alertas de Laboratorio**")
                if not df_criticos.empty: st.warning(f"⚠️ {len(df_criticos)} reactivos con stock crítico.")
                if not df_vencidos.empty: st.warning(f"⚠️ {len(df_vencidos)} reactivos vencen en menos de 30 días.")
        
        # TABLA DE INVENTARIO COMPLETA VISIBLE
        busqueda = st.text_input("🔍 Buscar reactivo...", value=st.session_state.auto_search)
        df_show = df[df['nombre'].str.contains(busqueda, case=False)] if busqueda else df
        
        if df.empty: st.info("Inventario vacío.")
        else:
            cols_mostrar = ['nombre', 'cantidad_actual', 'unidad', 'ubicacion', 'fecha_vencimiento']
            st.dataframe(df_show[cols_mostrar], use_container_width=True, hide_index=True)

        # MÓDULO FINANCIERO (SOLO ADMIN)
        if st.session_state.rol == "admin" and not df.empty:
            st.markdown("---")
            st.markdown("### 🛒 Panel Financiero y Compras")
            st.write("Solicita nuevas cotizaciones o reabastece reactivos directamente.")
            
            c_comp1, c_comp2 = st.columns([2, 1])
            with c_comp1:
                item_compra = st.selectbox("Seleccionar Reactivo a Comprar:", df['nombre'].tolist())
                datos_item = df[df['nombre'] == item_compra].iloc[0]
                
                fecha_cot = datos_item['fecha_cotizacion'] if datos_item['fecha_cotizacion'] else "Nunca"
                precio_ref = datos_item['precio'] if datos_item['precio'] > 0 else "No registrado"
                
                st.caption(f"**Última cotización:** {fecha_cot} | **Precio Referencial:** ${precio_ref}")
            
            with c_comp2:
                st.write("") # Espaciador
                st.write("")
                # DOBLE CHEQUEO PARA COMPRAR
                if st.button("🛒 Iniciar Solicitud", use_container_width=True):
                    st.session_state.confirmar_compra = item_compra
                
                if st.session_state.get('confirmar_compra') == item_compra:
                    st.warning("¿Confirmas enviar correo a adquisiciones?")
                    c_si, c_no = st.columns(2)
                    if c_si.button("✅ Enviar", type="primary"):
                        enviar_correo_compras(item_compra, precio_ref, usuario_actual)
                        st.success("Solicitud enviada.")
                        st.session_state.confirmar_compra = None
                        st.rerun()
                    if c_no.button("❌ Cancelar"):
                        st.session_state.confirmar_compra = None
                        st.rerun()

    with tab_edit:
        st.markdown("### ✍️ Edición (Precios y Fechas)")
        if not df.empty:
            cols_edit = ['nombre', 'cantidad_actual', 'precio', 'fecha_vencimiento', 'fecha_cotizacion', 'id']
            edited_df = st.data_editor(df[cols_edit].copy(), column_config={"id": st.column_config.TextColumn("ID", disabled=True)}, use_container_width=True, hide_index=True)
            
            if st.button("💾 Guardar Cambios Manuales"):
                for _, row in edited_df.iterrows():
                    d = row.replace({np.nan: None}).to_dict()
                    if 'id' in d and str(d['id']).strip(): 
                        d['lab_id'] = lab_id 
                        supabase.table("items").upsert(d).execute()
                st.success("Guardado.")
                st.rerun()

    if st.session_state.rol == "admin":
        with tab_equipo:
            st.markdown("### 🤝 Gestión de Accesos")
            with st.container(border=True):
                nuevo_email = st.text_input("Correo electrónico a invitar:")
                rol_nuevo = st.selectbox("Rol:", ["miembro", "admin"])
                if st.button("Dar Acceso", type="primary", use_container_width=True):
                    try:
                        # Actualizamos el lab_id y rol si el usuario ya se registró y estaba en espera
                        res = supabase.table("equipo").update({"lab_id": lab_id, "rol": rol_nuevo}).eq("email", nuevo_email).execute()
                        if len(res.data) == 0:
                            st.warning("Ese correo aún no se ha registrado en Stck. Pídele que cree una cuenta primero para llenar sus datos demográficos.")
                        else: st.success(f"Acceso otorgado a {nuevo_email}.")
                    except Exception as e: st.error(f"Error: {e}")
            
            st.write("**Miembros con Acceso:**")
            try:
                miembros = supabase.table("equipo").select("nombre, email, rol, perfil_academico, institucion").eq("lab_id", lab_id).execute()
                df_miembros = pd.DataFrame(miembros.data)
                st.dataframe(df_miembros, hide_index=True, use_container_width=True)
            except: st.info("No hay miembros agregados.")

# --- PANEL IA ---
with col_chat:
    st.markdown("### 💬 Secretario IA")
    chat_box = st.container(height=500, border=False)
    
    if "messages" not in st.session_state: st.session_state.messages = [{"role": "assistant", "content": f"Conectado. ¿Qué guardamos hoy?"}]
    for m in st.session_state.messages:
        with chat_box: st.chat_message(m["role"]).markdown(m["content"])

    v_in = speech_to_text(language='es-CL', start_prompt="🎙️ Hablar", stop_prompt="⏹️ Enviar", just_once=True, key='voice_input')
    prompt = v_in if v_in else st.chat_input("Ej: Saqué 2 buffer...")

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
                            supabase.table("items").update({"cantidad_actual": data['cantidad'], "ubicacion": data['ubicacion']}).eq("id", id_ac).execute()
                            itm = supabase.table("items").select("*").eq("id", id_ac).execute().data[0]
                            supabase.table("movimiento").insert({"item_id": id_ac, "nombre_item": itm['nombre'], "cantidad_cambio": data['cantidad'], "tipo": "Acción IA", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                            msg = f"✅ **Actualizado:** {itm['nombre']} | Stock: {itm['cantidad_actual']}"
                        else:
                            res_ins = supabase.table("items").insert({"nombre": data['nombre'], "cantidad_actual": data['cantidad'], "unidad": data['unidad'], "ubicacion": data['ubicacion'], "lab_id": lab_id}).execute()
                            itm = res_ins.data[0]
                            supabase.table("movimiento").insert({"item_id": str(itm['id']), "nombre_item": itm['nombre'], "cantidad_cambio": itm['cantidad_actual'], "tipo": "Nuevo IA", "usuario": usuario_actual, "lab_id": lab_id}).execute()
                            msg = f"📦 **Creado:** {itm['nombre']} | Stock: {itm['cantidad_actual']}"
                        
                        st.session_state.auto_search = itm['nombre']
                        st.markdown(msg)
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        st.rerun() 
                    else:
                        st.markdown(res_ai)
                        st.session_state.messages.append({"role": "assistant", "content": res_ai})
                except Exception as e: st.error(f"Error IA: {e}")

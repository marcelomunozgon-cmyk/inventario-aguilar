def procesar_todo(texto, imagen=None):
    prompt = f"""
    Analiza esta instrucción de inventario: "{texto}"
    Responde estrictamente un JSON válido:
    {{
      "producto": "nombre", 
      "valor": numero, 
      "unidad": "unidad o null",
      "accion": "sumar/reemplazar", 
      "ubicacion": "texto o null", 
      "umbral_minimo": numero o null
    }}
    """
    try:
        if imagen:
            imagen.thumbnail((1000, 1000))
            response = model.generate_content([prompt, imagen])
        else:
            response = model.generate_content(prompt)
            
        raw_text = response.text
        start = raw_text.find('{')
        end = raw_text.rfind('}') + 1
        orden = json.loads(raw_text[start:end])
        
        # --- MEJORA AQUÍ: BÚSQUEDA BORROSA ---
        nombre_buscado = orden['producto'].lower()
        palabras = nombre_buscado.split()
        
        # Empezamos la consulta
        query = supabase.table("items").select("*")
        
        # Filtramos: el nombre debe contener TODAS las palabras que dictaste
        for p in palabras:
            if len(p) > 1: # Ignoramos letras sueltas
                query = query.ilike("nombre", f"%{p}%")
        
        res = query.execute()
        
        # Si no encuentra con todas, intentamos buscar solo con la palabra más larga (la más importante)
        if not res.data and palabras:
            palabra_larga = max(palabras, key=len)
            res = supabase.table("items").select("*").ilike("nombre", f"%{palabra_larga}%").execute()

        if not res.data: 
            return f"❓ No encontré nada parecido a '{nombre_buscado}'."
        
        # Si hay varios parecidos, tomamos el primero
        item = res.data[0]
        updates = {}
        
        if orden.get('valor') is not None:
            actual = item.get('cantidad_actual') or 0
            nueva_cant = actual + orden['valor'] if orden['accion'] == 'sumar' else orden['valor']
            updates['cantidad_actual'] = nueva_cant
            if orden.get('unidad'): updates['unidad'] = orden['unidad']
            
        if orden.get('ubicacion'): updates['ubicacion_detallada'] = orden['ubicacion']
        if orden.get('umbral_minimo') is not None: updates['umbral_minimo'] = orden['umbral_minimo']
        
        if updates:
            supabase.table("items").update(updates).eq("id", item['id']).execute()
            return f"✅ **{item['nombre']}** actualizado correctamente (Detectado como '{nombre_buscado}')."
        return "⚠️ No se detectaron cambios."

    except Exception as e:
        return f"❌ Error: {str(e)}"

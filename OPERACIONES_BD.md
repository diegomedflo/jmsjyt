# Base de Datos — Procedimiento de sincronizacion local <-> Railway

## Reglas que NUNCA se rompen

1. **Siempre `IF NOT EXISTS`** en todo CREATE TABLE, CREATE INDEX, CREATE SEQUENCE.
2. **Nunca PL/pgSQL con `$$`** en el schema — PowerShell interpreta `$$` como variable del sistema y corrompe el SQL.
3. **Nunca usar pgAdmin para ejecutar el schema** — usar siempre `psql` desde la terminal.
4. **El Railway web UI no muestra tablas particionadas** — si ves "You have no tables" pero el psql dice que existen, es normal.
5. **Siempre aplicar primero en local, verificar, luego en Railway.**

---

## Conexiones

### Local
- Host: `localhost`
- Puerto: `5432`
- BD: `jmsjyt`
- Usuario: `postgres`
- Contrasena: `postgres`

### Railway (produccion)
- Host: `reseau.proxy.rlwy.net`
- Puerto: `15338`
- BD: `railway`
- Usuario: `postgres`
- Contrasena: ver variable `PGPASSWORD` en Railway Variables

---

## Comandos de referencia rapida

### Aplicar schema en LOCAL
```powershell
$env:PGPASSWORD="postgres"
psql -U postgres -d jmsjyt -f "D:\ProyectosPython\JMSJyT\sql\schema.sql"
```

### Aplicar schema en RAILWAY
```powershell
$env:PGPASSWORD="QjxLqIKMrlbXWrIiMIBQMTmDythBfyiM"
psql -h reseau.proxy.rlwy.net -p 15338 -U postgres -d railway -f "D:\ProyectosPython\JMSJyT\sql\schema.sql"
```

### Verificar tablas en LOCAL
```powershell
$env:PGPASSWORD="postgres"
psql -U postgres -d jmsjyt -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
```

### Verificar tablas en RAILWAY
```powershell
$env:PGPASSWORD="QjxLqIKMrlbXWrIiMIBQMTmDythBfyiM"
psql -h reseau.proxy.rlwy.net -p 15338 -U postgres -d railway -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
```

### Resetear BD local desde cero (CUIDADO: borra todo)
```powershell
$env:PGPASSWORD="postgres"
psql -U postgres -c "DROP DATABASE IF EXISTS jmsjyt;"
psql -U postgres -c "CREATE DATABASE jmsjyt ENCODING 'UTF8';"
psql -U postgres -d jmsjyt -f "D:\ProyectosPython\JMSJyT\sql\schema.sql"
```

---

## Flujo ante cualquier cambio de schema

```
1. Editar sql/schema.sql
      - Agregar la nueva tabla/columna/indice con IF NOT EXISTS
      - Nunca eliminar lineas existentes (rompe el idempotente)

2. Aplicar en LOCAL
      $env:PGPASSWORD="postgres"
      psql -U postgres -d jmsjyt -f "D:\ProyectosPython\JMSJyT\sql\schema.sql"

3. Verificar que no hay ERROR (NOTICE = ok, solo informa que ya existia)

4. Aplicar en RAILWAY
      $env:PGPASSWORD="QjxLqIKMrlbXWrIiMIBQMTmDythBfyiM"
      psql -h reseau.proxy.rlwy.net -p 15338 -U postgres -d railway -f "D:\ProyectosPython\JMSJyT\sql\schema.sql"

5. Verificar que no hay ERROR

6. Commit y push
      git add sql/schema.sql
      git commit -m "feat(db): descripcion del cambio"
      git push origin main
```

---

## Interpretacion de la salida de psql

| Mensaje | Significado | Accion |
|---|---|---|
| `CREATE TABLE` | Tabla creada nueva | OK |
| `NOTICE: relation already exists, skipping` | Ya existia, no se toco | OK (esperado) |
| `INSERT 0 1` | Fila insertada | OK |
| `INSERT 0 0` | Ya existia (ON CONFLICT), no se inserto | OK (esperado) |
| `ERROR: relation already exists` | CREATE sin IF NOT EXISTS | Agregar IF NOT EXISTS al schema |
| `ERROR: server closed the connection` | Problema de encoding (PL/pgSQL con $$) | Nunca usar $$ en el schema |

---

## Anadir nuevas columnas a tablas existentes

PostgreSQL no tiene `ADD COLUMN IF NOT EXISTS` antes de la v9.6. Como Railway corre v14+, si es posible usarlo:

```sql
ALTER TABLE franquiciados
    ADD COLUMN IF NOT EXISTS nueva_columna VARCHAR(120);
```

Agregar este ALTER al final de `schema.sql` antes de los INSERTs del seed.

---

## Aplicar migraciones desde local usando Railway CLI (método probado)

### Contexto
Cuando la BD de Railway necesita nuevas columnas y hay que aplicar un archivo `.sql`
desde la máquina de desarrollo Windows, el método con `-f` falla en PowerShell porque
el flag se ignora silenciosamente. El método correcto es conectarse en modo interactivo
y usar `\i` dentro de psql.

### Paso 1 — Obtener las credenciales públicas
```powershell
# Obtener DATABASE_PUBLIC_URL (accesible desde internet)
railway variables --service Postgres --json | python -c "import sys,json; v=json.load(sys.stdin); print(v['DATABASE_PUBLIC_URL'])"
```
Guarda el resultado. Tendrá la forma:
```
postgresql://postgres:PASSWORD@reseau.proxy.rlwy.net:15338/railway
```

### Paso 2 — Conectarse en modo interactivo
```powershell
$env:PGPASSWORD = "PASSWORD_AQUI"
psql "postgresql://postgres:PASSWORD_AQUI@reseau.proxy.rlwy.net:15338/railway"
```
> **NUNCA usar `-f archivo.sql`** en PowerShell — el flag se ignora con un warning
> y psql queda en modo interactivo sin ejecutar nada.

### Paso 3 — Ejecutar el archivo desde dentro de psql
```
railway=# \i sql/migrate_vX_X_nombre.sql
```
El path es relativo al directorio desde donde se lanzó psql (normalmente la raíz del proyecto).

### Paso 4 — Verificar columnas aplicadas
```sql
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'nombre_tabla'
  AND column_name IN ('col1', 'col2', 'col3');
```

### Paso 5 — Salir
```
railway=# \q
```

### Interpretación de NOTICEs durante la migración
- `NOTICE: column "X" of relation "Y" already exists, skipping` → columna ya existía, **OK**
- `ALTER TABLE` sin NOTICE → columna fue creada nueva, **OK**
- `ERROR:` → problema real, leer el mensaje

### Convención para archivos de migración
- Ubicación: `sql/`
- Nombre: `migrate_vX_X_descripcion.sql` (ej: `migrate_v2_2_paquetes_detalle.sql`)
- Siempre idempotentes: usar `ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS`
- También actualizar `sql/schema.sql` con los mismos cambios para que refleje el estado actual completo

---

## Admin inicial

- Usuario: `admin`
- Contrasena: `Mateo1997`
- Hash: `pbkdf2:sha256:600000$v3AFpNeY4Ft6jOG6$9f7f3bfac4126c54667af18e09d70df6658a09079ef43b8d47ec54bed7ab58a3`

El INSERT del admin ya esta incluido al final de `schema.sql` con `ON CONFLICT DO NOTHING`,
por lo que es seguro volver a ejecutar el schema sin duplicar el usuario.

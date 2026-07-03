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

## Admin inicial

- Usuario: `admin`
- Contrasena: `Mateo1997`
- Hash: `pbkdf2:sha256:600000$v3AFpNeY4Ft6jOG6$9f7f3bfac4126c54667af18e09d70df6658a09079ef43b8d47ec54bed7ab58a3`

El INSERT del admin ya esta incluido al final de `schema.sql` con `ON CONFLICT DO NOTHING`,
por lo que es seguro volver a ejecutar el schema sin duplicar el usuario.

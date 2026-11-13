# Panel de expedientes por año de creación

Proyecto didáctico de estructura similar al repositorio `panel-sddi`: un archivo principal `app.py`, dependencias en `requirements.txt` y configuración de Streamlit en `.streamlit/config.toml`.

La aplicación consulta directamente una pestaña de Google Sheets mediante una cuenta de servicio. No utiliza Excel de escritorio, archivos CSV locales ni archivos de datos guardados en el repositorio.

## Estructura

```text
panel-expedientes-anuales/
├── .streamlit/
│   └── config.toml
├── app.py
├── requirements.txt
└── README.md
```

## Columnas que debe tener la Hoja de cálculo de Google

Crea una pestaña llamada `Datos` (o cambia el nombre en Secrets) con estos encabezados en la primera fila:

| Expediente | Fecha de creación | Procedimiento | Equipo | Estado |
|---|---|---|---|---|
| 0001-2024 | 15/01/2024 | Venta directa | Equipo Legal | TRÁMITE |
| 0002-2024 | 20/02/2024 | Transferencia | Equipo Técnico | RESOLUCIÓN EMITIDA |

Usa datos ficticios para el ejercicio. Se admiten alias de encabezados como `Fec_Creacion`, `N° Expediente`, `Trámite`, `Brigada` y `Situación`; el panel permite corregir el mapeo desde el menú lateral.

## Reglas de clasificación

- **Sin Resolución:** SUSPENDIDO CON RESOLUCIÓN, CON FICHA TÉCNICA, TRÁMITE y GENERADO.
- **Con Resolución:** RESOLUCIÓN EMITIDA y RESOLUCIÓN CONSENTIDA.
- Los textos se comparan sin distinguir tildes, mayúsculas ni espacios repetidos.
- Los estados no reconocidos no se incluyen cuando se seleccionan los filtros de las dos categorías.
- Si un expediente aparece más de una vez, se conserva la última fila para evitar doble conteo.

## Conectar la Hoja de cálculo privada

1. En Google Cloud Console, crea un proyecto o selecciona uno existente.
2. Habilita **Google Sheets API** y **Google Drive API**.
3. Crea una cuenta de servicio y genera una clave JSON.
4. Copia el valor `client_email` de esa cuenta de servicio.
5. En Google Sheets, comparte la hoja con ese correo y dale permiso **Lector**. No necesitas publicar la hoja en la web.
6. Copia el ID de la hoja desde su URL: es el texto que aparece entre `/d/` y `/edit`.
7. En Streamlit Community Cloud, al desplegar la aplicación, abre **Advanced settings → Secrets** y pega una configuración TOML con el ID, nombre de pestaña y los campos de la cuenta de servicio.

Plantilla de Secrets (reemplaza todos los valores de ejemplo por los del JSON de tu cuenta de servicio):

```toml
[google_sheets]
spreadsheet_id = "ID_DE_TU_HOJA_DE_CALCULO"
worksheet = "Datos"

[gcp_service_account]
type = "service_account"
project_id = "ID_DEL_PROYECTO"
private_key_id = "ID_DE_LA_CLAVE"
private_key = "-----BEGIN PRIVATE KEY-----\nPEGA_AQUI_LA_CLAVE\n-----END PRIVATE KEY-----\n"
client_email = "cuenta-servicio@proyecto.iam.gserviceaccount.com"
client_id = "ID_CLIENTE"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "URL_DEL_CERTIFICADO"
universe_domain = "googleapis.com"
```

**Seguridad:** nunca pegues la clave privada en `app.py`, `README.md`, `requirements.txt` ni en GitHub. Los secretos se guardan en la configuración de Streamlit Cloud. Si guardas una copia local para pruebas, no la subas al repositorio.

## Desplegar desde GitHub

1. Crea un repositorio nuevo llamado `panel-expedientes-anuales` y elige **Private**.
2. Sube `app.py`, `requirements.txt`, `README.md` y la carpeta `.streamlit` con `config.toml`.
3. Abre Streamlit Community Cloud e inicia sesión con GitHub.
4. Selecciona **Create app** y el repositorio `panel-expedientes-anuales`.
5. Indica la rama `main` y el archivo principal `app.py`.
6. En **Advanced settings → Secrets**, pega la configuración TOML descrita arriba.
7. Selecciona una versión de Python compatible (3.12 es la predeterminada documentada actualmente) y pulsa **Deploy**.

## Nota sobre privacidad

La privacidad del repositorio GitHub y la privacidad de la aplicación Streamlit son controles distintos. Community Cloud permite actualmente una sola aplicación privada por workspace. Si tu aplicación `panel-sddi` ya ocupa ese cupo, puedes mantener este repositorio privado y desplegar el panel didáctico como aplicación pública únicamente con datos ficticios, o utilizar otro servicio de alojamiento para mantener también privada la aplicación.
